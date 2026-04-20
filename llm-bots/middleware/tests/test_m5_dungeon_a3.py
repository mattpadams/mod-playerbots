"""Milestone 5 (phase a3): leader / boss / phase / wipe tests.

Run with::

    cd llm-bots/middleware
    python -m pytest tests/test_m5_dungeon_a3.py -v

Coverage:
  - LeaderTracker election: explicit > matching-role > tank>healer>dps.
  - Boss engaged / defeated events from combat + target match.
  - Phase transitions via target HP crossing thresholds.
  - Party wipe fires once to the leader; resets when anyone revives.
  - Prompt builder surfaces leader + phase-specific role instructions.
  - Policy registry covers all new events.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.bot_registry import BotRegistry
from core.game_client import BotSnapshot
from dungeons.coordinator import DungeonContext, DungeonCoordinator
from dungeons.leader import LeaderCandidate, LeaderTracker
from dungeons.loader import DungeonRegistry
from dungeons.models import Boss, BossPhase, Difficulty, Dungeon, DungeonRole
from game.event_policy import POLICY_REGISTRY, get_policy
from game.events import (
    BossDefeatedEvent,
    BossEngagedEvent,
    BossPhaseChangedEvent,
    DungeonEnteredEvent,
    EventType,
    PartyWipeEvent,
)
from personality.prompt_builder import build_context_message


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

def test_a3_events_registered():
    for et in (
        EventType.BOSS_ENGAGED,
        EventType.BOSS_DEFEATED,
        EventType.BOSS_PHASE_CHANGED,
        EventType.PARTY_WIPE,
    ):
        assert et in POLICY_REGISTRY, et


def test_boss_engaged_policy_is_important_with_cooldown():
    p = get_policy(EventType.BOSS_ENGAGED)
    assert p.invoke_llm is True
    assert p.model_tier == "important"
    assert p.needs_combat_context is True
    assert p.cooldown_seconds > 0


def test_party_wipe_is_important_and_party_aware():
    p = get_policy(EventType.PARTY_WIPE)
    assert p.invoke_llm is True
    assert p.model_tier == "important"
    assert p.needs_party_context is True


def test_boss_defeated_is_bookkeeping_only():
    assert get_policy(EventType.BOSS_DEFEATED).invoke_llm is False


# ---------------------------------------------------------------------------
# Leader election
# ---------------------------------------------------------------------------

def _dungeon_tank_led(leader: DungeonRole = DungeonRole.TANK) -> Dungeon:
    return Dungeon(
        key="d",
        name="D",
        map_id=1,
        expansion="wotlk",
        leader_role=leader,
        bosses=[],
    )


def test_explicit_leader_wins_over_role_match():
    d = _dungeon_tank_led()
    candidates = [
        LeaderCandidate(guid=10, role=DungeonRole.TANK, explicit_leader=False),
        LeaderCandidate(guid=20, role=DungeonRole.HEALER, explicit_leader=True),
    ]
    assert LeaderTracker().resolve(d, candidates) == 20


def test_role_match_beats_rank_fallthrough():
    d = _dungeon_tank_led(leader=DungeonRole.HEALER)
    candidates = [
        LeaderCandidate(guid=10, role=DungeonRole.TANK, explicit_leader=False),
        LeaderCandidate(guid=20, role=DungeonRole.HEALER, explicit_leader=False),
    ]
    # Dungeon wants healer-led, so the healer should lead even though
    # tank would normally outrank.
    assert LeaderTracker().resolve(d, candidates) == 20


def test_fallthrough_prefers_tank_over_healer_over_dps():
    d = _dungeon_tank_led(leader=DungeonRole.HEALER)
    # No healers available → fall through to role-rank (tank wins).
    candidates = [
        LeaderCandidate(guid=20, role=DungeonRole.DPS, explicit_leader=False),
        LeaderCandidate(guid=10, role=DungeonRole.TANK, explicit_leader=False),
    ]
    assert LeaderTracker().resolve(d, candidates) == 10


def test_leader_recomputes_only_on_membership_change():
    d = _dungeon_tank_led()
    tracker = LeaderTracker()
    a = [LeaderCandidate(10, DungeonRole.TANK, False)]
    assert tracker.resolve(d, a) == 10
    # Same membership, same result without reclassifying.
    assert tracker.resolve(d, a) == 10
    # Membership changes → may re-elect.
    b = [
        LeaderCandidate(10, DungeonRole.TANK, False),
        LeaderCandidate(5, DungeonRole.TANK, False),
    ]
    # Both are tanks → lowest GUID among matching-role wins.
    assert tracker.resolve(d, b) == 5


def test_leader_empty_membership_returns_none():
    d = _dungeon_tank_led()
    assert LeaderTracker().resolve(d, []) is None


# ---------------------------------------------------------------------------
# Coordinator fixtures (mirror a2 setup)
# ---------------------------------------------------------------------------

def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def registry(tmp_path: Path) -> DungeonRegistry:
    _write(
        tmp_path / "keep.yaml",
        """
