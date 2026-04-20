"""Milestone 4: Party coordination tests.

Run with::

    cd llm-bots/middleware
    python -m pytest tests/test_m4_party.py -v

Coverage:
  - Gear tiebreak ladder: score delta → level → role
  - ArbitrationEngine winner selection + exclude filter
  - SharedQuestTracker emits PartyQuestProgressEvent on every pickup
  - RosterTracker parses Name:Class:HpPct|... and groups by party
  - PartyState.to_prompt_section() renders members + shared quests
  - LootRollHandler dispatches pass-commands to losers
  - policy registry covers all new events
  - quest_tools / party_tools build the right BotCommand payloads
  - [PARTY STATE] prompt injection appears only when partied
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.game_client import BotSnapshot
from game.commands import CommandType
from game.event_policy import POLICY_REGISTRY, get_policy
from game.events import (
    EventType,
    LootRollStartedEvent,
    PartyQuestProgressEvent,
    VendorNearbyEvent,
)
from party.arbitration import ArbitrationEngine
from party.gear_scorer import gear_eligible, gear_score
from party.loot_roll_handler import LootRollHandler
from party.models import (
    ROLE_RANK_BOT_DPS,
    ROLE_RANK_BOT_HEALER,
    ROLE_RANK_BOT_TANK,
    ROLE_RANK_PLAYER,
    PartyMember,
    PartyState,
    QuestProgress,
    RollCandidate,
)
from party.quest_tracker import SharedQuestTracker, _parse
from party.roster import RosterTracker


# ---------------------------------------------------------------------------
# Policies & events
# ---------------------------------------------------------------------------

def test_every_event_type_has_a_policy():
    missing = [e for e in EventType if e not in POLICY_REGISTRY]
    assert not missing, f"EventTypes missing from POLICY_REGISTRY: {missing}"


def test_loot_roll_policy_urgent_and_party_aware():
    p = get_policy(EventType.LOOT_ROLL_STARTED)
    assert p.invoke_llm is True
    assert p.model_tier == "important"
    assert p.needs_party_context is True
    assert p.cooldown_seconds == 0.0


def test_vendor_nearby_does_not_invoke_llm():
    assert get_policy(EventType.VENDOR_NEARBY).invoke_llm is False


def test_party_quest_progress_uses_default_model_with_cooldown():
    p = get_policy(EventType.PARTY_QUEST_PROGRESS)
    assert p.model_tier == "default"
    assert p.needs_party_context is True
    assert p.cooldown_seconds > 0


# ---------------------------------------------------------------------------
# Arbitration + gear scorer
# ---------------------------------------------------------------------------

def _candidate(
    guid: int,
    *,
    score: float,
    level: int,
    role: int,
    name: str = "",
) -> RollCandidate:
    return RollCandidate(
        guid=guid,
        name=name or f"Bot{guid}",
        score_delta=score,
        level=level,
        role_rank=role,
    )


def test_arbitration_picks_highest_score_delta_first():
    arb = ArbitrationEngine()
    cands = [
        _candidate(1, score=5, level=80, role=ROLE_RANK_BOT_TANK),
        _candidate(2, score=10, level=70, role=ROLE_RANK_BOT_DPS),
        _candidate(3, score=8, level=80, role=ROLE_RANK_PLAYER),
    ]
    winner = arb.pick_winner(cands, score_fn=gear_score)
    assert winner.guid == 2


def test_arbitration_ties_broken_by_level_then_role():
    arb = ArbitrationEngine()
    # All tied on score — level breaks tie, then role
    cands = [
        _candidate(1, score=5, level=70, role=ROLE_RANK_BOT_TANK),
        _candidate(2, score=5, level=80, role=ROLE_RANK_BOT_DPS),
        _candidate(3, score=5, level=80, role=ROLE_RANK_PLAYER),
    ]
    winner = arb.pick_winner(cands, score_fn=gear_score)
    assert winner.guid == 3  # level 80 + player rank beats level 80 dps


def test_arbitration_ties_broken_by_role_when_level_equal():
    arb = ArbitrationEngine()
    cands = [
        _candidate(1, score=5, level=80, role=ROLE_RANK_BOT_DPS),
        _candidate(2, score=5, level=80, role=ROLE_RANK_BOT_HEALER),
        _candidate(3, score=5, level=80, role=ROLE_RANK_BOT_TANK),
    ]
    winner = arb.pick_winner(cands, score_fn=gear_score)
    assert winner.guid == 3  # tank outranks healer outranks dps


def test_gear_ineligible_if_score_not_positive():
    assert not gear_eligible(_candidate(1, score=0, level=80, role=0))
    assert not gear_eligible(_candidate(1, score=-1, level=80, role=0))
    assert gear_eligible(_candidate(1, score=0.1, level=80, role=0))


def test_arbitration_excludes_ineligible_candidates():
    arb = ArbitrationEngine()
    cands = [
        _candidate(1, score=100, level=80, role=ROLE_RANK_BOT_DPS),  # -> excluded below
        _candidate(2, score=1, level=50, role=ROLE_RANK_BOT_HEALER),
    ]
    # Exclude guid 1
    winner = arb.pick_winner(
        cands, score_fn=gear_score, exclude=lambda c: c.guid == 1
    )
    assert winner.guid == 2


def test_arbitration_returns_none_on_empty():
    arb = ArbitrationEngine()
    assert arb.pick_winner([], score_fn=gear_score) is None


# ---------------------------------------------------------------------------
# Quest tracker parser
# ---------------------------------------------------------------------------

def test_parse_quests_line_format():
    raw = "123:Wolf Slayer:Wolf Pelt:3:5;124:Kobold Hunt:Kobold Ear:0:10"
    parsed = _parse(raw)
    assert len(parsed) == 2
    k = (123, "Wolf Pelt")
    assert k in parsed
    assert parsed[k].current == 3
    assert parsed[k].required == 5
    assert parsed[k].quest_name == "Wolf Slayer"


def test_parse_quests_empty_string():
    assert _parse("") == {}


def test_parse_quests_malformed_lines_skipped():
    raw = "bad;123:Name:Item:1:2;;missing:fields"
    parsed = _parse(raw)
    assert len(parsed) == 1


@pytest.mark.asyncio
async def test_quest_tracker_emits_event_on_every_pickup():
    tracker = SharedQuestTracker()
    fake_game = MagicMock()
    fake_game.query = AsyncMock(
        side_effect=[
            # First tick: bot 1 has 1/5, bot 2 has 0/5
            "5:Collect:Mageroyal:1:5",
            "5:Collect:Mageroyal:0:5",
        ]
    )
    snapshots = {1: BotSnapshot(guid=1), 2: BotSnapshot(guid=2)}
    events = await tracker.update(
        fake_game, snapshots, partied_guids={1, 2}, name_lookup=lambda g: f"Bot{g}"
    )
    # Both bots had new objectives → both fire an initial event
    assert len(events) == 2
    assert all(e.item_name == "Mageroyal" for e in events)
    # Events carry real bot names, not state strings
    assert {e.bot_name for e in events} == {"Bot1", "Bot2"}
    assert {e.picker_name for e in events} == {"Bot1", "Bot2"}

    # Second tick: bot 1 picked up another; bot 2 unchanged → one event
    fake_game.query = AsyncMock(
        side_effect=[
            "5:Collect:Mageroyal:2:5",
            "5:Collect:Mageroyal:0:5",
        ]
    )
    events2 = await tracker.update(
        fake_game, snapshots, partied_guids={1, 2}, name_lookup=lambda g: f"Bot{g}"
    )
    assert len(events2) == 1
    assert events2[0].new_count == 2
    assert events2[0].picker_guid == 1


@pytest.mark.asyncio
async def test_quest_tracker_skips_solo_bots():
    """Solo bots produce no quest progress events and no TCP queries."""
    tracker = SharedQuestTracker()
    fake_game = MagicMock()
    fake_game.query = AsyncMock(return_value="5:q:Item:1:5")
    events = await tracker.update(
        fake_game,
        {1: BotSnapshot(guid=1)},
        partied_guids=set(),
        name_lookup=lambda g: f"Bot{g}",
    )
    assert events == []
    fake_game.query.assert_not_called()


@pytest.mark.asyncio
async def test_quest_tracker_ignores_count_decrease():
    tracker = SharedQuestTracker()
    fake_game = MagicMock()
    fake_game.query = AsyncMock(return_value="5:q:Item:3:5")
    await tracker.update(fake_game, {1: BotSnapshot(guid=1)}, partied_guids={1})
    # Now count decreased (turn-in) — no event expected
    fake_game.query = AsyncMock(return_value="5:q:Item:0:5")
    events = await tracker.update(
        fake_game, {1: BotSnapshot(guid=1)}, partied_guids={1}
    )
    assert events == []


def test_tracked_guids_public_api():
    """Coordinator uses this; no private-attribute leak."""
    tracker = SharedQuestTracker()
    tracker._per_bot[7] = {}
    tracker._per_bot[9] = {}
    assert tracker.tracked_guids() == {7, 9}
    tracker.forget({7})
    assert tracker.tracked_guids() == {9}


def test_shared_progress_fans_across_members():
    tracker = SharedQuestTracker()
    tracker._per_bot[1] = _parse("5:q:Item:3:5")
    tracker._per_bot[2] = _parse("5:q:Item:1:5")
    members = [PartyMember(guid=1, name="A"), PartyMember(guid=2, name="B")]
    shared = tracker.shared_progress(members)
    assert len(shared) == 1
    qp = shared[0]
    assert qp.member_current(1) == 3
    assert qp.member_current(2) == 1


# ---------------------------------------------------------------------------
# Roster parsing
# ---------------------------------------------------------------------------

def test_roster_parses_pipe_separated_triples():
    from core.bot_registry import BotRegistry

    class _FakeGame:
        async def query(self, guid, cmd):
            return ""

    reg = BotRegistry()
    reg.elevate(1, "Mirelle")
    reg.elevate(2, "Thrargor")
    tracker = RosterTracker(_FakeGame(), reg)
    members = tracker._parse_roster(
        "Mirelle:Priest:100|Thrargor:Warrior:75|Gob:Rogue:50",
        leader_guid=1,
        snap=BotSnapshot(guid=1),
    )
    names = [m.name for m in members]
    assert names == ["Mirelle", "Thrargor", "Gob"]
    # Mirelle and Thrargor are elevated → not players; Gob is a human
    assert not members[0].is_player
    assert not members[1].is_player
    assert members[2].is_player
    assert members[1].hp_pct == 75


def test_roster_empty_returns_no_members():
    from core.bot_registry import BotRegistry

    class _FakeGame:
        async def query(self, guid, cmd):
            return ""

    tracker = RosterTracker(_FakeGame(), BotRegistry())
    assert tracker._parse_roster("", leader_guid=1, snap=BotSnapshot(guid=1)) == []


# ---------------------------------------------------------------------------
# PartyState prompt rendering
# ---------------------------------------------------------------------------

def test_party_state_renders_members_and_quests():
    members = (
        PartyMember(guid=1, name="Mirelle", cls="priest", spec_role="healer", level=12, hp_pct=80),
        PartyMember(guid=2, name="Thrargor", cls="warrior", spec_role="tank", level=11, hp_pct=100),
    )
    quests = (
        QuestProgress(
            quest_id=5,
            quest_name="Gather Herbs",
            item_name="Mageroyal",
            per_member={1: (2, 5), 2: (1, 5)},
        ),
    )
    state = PartyState(party_id="abc", members=members, shared_quests=quests)
    section = state.to_prompt_section()
    assert "[PARTY STATE]" in section
    assert "Mirelle" in section
    assert "Thrargor" in section
    assert "Mageroyal" in section
    assert "2/5" in section
    assert "1/5" in section


def test_party_state_solo_renders_nothing():
    members = (PartyMember(guid=1, name="Mirelle"),)
    state = PartyState(party_id="abc", members=members)
    assert state.to_prompt_section() == ""


def test_prompt_builder_includes_party_state_when_partied():
    from personality.prompt_builder import build_context_message

    members = (
        PartyMember(guid=1, name="Mirelle", cls="priest", spec_role="healer", hp_pct=80),
        PartyMember(guid=2, name="Thrargor", cls="warrior", spec_role="tank", hp_pct=100),
    )
    state = PartyState(party_id="abc", members=members)
    snap = BotSnapshot(guid=1, state="non-combat")
    msg = build_context_message(
        snapshot=snap,
        recent_events=[],
        memories=[],
        triggering_event="Something happened.",
        combat_context=None,
        party_state=state,
    )
    assert "[PARTY STATE]" in msg


def test_prompt_builder_omits_party_state_when_solo():
    from personality.prompt_builder import build_context_message

    msg = build_context_message(
        snapshot=BotSnapshot(guid=1),
        recent_events=[],
        memories=[],
        triggering_event="...",
        party_state=PartyState(party_id="abc", members=()),
    )
    assert "[PARTY STATE]" not in msg


# ---------------------------------------------------------------------------
# LootRollHandler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loot_handler_tells_losers_to_pass_and_returns_winner_event():
    executor = MagicMock()
    executor.execute = AsyncMock(return_value="")
    handler = LootRollHandler(ArbitrationEngine(), executor)

    candidates = [
        _candidate(1, score=2, level=80, role=ROLE_RANK_BOT_DPS, name="A"),
        _candidate(2, score=10, level=80, role=ROLE_RANK_BOT_TANK, name="B"),
        _candidate(3, score=5, level=80, role=ROLE_RANK_BOT_HEALER, name="C"),
    ]
    event = await handler.handle(
        roll_id="r1",
        item_id=123,
        item_link="item:123",
        item_name="Epic Sword",
        candidates=candidates,
    )
    assert isinstance(event, LootRollStartedEvent)
    assert event.bot_guid == 2  # winner
    # Losers (guid 1 and 3) receive pass commands; winner does NOT.
    sent_guids = [
        call.args[0].bot_guid for call in executor.execute.call_args_list
    ]
    assert set(sent_guids) == {1, 3}
    for call in executor.execute.call_args_list:
        cmd = call.args[0]
        assert cmd.command_type == CommandType.LOOT_ROLL
        assert cmd.payload["decision"] == "pass"


@pytest.mark.asyncio
async def test_loot_handler_no_eligible_candidates_returns_none():
    executor = MagicMock()
    executor.execute = AsyncMock(return_value="")
    handler = LootRollHandler(ArbitrationEngine(), executor)
    # All candidates have non-positive deltas → ineligible
    candidates = [
        _candidate(1, score=0, level=80, role=ROLE_RANK_BOT_DPS),
        _candidate(2, score=-1, level=80, role=ROLE_RANK_BOT_TANK),
    ]
    event = await handler.handle(
        roll_id="r2",
        item_id=1,
        item_link="item:1",
        item_name="",
        candidates=candidates,
    )
    assert event is None
    executor.execute.assert_not_called()


@pytest.mark.asyncio
async def test_loot_handler_deduplicates_same_roll_id():
    """Multiple POSTs for the same roll_id (duplicate bots hitting the
    defer branch in the same tick) must not re-arbitrate."""
    executor = MagicMock()
    executor.execute = AsyncMock(return_value="")
    handler = LootRollHandler(ArbitrationEngine(), executor)
    candidates = [
        _candidate(1, score=2, level=80, role=ROLE_RANK_BOT_DPS),
        _candidate(2, score=10, level=80, role=ROLE_RANK_BOT_TANK),
    ]
    event1 = await handler.handle(
        roll_id="r3",
        item_id=5,
        item_link="item:5",
        item_name="X",
        candidates=candidates,
    )
    first_call_count = executor.execute.call_count

    # Second POST with same roll_id — must be ignored
    event2 = await handler.handle(
        roll_id="r3",
        item_id=5,
        item_link="item:5",
        item_name="X",
        candidates=candidates,
    )
    assert event1 is not None
    assert event2 is None
    # No additional pass-commands dispatched the second time around.
    assert executor.execute.call_count == first_call_count


# ---------------------------------------------------------------------------
# PartyCoordinator filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_coordinator_filters_non_elevated_candidates_from_arbitration():
    """Real players and non-elevated bots must not be arbitration winners
    — the middleware can't drive their rolls."""
    from core.bot_registry import BotRegistry
    from party.coordinator import PartyCoordinator

    class _Stub:
        async def query(self, guid, cmd):
            return ""

    registry = BotRegistry()
    registry.elevate(100, "ElevatedBot")
    executor = MagicMock()
    executor.execute = AsyncMock(return_value="")
    coord = PartyCoordinator(_Stub(), registry, executor)

    # Seed the roster so _roster_member() returns a real entry.
    from party.models import PartyMember
    coord._roster._guid_to_party[100] = "party-x"
    coord._roster._parties["party-x"] = type(
        "G", (), {"members": [PartyMember(guid=100, name="ElevatedBot")]}
    )()

    # 50 is a human player (not elevated), 100 is elevated.
    event = await coord.on_loot_roll_started(
        roll_id="rX",
        item_id=1,
        item_link="item:1",
        item_name="",
        candidate_guids=[50, 100],
        item_scores={50: 100.0, 100: 5.0},
    )
    # Despite the human having a far better score, the elevated bot
    # wins because non-elevated candidates are filtered out.
    assert event is not None
    assert event.bot_guid == 100


