"""Milestone 4: RPG / quest / trade / proactive / mana tests.

Run with::

    cd llm-bots/middleware
    python -m pytest tests/test_m4_rpg_quest_trade.py -v

Coverage:
  - New CommandTypes wire to correct mod-playerbots chat commands
    (drop, b/s vendor, rpg mode, go x;y;z / go travel)
  - Quest / trade / rpg tool factories build the right BotCommand
  - Quest accept / share / drop writes a QUEST_OUTCOME memory when a
    MemoryManager + registry are supplied
  - Proactive idle emit respects the global kill-switch AND the
    per-personality opt-in flag
  - state_differ emits MANA_CRITICAL on threshold crossing and
    ignores mana-less classes (mana_pct is None)
  - POLICY_REGISTRY covers MANA_CRITICAL
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub heavy optional deps so tests run without sentence_transformers /
# qdrant installed. bot_agent → memory_manager → qdrant_store imports
# these at module load; we never exercise them in this test file.
for mod in ("sentence_transformers", "qdrant_client", "qdrant_client.models"):
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)
sys.modules["sentence_transformers"].SentenceTransformer = object  # type: ignore
_qc_models = sys.modules["qdrant_client.models"]
for _name in ("Distance", "FieldCondition", "Filter", "MatchValue",
              "PointStruct", "VectorParams"):
    setattr(_qc_models, _name, object)
sys.modules["qdrant_client"].QdrantClient = object  # type: ignore

from bot_agents.tools.quest_tools import create_quest_tools
from bot_agents.tools.rpg_tools import create_rpg_tools
from bot_agents.tools.trade_tools import create_trade_tools
from core.command_executor import CommandExecutor
from core.game_client import BotSnapshot
from game.commands import BotCommand, CommandType
from game.event_policy import POLICY_REGISTRY, get_policy
from game.events import EventType, ManaCriticalEvent
from game.state_differ import diff


# ---------------------------------------------------------------------------
# Command executor: new / fixed wire formats
# ---------------------------------------------------------------------------

def _executor():
    game = MagicMock()
    game.send_command = AsyncMock(return_value="")
    return CommandExecutor(game, MagicMock()), game


@pytest.mark.asyncio
async def test_drop_quest_sends_drop_title():
    ex, game = _executor()
    await ex.execute(
        BotCommand(
            command_type=CommandType.DROP_QUEST,
            bot_guid=1,
            payload={"quest_link": "The Legend of Stalvan"},
        )
    )
    _, sent = game.send_command.call_args.args
    assert sent == "drop The Legend of Stalvan"


@pytest.mark.asyncio
async def test_vendor_buy_defaults_to_vendor_filter():
    ex, game = _executor()
    await ex.execute(
        BotCommand(command_type=CommandType.VENDOR_BUY, bot_guid=1, payload={})
    )
    _, sent = game.send_command.call_args.args
    assert sent == "b vendor"


@pytest.mark.asyncio
async def test_vendor_buy_uses_item_link():
    ex, game = _executor()
    await ex.execute(
        BotCommand(
            command_type=CommandType.VENDOR_BUY,
            bot_guid=1,
            payload={"item_link": "item:1234"},
        )
    )
    _, sent = game.send_command.call_args.args
    assert sent == "b item:1234"


@pytest.mark.asyncio
async def test_set_rpg_mode_sends_rpg_mode_command():
    ex, game = _executor()
    await ex.execute(
        BotCommand(
            command_type=CommandType.SET_RPG_MODE,
            bot_guid=1,
            payload={"mode": "rest"},
        )
    )
    _, sent = game.send_command.call_args.args
    assert sent == "rpg mode rest"


@pytest.mark.asyncio
async def test_go_to_coords_uses_semicolons():
    ex, game = _executor()
    await ex.execute(
        BotCommand(
            command_type=CommandType.GO_TO,
            bot_guid=1,
            payload={"x": -8834.5, "y": 625.2, "z": 94.1},
        )
    )
    _, sent = game.send_command.call_args.args
    assert sent == "go -8834.5;625.2;94.1"


@pytest.mark.asyncio
async def test_go_to_destination_passthrough():
    ex, game = _executor()
    await ex.execute(
        BotCommand(
            command_type=CommandType.GO_TO,
            bot_guid=1,
            payload={"destination": "travel Darkshire"},
        )
    )
    _, sent = game.send_command.call_args.args
    assert sent == "go travel Darkshire"


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drop_quest_tool_emits_drop_command():
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_quest_tools(executor)
    drop = next(t for t in tools if t.tool_name == "drop_quest")
    await drop({"bot_guid": 7, "quest_link_or_title": "Wolves Across the Border"})
    cmd = executor.execute.call_args.args[0]
    assert cmd.command_type == CommandType.DROP_QUEST
    assert cmd.payload["quest_link"] == "Wolves Across the Border"


@pytest.mark.asyncio
async def test_list_quests_tool_defaults_to_all():
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_quest_tools(executor)
    lst = next(t for t in tools if t.tool_name == "list_quests")
    await lst({"bot_guid": 7})
    cmd = executor.execute.call_args.args[0]
    assert cmd.command_type == CommandType.EXECUTE_ACTION
    assert cmd.payload["action"] == "quests"


@pytest.mark.asyncio
async def test_list_quests_tool_filter_completed():
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_quest_tools(executor)
    lst = next(t for t in tools if t.tool_name == "list_quests")
    await lst({"bot_guid": 7, "filter": "completed"})
    cmd = executor.execute.call_args.args[0]
    assert cmd.payload["action"] == "quests completed"


@pytest.mark.asyncio
async def test_accept_quest_writes_memory_when_registry_and_memory_provided():
    executor = MagicMock()
    executor.execute = AsyncMock()
    memory = MagicMock()
    memory.store_explicit = AsyncMock()

    registry = MagicMock()
    profile = MagicMock()
    profile.name = "Zerik"
    registry.get = MagicMock(return_value=profile)

    tools = create_quest_tools(executor, memory=memory, registry=registry)
    accept = next(t for t in tools if t.tool_name == "accept_quest")
    await accept({"bot_guid": 7, "quest_link": "quest:123"})

    cmd = executor.execute.call_args.args[0]
    assert cmd.command_type == CommandType.ACCEPT_QUEST
    assert cmd.payload["quest_link"] == "quest:123"

    memory.store_explicit.assert_awaited_once()
    kwargs = memory.store_explicit.await_args.kwargs
    assert kwargs["bot_guid"] == 7
    assert kwargs["bot_name"] == "Zerik"
    assert "quest:123" in kwargs["content"]
    assert kwargs["importance"] >= 0.8


@pytest.mark.asyncio
async def test_accept_quest_no_memory_without_services():
    """Memory must be opt-in; tool works standalone."""
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_quest_tools(executor)
    accept = next(t for t in tools if t.tool_name == "accept_quest")
    # Must not raise even though no memory/registry was passed.
    await accept({"bot_guid": 7, "quest_link": "quest:123"})
    executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_buy_from_vendor_tool_default():
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_trade_tools(executor)
    buy = next(t for t in tools if t.tool_name == "buy_from_vendor")
    await buy({"bot_guid": 1})
    cmd = executor.execute.call_args.args[0]
    assert cmd.command_type == CommandType.VENDOR_BUY
    assert cmd.payload == {}


@pytest.mark.asyncio
async def test_sell_to_vendor_tool_gray_default():
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_trade_tools(executor)
    sell = next(t for t in tools if t.tool_name == "sell_to_vendor")
    await sell({"bot_guid": 1})
    cmd = executor.execute.call_args.args[0]
    assert cmd.command_type == CommandType.VENDOR_SELL
    assert cmd.payload["filter"] == "gray"


@pytest.mark.asyncio
async def test_set_rpg_mode_tool():
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_rpg_tools(executor)
    set_mode = next(t for t in tools if t.tool_name == "set_rpg_mode")
    await set_mode({"bot_guid": 1, "mode": "explore"})
    cmd = executor.execute.call_args.args[0]
    assert cmd.command_type == CommandType.SET_RPG_MODE
    assert cmd.payload["mode"] == "explore"


@pytest.mark.asyncio
async def test_go_to_location_tool_parses_coords():
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_rpg_tools(executor)
    go = next(t for t in tools if t.tool_name == "go_to_location")
    await go({"bot_guid": 1, "destination": "-8834.5 625.2 94.1"})
    cmd = executor.execute.call_args.args[0]
    assert cmd.payload["x"] == pytest.approx(-8834.5)
    assert cmd.payload["y"] == pytest.approx(625.2)
    assert cmd.payload["z"] == pytest.approx(94.1)


@pytest.mark.asyncio
async def test_go_to_location_tool_passes_named_destination():
    executor = MagicMock()
    executor.execute = AsyncMock()
    tools = create_rpg_tools(executor)
    go = next(t for t in tools if t.tool_name == "go_to_location")
    await go({"bot_guid": 1, "destination": "travel Stormwind"})
    cmd = executor.execute.call_args.args[0]
    assert cmd.payload == {"destination": "travel Stormwind"}


# ---------------------------------------------------------------------------
# Proactive idle gate
# ---------------------------------------------------------------------------

def _make_agent(personality: str = "base"):
    """Build a minimal BotAgent bypassing external services."""
    from bot_agents.bot_agent import BotAgent
    from core.bot_registry import BotProfile

    profile = BotProfile(guid=1, name="Test", personality=personality)
    agent = object.__new__(BotAgent)
    agent._profile = profile
    agent._idle_counter = 0
    return agent


def test_proactive_disabled_globally_returns_none(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "proactive_enabled", False)
    agent = _make_agent()
    # Even after many ticks, the kill switch wins.
    for _ in range(30):
        assert agent.maybe_emit_idle(3.0) is None


def test_proactive_requires_personality_opt_in(monkeypatch):
    from core.config import settings
    from personality import loader

    monkeypatch.setattr(settings, "proactive_enabled", True)
    monkeypatch.setattr(settings, "proactive_idle_ticks", 2)
    # Pretend the loaded profile does NOT opt in.
    monkeypatch.setattr(
        loader, "load_profile", lambda name: {"proactive_enabled": False}
    )
    # Patch the symbol in the module under test (already imported there).
    import bot_agents.bot_agent as ba
    monkeypatch.setattr(ba, "load_profile", lambda name: {"proactive_enabled": False})

    agent = _make_agent()
    for _ in range(10):
        assert agent.maybe_emit_idle(3.0) is None


def test_proactive_fires_after_n_ticks_when_both_opted_in(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "proactive_enabled", True)
    monkeypatch.setattr(settings, "proactive_idle_ticks", 3)
    import bot_agents.bot_agent as ba
    monkeypatch.setattr(ba, "load_profile", lambda name: {"proactive_enabled": True})

    agent = _make_agent()
    assert agent.maybe_emit_idle(3.0) is None
    assert agent.maybe_emit_idle(3.0) is None
    idle = agent.maybe_emit_idle(3.0)
    assert idle is not None
    assert idle.event_type == EventType.IDLE_TICK
    # Counter resets after emit
    assert agent.maybe_emit_idle(3.0) is None


# ---------------------------------------------------------------------------
# MANA_CRITICAL event
# ---------------------------------------------------------------------------

def test_mana_critical_policy_registered():
    assert EventType.MANA_CRITICAL in POLICY_REGISTRY
    p = get_policy(EventType.MANA_CRITICAL)
    assert p.invoke_llm is True
    assert p.model_tier == "important"
    assert p.needs_combat_context is True
    assert p.cooldown_seconds > 0


def test_state_differ_emits_mana_critical_on_crossing():
    old = BotSnapshot(guid=1, state="combat", mana_pct=50, hp_pct=100)
    new = BotSnapshot(guid=1, state="combat", mana_pct=15, hp_pct=100)
    events = diff(old, new, bot_name="Zerik")
    mana_events = [e for e in events if isinstance(e, ManaCriticalEvent)]
    assert len(mana_events) == 1
    assert mana_events[0].mana_pct == 15


def test_state_differ_ignores_mana_less_classes():
    """Warriors / rogues / DKs have mana_pct=None — never fire the event."""
    old = BotSnapshot(guid=1, mana_pct=None)
    new = BotSnapshot(guid=1, mana_pct=None)
    events = diff(old, new)
    assert not any(isinstance(e, ManaCriticalEvent) for e in events)


def test_state_differ_only_fires_on_crossing_not_while_below():
    old = BotSnapshot(guid=1, mana_pct=10, hp_pct=100)
    new = BotSnapshot(guid=1, mana_pct=8, hp_pct=100)
    events = diff(old, new)
    assert not any(isinstance(e, ManaCriticalEvent) for e in events)
