"""Milestone 6: Observability dashboard tests.

Run:
    cd llm-bots/middleware
    python -m pytest tests/test_m6_dashboard.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub heavy deps that aren't relevant to these tests so collection works
# even in a minimal dev env without sentence-transformers / qdrant-client.
import types
for _mod in ("sentence_transformers", "qdrant_client", "qdrant_client.models"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
# Provide attribute shims used at import time
sys.modules["sentence_transformers"].SentenceTransformer = object  # type: ignore[attr-defined]
_qc_models = sys.modules["qdrant_client.models"]
for _name in ("Distance", "FieldCondition", "Filter", "MatchValue",
              "PointStruct", "VectorParams"):
    setattr(_qc_models, _name, object)
sys.modules["qdrant_client"].QdrantClient = object  # type: ignore[attr-defined]

from core.bot_registry import BotRegistry
from core.event_bus import EventBus
from core.trace_store import TraceStore
from game.events import AdminForceSayEvent, EventType
from scheduler.cost_controller import CostController

# Imported AFTER stubs so the heavy deps don't break import
from bot_agents.bot_agent import AgentTrace  # noqa: E402


# ---------------------------------------------------------------------------
# TraceStore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_store_roundtrip():
    """Insert a trace and read it back."""
    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(path=Path(tmp) / "t.db")
        await store.insert(
            bot_guid=42, bot_name="Thaldrin", event_type="chat_received",
            model="claude-haiku-4-5", tokens_in=100, tokens_out=50,
            cost_usd=0.0012, latency_ms=850.0,
            tool_calls=["say", "remember_this"], preview="Aye.",
        )
        rows = await store.recent(limit=10)
        assert len(rows) == 1
        r = rows[0]
        assert r.bot_guid == 42
        assert r.tool_calls == ["say", "remember_this"]
        assert r.cost_usd == pytest.approx(0.0012)


@pytest.mark.asyncio
async def test_trace_store_filter_by_bot():
    """recent(bot_guid=...) filters correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        store = TraceStore(path=Path(tmp) / "t.db")
        for guid in (1, 2, 1, 3):
            await store.insert(
                bot_guid=guid, bot_name=f"b{guid}", event_type="idle_tick",
                model="m", tokens_in=0, tokens_out=0, cost_usd=0.0,
                latency_ms=0.0, tool_calls=[], preview="",
            )
        rows = await store.recent(bot_guid=1, limit=10)
        assert len(rows) == 2
        assert all(r.bot_guid == 1 for r in rows)


# ---------------------------------------------------------------------------
# CostController additions
# ---------------------------------------------------------------------------


def test_cost_controller_set_limit():
    c = CostController()
    c.set_hourly_limit(2.5)
    assert c.hourly_limit == 2.5
    metrics = c.get_metrics()
    assert metrics["hourly_limit_usd"] == 2.5


def test_cost_controller_per_model_distribution():
    c = CostController()
    c.record_usage("claude-haiku-4-5-20251001", 1000, 500)
    c.record_usage("claude-haiku-4-5-20251001", 1000, 500)
    c.record_usage("claude-sonnet-4-5-20241022", 1000, 500)
    dist = c.get_metrics()["model_distribution"]
    assert dist["claude-haiku-4-5-20251001"] == pytest.approx(2 / 3)
    assert dist["claude-sonnet-4-5-20241022"] == pytest.approx(1 / 3)


def test_cost_controller_returns_cost():
    c = CostController()
    cost = c.record_usage("claude-haiku-4-5-20251001", 1_000_000, 0)
    assert cost == pytest.approx(0.80)  # $0.80 per 1M input tokens


