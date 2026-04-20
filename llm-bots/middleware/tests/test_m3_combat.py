"""Milestone 3: Combat Integration tests.

Run with:
    cd llm-bots/middleware
    python -m pytest tests/test_m3_combat.py -v

These verify the new abstractions introduced in M3:
  - EventPolicy registry replaces scattered if-chains
  - DebounceFilter suppresses HEALTH_CRITICAL spam during HP oscillation
  - CombatContext parses the C++ values/party TCP responses safely
  - prompt_builder renders [COMBAT SITUATION] only when supplied
  - raid_tools build the right BotCommand payloads
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from combat.context import CombatContext
from combat.models import PartyMember
from combat.snapshot_queries import parse_party, parse_values_attackers
from core.game_client import BotSnapshot
from game.debounce import DebounceFilter
from game.event_policy import POLICY_REGISTRY, get_policy
from game.events import (
    ChatReceivedEvent,
    CombatEndEvent,
    CombatStartEvent,
    EventType,
    HealthCriticalEvent,
    IdleTickEvent,
    TargetChangedEvent,
)
from personality.prompt_builder import build_context_message


# ---------------------------------------------------------------------------
# EventPolicy registry
# ---------------------------------------------------------------------------

def test_every_event_type_has_a_policy():
    """The registry must cover every EventType so nothing falls into the
    silent fallback by accident."""
    missing = [e for e in EventType if e not in POLICY_REGISTRY]
    assert not missing, f"EventTypes missing from POLICY_REGISTRY: {missing}"


def test_combat_start_uses_important_model():
    assert get_policy(EventType.COMBAT_START).model_tier == "important"


def test_health_critical_uses_important_model_and_needs_combat_context():
    p = get_policy(EventType.HEALTH_CRITICAL)
    assert p.model_tier == "important"
    assert p.needs_combat_context is True
    assert p.cooldown_seconds == 30.0


def test_combat_end_does_not_invoke_llm():
    assert get_policy(EventType.COMBAT_END).invoke_llm is False


def test_health_critical_higher_priority_than_combat_start():
    """HEALTH_CRITICAL is more urgent than COMBAT_START — should sort first."""
    assert get_policy(EventType.HEALTH_CRITICAL).priority < get_policy(
        EventType.COMBAT_START
    ).priority


# ---------------------------------------------------------------------------
# DebounceFilter
# ---------------------------------------------------------------------------

def test_health_critical_passes_first_time():
    f = DebounceFilter()
    events = [HealthCriticalEvent(bot_guid=1, hp_pct=15)]
    result = f.filter(events, current_hp_pct=15)
    assert len(result) == 1


def test_health_critical_blocked_within_cooldown():
    """A second HEALTH_CRITICAL within the cooldown is dropped, even after
    HP swings back below the threshold."""
    f = DebounceFilter()
    f.filter([HealthCriticalEvent(bot_guid=1, hp_pct=15)], current_hp_pct=15)
    # Second event arrives — cooldown not elapsed
    result = f.filter(
        [HealthCriticalEvent(bot_guid=1, hp_pct=10)], current_hp_pct=10
    )
    assert result == []


def test_health_critical_fires_again_after_cooldown_even_without_hp_recovery():
    """Regression guard: if a bot's HP stays critically low, the
    cooldown alone should eventually allow the LLM to re-evaluate.
    Earlier designs required HP to recover above 40% first; that rule
    was dropped because the diff only fires on threshold *crossings*
    anyway, and the extra gate could silence legitimate re-evaluations
    during sustained raid fights."""
    with patch("game.debounce.time.monotonic") as mock_now:
        mock_now.return_value = 1000.0
        f = DebounceFilter()

        # First firing
        assert len(f.filter(
            [HealthCriticalEvent(bot_guid=1, hp_pct=15)], current_hp_pct=15
        )) == 1

        # Immediately after: within cooldown, suppressed
        mock_now.return_value = 1005.0
        assert f.filter(
            [HealthCriticalEvent(bot_guid=1, hp_pct=15)], current_hp_pct=15
        ) == []

        # 31 seconds later — HP still low, but cooldown elapsed
        mock_now.return_value = 1031.0
        result = f.filter(
            [HealthCriticalEvent(bot_guid=1, hp_pct=15)], current_hp_pct=15
        )
        assert len(result) == 1


def test_combat_start_never_debounced():
    """COMBAT_START has no cooldown — fires every time."""
    f = DebounceFilter()
    e = CombatStartEvent(bot_guid=1, target_name="Lich King")
    assert len(f.filter([e], current_hp_pct=80)) == 1
    assert len(f.filter([e], current_hp_pct=80)) == 1


def test_invoke_llm_false_events_pass_through():
    """COMBAT_END is recorded for the buffer even though it never triggers
    an LLM call. The filter should not drop it."""
    f = DebounceFilter()
    result = f.filter([CombatEndEvent(bot_guid=1)], current_hp_pct=100)
    assert len(result) == 1


def test_filter_reset_clears_state():
    f = DebounceFilter()
    f.filter([HealthCriticalEvent(bot_guid=1, hp_pct=15)], current_hp_pct=15)
    f.reset()
    # First-shot semantics restored
    result = f.filter(
        [HealthCriticalEvent(bot_guid=1, hp_pct=10)], current_hp_pct=10
    )
    assert len(result) == 1


# ---------------------------------------------------------------------------
# values + party parsers
# ---------------------------------------------------------------------------

def test_parse_values_extracts_known_keys():
    raw = "{attackers count=3}|{my attackers count=1}|{balance percentage=72}|{other=foo}"
    attackers, my_attackers, balance = parse_values_attackers(raw)
    assert attackers == 3
    assert my_attackers == 1
    assert balance == 72


def test_parse_values_returns_defaults_on_empty():
    assert parse_values_attackers("") == (0, 0, 100)


def test_parse_values_returns_defaults_on_malformed():
    """Garbage in, sensible defaults out — should never raise."""
    assert parse_values_attackers("not a values dump at all") == (0, 0, 100)


def test_parse_values_handles_missing_keys():
    """When only one key is present, others fall back to defaults."""
    a, m, b = parse_values_attackers("{attackers count=5}")
    assert (a, m, b) == (5, 0, 100)


def test_parse_values_handles_raw_byte_values():
    """Older mod-playerbots builds emitted uint8 values as raw bytes —
    the parser should interpret a single byte as its ordinal value."""
    raw = "{attackers count=\x03}|{my attacker count=\x01}"
    a, m, _ = parse_values_attackers(raw)
    assert a == 3
    assert m == 1


def test_parse_values_accepts_singular_my_attacker_count():
    """mod-playerbots has an inconsistency: the value's default class
    name is 'my attackers count' (plural) but triggers reference it as
    'my attacker count' (singular). Accept either."""
    a, m, _ = parse_values_attackers("{my attacker count=4}")
    assert m == 4


def test_parse_party_pipe_delimited():
    members = parse_party("Elariel:Priest:92|Shadowstep:Rogue:78|Frostweave:Mage:95")
    assert len(members) == 3
    assert members[0].name == "Elariel"
    assert members[0].cls == "Priest"
    assert members[0].hp_pct == 92


def test_parse_party_newline_delimited():
    raw = "Elariel:Priest:92\nShadowstep:Rogue:78"
    members = parse_party(raw)
    assert len(members) == 2
    assert members[1].name == "Shadowstep"


def test_parse_party_handles_empty():
    assert parse_party("") == []


def test_parse_party_skips_malformed_records():
    raw = "Good:Class:50|justname|||OtherGood:Class:75"
    members = parse_party(raw)
    assert len(members) == 2
    assert members[0].name == "Good"
    assert members[1].name == "OtherGood"


def test_party_member_dead_when_hp_zero():
    m = PartyMember(name="Fallen", hp_pct=0)
    assert not m.is_alive


# ---------------------------------------------------------------------------
# CombatContext rendering
# ---------------------------------------------------------------------------

def test_combat_context_empty_renders_nothing():
    assert CombatContext().to_prompt_section() == ""


def test_combat_context_renders_party_and_attackers():
    ctx = CombatContext(
        party_members=[
            PartyMember(name="Elariel", cls="Priest", hp_pct=92),
            PartyMember(name="Shadowstep", cls="Rogue", hp_pct=0),
        ],
        attacker_count=4,
        my_attacker_count=2,
        balance_pct=60,
    )
    section = ctx.to_prompt_section()
    assert "[COMBAT SITUATION]" in section
    assert "Elariel (Priest)" in section
    assert "DEAD" in section  # Shadowstep
    assert "Enemies in combat: 4" in section
    assert "Enemies targeting me: 2" in section
    assert "60%" in section


def test_combat_context_is_raid_when_more_than_5_members():
    big = CombatContext(
        party_members=[PartyMember(name=f"P{i}", hp_pct=100) for i in range(10)]
    )
    assert big.is_raid is True
    assert "raid" in big.to_prompt_section().lower()


# ---------------------------------------------------------------------------
# prompt_builder integration
# ---------------------------------------------------------------------------

def _snap(**overrides):
    s = BotSnapshot(guid=1)
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_build_context_renders_target_hp():
    snap = _snap(target_name="Lich King", target_hp_pct=45, state="combat")
    msg = build_context_message(snap, [], [], "Combat started", None)
    assert "Lich King (45% HP)" in msg


def test_build_context_renders_last_action():
    snap = _snap(last_action="Cast Greater Heal")
    msg = build_context_message(snap, [], [], "tick", None)
    assert "Last action: Cast Greater Heal" in msg


def test_build_context_target_hp_unset_renders_cleanly():
    snap = _snap(target_name="Some mob")
    msg = build_context_message(snap, [], [], "tick", None)
    assert "Target: Some mob" in msg
    assert "% HP" not in msg


def test_build_context_renders_combat_section_when_provided():
    snap = _snap(state="combat")
    ctx = CombatContext(attacker_count=2, my_attacker_count=1)
    msg = build_context_message(snap, [], [], "Combat started", ctx)
    assert "[COMBAT SITUATION]" in msg


def test_build_context_omits_combat_section_when_none():
    snap = _snap()
    msg = build_context_message(snap, [], [], "tick", None)
    assert "[COMBAT SITUATION]" not in msg


# ---------------------------------------------------------------------------
# Raid tools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_focus_target_sends_party_chat_and_strategy():
    from bot_agents.tools.raid_tools import create_raid_tools

    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_raid_tools(executor)
    focus = next(t for t in tools if t.tool_name == "focus_target")

    await focus({"bot_guid": 42, "target_name": "Adds"})

    assert executor.execute.await_count == 2
    calls = executor.execute.await_args_list
    # First call is party chat
    cmd0 = calls[0].args[0]
    assert cmd0.command_type.value == "party"
    assert "Adds" in cmd0.payload["message"]
    # Second is strategy add
    cmd1 = calls[1].args[0]
    assert cmd1.command_type.value == "set_strategy"
    assert cmd1.payload["strategy"] == "+dps assist"


@pytest.mark.asyncio
async def test_request_heal_picks_message_by_urgency():
    from bot_agents.tools.raid_tools import create_raid_tools

    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_raid_tools(executor)
    request_heal = next(t for t in tools if t.tool_name == "request_heal")

    await request_heal({"bot_guid": 1, "urgency": "critical"})
    msg = executor.execute.await_args.args[0].payload["message"]
    assert "HEALS NOW" in msg


@pytest.mark.asyncio
async def test_assist_player_uses_execute_action():
    from bot_agents.tools.raid_tools import create_raid_tools

    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_raid_tools(executor)
    assist = next(t for t in tools if t.tool_name == "assist_player")

    await assist({"bot_guid": 1, "player_name": "Tankington"})
    cmd = executor.execute.await_args.args[0]
    assert cmd.command_type.value == "execute_action"
    assert cmd.payload["action"] == "assist Tankington"


@pytest.mark.asyncio
async def test_mark_target_sends_action_and_chat():
    from bot_agents.tools.raid_tools import create_raid_tools

    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_raid_tools(executor)
    mark = next(t for t in tools if t.tool_name == "mark_target")

    await mark({"bot_guid": 1, "target_name": "Caster", "marker": "skull"})
    assert executor.execute.await_count == 2
    action_cmd = executor.execute.await_args_list[0].args[0]
    assert action_cmd.payload["action"] == "mark skull Caster"


# ---------------------------------------------------------------------------
# BotAgent.maybe_emit_idle
# ---------------------------------------------------------------------------

def _make_bot_agent():
    """Construct a BotAgent with minimal mocks — no LLM plumbing needed
    to exercise maybe_emit_idle."""
    import bot_agents.bot_agent as ba
    from bot_agents.bot_agent import BotAgent
    from core.config import settings

    profile = MagicMock()
    profile.guid = 42
    profile.name = "Testbot"
    profile.personality = "base"
    # Idle-tick emission is gated on a global kill switch and a
    # per-personality opt-in; force both on so these tests exercise
    # the counter logic rather than the gate.
    settings.proactive_enabled = True
    ba.load_profile = lambda name: {"proactive_enabled": True}  # noqa: E731
    with patch("bot_agents.bot_agent.build_system_prompt", return_value=""):
        return BotAgent(
            profile=profile,
            memory_manager=MagicMock(),
            cost_controller=MagicMock(),
            provider=MagicMock(),
        )


def test_maybe_emit_idle_returns_none_for_first_nine_calls():
    agent = _make_bot_agent()
    for _ in range(9):
        assert agent.maybe_emit_idle(30.0) is None


def test_maybe_emit_idle_emits_on_tenth_call():
    agent = _make_bot_agent()
    for _ in range(9):
        agent.maybe_emit_idle(30.0)
    event = agent.maybe_emit_idle(30.0)
    assert event is not None
    assert event.bot_guid == 42
    assert event.idle_seconds == 30.0


def test_maybe_emit_idle_resets_counter_after_emission():
    """After emitting one idle tick, the counter resets — the next
    emission should require 10 more calls."""
    agent = _make_bot_agent()
    for _ in range(10):
        agent.maybe_emit_idle(30.0)
    # Counter was reset — next 9 calls should return None
    for _ in range(9):
        assert agent.maybe_emit_idle(30.0) is None
    assert agent.maybe_emit_idle(30.0) is not None


@pytest.mark.asyncio
async def test_call_out_mechanic_truncates_long_messages():
    """Final payload including the [!] prefix must fit within the
    _MAX_CHAT_LEN contract (100 chars)."""
    from bot_agents.tools.raid_tools import _MAX_CHAT_LEN, create_raid_tools

    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_raid_tools(executor)
    callout = next(t for t in tools if t.tool_name == "call_out_mechanic")

    long_msg = "x" * 500
    await callout({"bot_guid": 1, "message": long_msg})
    msg = executor.execute.await_args.args[0].payload["message"]
    assert msg.startswith("[!] ")
    assert len(msg) <= _MAX_CHAT_LEN