key: keep
name: Keep
map_id: 999
sub_zone: null
expansion: wotlk
difficulty: normal
overlay_of: null
strategy_key: null
cpp_coverage: partial
min_level: 68
max_level: 72
leader_role: tank
general_notes: Tank leads.
bosses:
  - name: Boss One
    order: 1
    aliases: [BossAlpha]
    phases:
      - name: Phase 1
        hp_threshold: null
        description: open
        tank: Face boss away
        healer: Top tank
        dps: Burn
        mechanics: [Keep back]
      - name: Phase 2
        hp_threshold: 50
        description: enrage
        tank: Use cooldowns
        healer: Save big heal
        dps: Avoid new pools
        mechanics: [Fire pools spawn]
      - name: Phase 3
        hp_threshold: 20
        description: execute
        tank: Hold threat
        healer: Spam heals
        dps: Execute
        mechanics: [Execute below 20]
""".lstrip(),
    )
    reg = DungeonRegistry()
    reg.load_dir(tmp_path)
    return reg


@pytest.fixture
def bot_registry() -> BotRegistry:
    br = BotRegistry()
    br.elevate(10, "Thrargor", "base")   # warrior/arms → dps
    return br


def _snap(
    guid: int,
    *,
    map_id: int = 999,
    state: str = "non-combat",
    target: str = "",
    target_hp: int | None = None,
    zone: str = "Keep",
    strategy: str = "combat",
    level: int = 70,
) -> BotSnapshot:
    return BotSnapshot(
        guid=guid,
        map_id=map_id,
        state=state,
        target_name=target,
        target_hp_pct=target_hp,
        zone=zone,
        strategy=strategy,
        level=level,
    )


@pytest.fixture
def coord(registry: DungeonRegistry, bot_registry: BotRegistry):
    executor = AsyncMock()
    executor.execute = AsyncMock(return_value="ok")
    return (
        DungeonCoordinator(
            registry=bot_registry,
            command_executor=executor,
            dungeon_registry=registry,
        ),
        bot_registry,
    )


# ---------------------------------------------------------------------------
# Boss engagement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_boss_engaged_fires_on_combat_start(coord):
    c, _ = coord
    # First tick: enter dungeon.
    await c.update({10: _snap(10, map_id=0, zone="Stormwind")})
    await c.update({10: _snap(10)})
    c.pop_events()  # drain dungeon entered

    # Combat against a boss → engaged.
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=100)}
    )
    events = c.pop_events()
    engaged = [e for e in events if isinstance(e, BossEngagedEvent)]
    assert len(engaged) == 1
    assert engaged[0].boss_name == "Boss One"
    assert engaged[0].is_leader  # solo bot → leader


@pytest.mark.asyncio
async def test_boss_engaged_not_refired_while_fighting(coord):
    c, _ = coord
    await c.update({10: _snap(10, map_id=0)})
    await c.update({10: _snap(10)})
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=100)}
    )
    c.pop_events()
    # Same boss, still in combat — no new engage.
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=80)}
    )
    assert [e for e in c.pop_events() if isinstance(e, BossEngagedEvent)] == []


@pytest.mark.asyncio
async def test_boss_defeated_fires_on_combat_end(coord):
    c, _ = coord
    await c.update({10: _snap(10, map_id=0)})
    await c.update({10: _snap(10)})
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=100)}
    )
    c.pop_events()
    await c.update({10: _snap(10, state="non-combat")})
    events = c.pop_events()
    defeated = [e for e in events if isinstance(e, BossDefeatedEvent)]
    assert len(defeated) == 1
    assert defeated[0].boss_name == "Boss One"


# ---------------------------------------------------------------------------
# Phase transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phase_transitions_follow_hp(coord):
    c, _ = coord
    await c.update({10: _snap(10, map_id=0)})
    await c.update({10: _snap(10)})
    # Engage at 100%.
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=100)}
    )
    c.pop_events()

    # Cross 50% → phase 1.
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=50)}
    )
    evs = [e for e in c.pop_events() if isinstance(e, BossPhaseChangedEvent)]
    assert len(evs) == 1
    assert evs[0].phase_index == 1
    assert evs[0].phase_name == "Phase 2"

    # Cross 20% → phase 2 (third entry).
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=20)}
    )
    evs = [e for e in c.pop_events() if isinstance(e, BossPhaseChangedEvent)]
    assert len(evs) == 1
    assert evs[0].phase_index == 2


@pytest.mark.asyncio
async def test_phase_does_not_go_backwards(coord):
    c, _ = coord
    await c.update({10: _snap(10, map_id=0)})
    await c.update({10: _snap(10)})
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=40)}
    )
    # Engage already past 50% threshold → initial phase_index should
    # snap forward to the current one (2 — past both 50 and 20? no, 40 > 20).
    c.pop_events()
    # Later HP goes back up (heal) — must not emit phase-back event.
    await c.update(
        {10: _snap(10, state="combat", target="Boss One", target_hp=80)}
    )
    assert [
        e for e in c.pop_events() if isinstance(e, BossPhaseChangedEvent)
    ] == []


# ---------------------------------------------------------------------------
# Wipe detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wipe_fires_once_to_leader(coord):
    c, br = coord
    br.elevate(20, "Mirelle", "base")  # second bot in dungeon

    # Both enter dungeon.
    await c.update({10: _snap(10, map_id=0), 20: _snap(20, map_id=0)})
    await c.update({10: _snap(10), 20: _snap(20)})
    c.pop_events()

    # Both die.
    await c.update(
        {10: _snap(10, state="dead"), 20: _snap(20, state="dead")}
    )
    wipes = [e for e in c.pop_events() if isinstance(e, PartyWipeEvent)]
    assert len(wipes) == 1
    # Leader is deterministic: lowest-guid tank-rank peer (both are dps,
    # so role-rank + guid tiebreak → guid 10).
    assert wipes[0].bot_guid == 10
    assert set(wipes[0].dead_bot_names) == {"Thrargor", "Mirelle"}

    # Still all dead next tick — no re-emit.
    await c.update(
        {10: _snap(10, state="dead"), 20: _snap(20, state="dead")}
    )
    assert [e for e in c.pop_events() if isinstance(e, PartyWipeEvent)] == []


@pytest.mark.asyncio
async def test_wipe_re_arms_after_revive(coord):
    c, br = coord
    br.elevate(20, "Mirelle", "base")
    await c.update({10: _snap(10, map_id=0), 20: _snap(20, map_id=0)})
    await c.update({10: _snap(10), 20: _snap(20)})
    await c.update(
        {10: _snap(10, state="dead"), 20: _snap(20, state="dead")}
    )
    c.pop_events()

    # Someone revives.
    await c.update(
        {10: _snap(10, state="non-combat"), 20: _snap(20, state="dead")}
    )
    c.pop_events()

    # All die again → second wipe.
    await c.update(
        {10: _snap(10, state="dead"), 20: _snap(20, state="dead")}
    )
    wipes = [e for e in c.pop_events() if isinstance(e, PartyWipeEvent)]
    assert len(wipes) == 1


# ---------------------------------------------------------------------------
# Prompt builder — a3 additions
# ---------------------------------------------------------------------------

def _three_phase_boss() -> Boss:
    return Boss(
        name="Boss One",
        order=1,
        aliases=[],
        phases=[
            BossPhase(name="Phase 1", tank="Open tank", dps="Open dps"),
            BossPhase(
                name="Phase 2",
                hp_threshold=50,
                tank="P2 tank",
                dps="P2 dps",
                mechanics=["Fire pools"],
            ),
        ],
    )


def _mini_dungeon() -> Dungeon:
    return Dungeon(
        key="keep",
        name="Keep",
        map_id=999,
        expansion="wotlk",
        difficulty=Difficulty.NORMAL,
        cpp_coverage="partial",
        leader_role=DungeonRole.TANK,
        general_notes="",
        bosses=[_three_phase_boss()],
    )


def test_prompt_uses_current_phase_role_text():
    d = _mini_dungeon()
    ctx = DungeonContext(
        dungeon=d, role=DungeonRole.DPS, current_boss=d.bosses[0],
        phase_index=1, is_leader=False,
    )
    msg = build_context_message(
        snapshot=BotSnapshot(guid=1, target_name="Boss One"),
        recent_events=[], memories=[], triggering_event="x",
        dungeon_context=ctx,
    )
    assert "Phase 2" in msg
    assert "P2 dps" in msg
    assert "Open dps" not in msg
    assert "Fire pools" in msg


def test_prompt_marks_leader_and_adds_callout_instruction():
    d = _mini_dungeon()
    ctx = DungeonContext(
        dungeon=d, role=DungeonRole.TANK, current_boss=d.bosses[0],
        phase_index=0, is_leader=True,
    )
    msg = build_context_message(
        snapshot=BotSnapshot(guid=1, target_name="Boss One"),
        recent_events=[], memories=[], triggering_event="x",
        dungeon_context=ctx,
    )
    assert "(PARTY LEADER)" in msg
    assert "party leader" in msg.lower()
    assert "Call pulls" in msg