@pytest.mark.asyncio
async def test_coordinator_returns_none_when_no_elevated_candidates():
    from core.bot_registry import BotRegistry
    from party.coordinator import PartyCoordinator

    class _Stub:
        async def query(self, guid, cmd):
            return ""

    registry = BotRegistry()
    executor = MagicMock()
    executor.execute = AsyncMock(return_value="")
    coord = PartyCoordinator(_Stub(), registry, executor)

    event = await coord.on_loot_roll_started(
        roll_id="rY",
        item_id=1,
        item_link="item:1",
        item_name="",
        candidate_guids=[1, 2, 3],
    )
    assert event is None
    executor.execute.assert_not_called()


@pytest.mark.asyncio
async def test_coordinator_skips_candidates_with_stale_roster():
    """When a candidate's roster isn't cached, drop them rather than
    fabricating wrong defaults (level=0, spec_role=dps)."""
    from core.bot_registry import BotRegistry
    from party.coordinator import PartyCoordinator

    class _Stub:
        async def query(self, guid, cmd):
            return ""

    registry = BotRegistry()
    registry.elevate(100, "ElevatedBot")
    executor = MagicMock()
    executor.execute = AsyncMock(return_value="")
    coord = PartyCoordinator(_Stub(), registry, executor)

    # Elevated, but no roster entry → skipped by _roster_member.
    event = await coord.on_loot_roll_started(
        roll_id="rZ",
        item_id=1,
        item_link="item:1",
        item_name="",
        candidate_guids=[100],
    )
    assert event is None