def test_cost_controller_hourly_calls_and_avg_latency():
    c = CostController()
    c.record_usage("claude-haiku-4-5-20251001", 100, 50)
    c.record_usage("claude-haiku-4-5-20251001", 100, 50)
    c.record_latency(800.0)
    c.record_latency(1200.0)
    m = c.get_metrics()
    assert m["calls_this_hour"] == 2
    assert m["avg_latency_ms"] == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# Supervisor trace broadcast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_trace_broadcast_fanout():
    """Publishing a trace reaches every subscriber queue."""
    from bot_agents.agent_supervisor import AgentSupervisor

    sup = AgentSupervisor(
        game_client=MagicMock(),
        registry=BotRegistry(),
        event_bus=EventBus(),
        memory_manager=MagicMock(),
        cost_controller=CostController(),
        provider=MagicMock(),
    )
    q1 = sup.subscribe_traces()
    q2 = sup.subscribe_traces()

    trace = AgentTrace(
        bot_guid=1, bot_name="x", event_type="chat_received", model="m"
    )
    sup._broadcast_trace(trace)

    assert q1.qsize() == 1 and q2.qsize() == 1
    assert (await q1.get()).bot_guid == 1
    assert (await q2.get()).bot_guid == 1

    sup.unsubscribe_traces(q1)
    sup._broadcast_trace(trace)
    assert q1.qsize() == 0
    assert q2.qsize() == 1


@pytest.mark.asyncio
async def test_supervisor_drops_oldest_when_subscriber_full():
    """Slow consumers do not block the supervisor."""
    from bot_agents.agent_supervisor import AgentSupervisor

    sup = AgentSupervisor(
        game_client=MagicMock(),
        registry=BotRegistry(),
        event_bus=EventBus(),
        memory_manager=MagicMock(),
        cost_controller=CostController(),
        provider=MagicMock(),
    )
    q = sup.subscribe_traces(maxsize=2)
    t1 = AgentTrace(bot_guid=1, bot_name="a", event_type="e", model="m")
    t2 = AgentTrace(bot_guid=2, bot_name="b", event_type="e", model="m")
    t3 = AgentTrace(bot_guid=3, bot_name="c", event_type="e", model="m")
    sup._broadcast_trace(t1)
    sup._broadcast_trace(t2)
    sup._broadcast_trace(t3)  # should drop t1, keep t2+t3

    got = [await q.get(), await q.get()]
    assert [t.bot_guid for t in got] == [2, 3]


# ---------------------------------------------------------------------------
# Admin force-say event
# ---------------------------------------------------------------------------


def test_admin_force_say_event_type():
    e = AdminForceSayEvent(bot_guid=1, bot_name="n", text="hello")
    assert e.event_type == EventType.ADMIN_FORCE_SAY
    assert e.text == "hello"


# ---------------------------------------------------------------------------
# BotProfile new fields
# ---------------------------------------------------------------------------


def test_bot_profile_has_cost_and_last_action():
    reg = BotRegistry()
    reg.elevate(99, "Ziggy")
    p = reg.get(99)
    assert p.total_cost_usd == 0.0
    assert p.last_llm_action == ""


# ---------------------------------------------------------------------------
# BotAgent.reload_system_prompt rebuilds the cached string
# ---------------------------------------------------------------------------


def test_reload_system_prompt_picks_up_new_personality():
    from unittest.mock import patch

    from bot_agents.bot_agent import BotAgent
    from core.bot_registry import BotProfile

    profile = BotProfile(guid=7, name="Aerin", personality="default")
    with patch("bot_agents.bot_agent.build_system_prompt") as m:
        m.return_value = "PROMPT[default]"
        agent = BotAgent(
            profile=profile,
            memory_manager=MagicMock(),
            cost_controller=CostController(),
            provider=MagicMock(),
        )
        assert "PROMPT[default]" in agent._system_prompt  # noqa: SLF001
        profile.personality = "gruff_warrior"
        m.return_value = "PROMPT[gruff_warrior]"
        agent.reload_system_prompt()
        assert "PROMPT[gruff_warrior]" in agent._system_prompt  # noqa: SLF001


# ---------------------------------------------------------------------------
# Dashboard import smoke test (must not raise)
# ---------------------------------------------------------------------------


def test_dashboard_app_imports():
    from dashboard import app as dash_app
    from dashboard import routes  # noqa: F401
    assert dash_app.app is not None
    # Routes registered
    paths = {r.path for r in dash_app.app.routes}
    assert "/" in paths
    assert "/api/roster" in paths
    assert "/api/traces/stream" in paths
    assert "/memories" in paths