# ---------------------------------------------------------------------------
# Command executor dispatch for new M4 types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_command_executor_trade_item_sends_t_command():
    from core.command_executor import CommandExecutor
    from game.commands import BotCommand

    game = MagicMock()
    game.send_command = AsyncMock(return_value="")
    executor = CommandExecutor(game, MagicMock())
    await executor.execute(
        BotCommand(
            command_type=CommandType.TRADE_ITEM,
            bot_guid=1,
            payload={"target_player": "Mirelle", "item_link": "item:5", "count": 3},
        )
    )
    game.send_command.assert_awaited_once()
    _, sent = game.send_command.call_args.args
    assert sent.startswith("t ")
    assert "Mirelle" in sent
    assert "3" in sent


@pytest.mark.asyncio
async def test_command_executor_loot_roll_pass():
    from core.command_executor import CommandExecutor
    from game.commands import BotCommand

    game = MagicMock()
    game.send_command = AsyncMock(return_value="")
    executor = CommandExecutor(game, MagicMock())
    await executor.execute(
        BotCommand(
            command_type=CommandType.LOOT_ROLL,
            bot_guid=1,
            payload={"decision": "pass", "item_link": "item:9"},
        )
    )
    _, sent = game.send_command.call_args.args
    assert sent == "roll pass item:9"


@pytest.mark.asyncio
async def test_command_executor_cast_spell_on_target():
    from core.command_executor import CommandExecutor
    from game.commands import BotCommand

    game = MagicMock()
    game.send_command = AsyncMock(return_value="")
    executor = CommandExecutor(game, MagicMock())
    await executor.execute(
        BotCommand(
            command_type=CommandType.CAST_SPELL,
            bot_guid=1,
            payload={"spell": "Lesser Heal", "target": "Henze Faulk"},
        )
    )
    _, sent = game.send_command.call_args.args
    assert sent == "cast Lesser Heal Henze Faulk"


@pytest.mark.asyncio
async def test_command_executor_vendor_sell_gray():
    from core.command_executor import CommandExecutor
    from game.commands import BotCommand

    game = MagicMock()
    game.send_command = AsyncMock(return_value="")
    executor = CommandExecutor(game, MagicMock())
    await executor.execute(
        BotCommand(
            command_type=CommandType.VENDOR_SELL,
            bot_guid=1,
            payload={"filter": "gray"},
        )
    )
    _, sent = game.send_command.call_args.args
    assert sent == "s gray"
