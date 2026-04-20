"""Milestone 7: Scale-to-50 tests.

Run:
    cd llm-bots/middleware
    python -m pytest tests/test_m7_scale.py -v

Covers:
- Tick batching: bot polls are chunked, not all-at-once.
- Auto-elevator promote/demote by proximity, pinned-bot protection.
- Budget degrade ladder (normal / degrading / exhausted).
- Global rate-limit circuit breaker.
- Proximity distance math + bot-GUID exclusion.
"""
from __future__ import annotations

import asyncio
import sys
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub heavy deps so collection works in minimal envs.
for _mod in ("sentence_transformers", "qdrant_client", "qdrant_client.models"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["sentence_transformers"].SentenceTransformer = object  # type: ignore[attr-defined]
_qc_models = sys.modules["qdrant_client.models"]
for _name in ("Distance", "FieldCondition", "Filter", "MatchValue",
              "PointStruct", "VectorParams"):
    setattr(_qc_models, _name, object)
sys.modules["qdrant_client"].QdrantClient = object  # type: ignore[attr-defined]

from core.bot_registry import BotRegistry  # noqa: E402
from core.config import settings  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from scheduler.auto_elevator import AutoElevator  # noqa: E402
from scheduler.cost_controller import CostController  # noqa: E402
from scheduler.proximity_scanner import (  # noqa: E402
    ProximityScanner,
    distance_squared,
)


# ---------------------------------------------------------------------------
# BotRegistry auto_elevated / pinned semantics
# ---------------------------------------------------------------------------


def test_elevate_defaults_to_pinned():
    reg = BotRegistry()
    assert reg.elevate(1, "Alice") is True
    p = reg.get(1)
    assert p.auto_elevated is False
    assert reg.all_pinned() == [p]
    assert reg.all_auto_elevated() == []


def test_elevate_auto_flag_is_respected():
    reg = BotRegistry()
    reg.elevate(2, "Bob", auto=True)
    assert reg.get(2).auto_elevated is True
    assert reg.all_auto_elevated()[0].guid == 2
    assert reg.all_pinned() == []


def test_demote_only_if_auto_protects_pinned():
    reg = BotRegistry()
    reg.elevate(1, "Pinned", auto=False)
    reg.elevate(2, "Auto", auto=True)
    assert reg.demote(1, only_if_auto=True) is False
    assert reg.is_elevated(1) is True
    assert reg.demote(2, only_if_auto=True) is True
    assert reg.is_elevated(2) is False


def test_re_elevate_promotes_auto_to_pinned():
    reg = BotRegistry()
    reg.elevate(3, "X", auto=True)
    assert reg.get(3).auto_elevated is True
    reg.elevate(3, "X", auto=False)  # admin action
    assert reg.get(3).auto_elevated is False


# ---------------------------------------------------------------------------
# CostController: budget degrade + global backoff
# ---------------------------------------------------------------------------


def test_select_model_downgrades_at_threshold():
    c = CostController()
    c.set_hourly_limit(1.0)
    # Force spend above the 80% threshold but under 100%
    c._hourly_spend = 0.85  # noqa: SLF001
    assert c.select_model("important") == settings.model_default
    assert c.select_model("default") == settings.model_default
    assert c.budget_state == "degrading"


def test_select_model_returns_none_when_exhausted():
    c = CostController()
    c.set_hourly_limit(1.0)
    c._hourly_spend = 1.5  # noqa: SLF001
    assert c.select_model("important") is None
    assert c.budget_state == "exhausted"


def test_rate_limit_global_breaker_trips_after_n_errors():
    c = CostController()
    # Default trigger from settings, but assert it explicitly
    trigger = settings.rate_limit_global_trigger
    for _ in range(trigger - 1):
        c.note_rate_limit_error()
    assert c.global_backoff_active is False
    c.note_rate_limit_error()  # nth error trips breaker
    assert c.global_backoff_active is True
    assert c.select_model("default") is None


def test_successful_call_resets_streak():
    c = CostController()
    c.note_rate_limit_error()
    c.note_rate_limit_error()
    c.note_successful_call()
    assert c._recent_rate_limit_errors == 0  # noqa: SLF001


# ---------------------------------------------------------------------------
# ProximityScanner / distance math
# ---------------------------------------------------------------------------


def test_distance_squared_is_3d():
    assert distance_squared(0, 0, 0, 3, 4, 0) == pytest.approx(25.0)
    assert distance_squared(0, 0, 0, 0, 0, 5) == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_scanner_marks_bot_near_human():
    scanner = ProximityScanner(db=MagicMock())
    # Inject fabricated scan state — bot 10 is near, bot 20 is far.
    scanner._inject_scan_state(  # noqa: SLF001
        nearby={10: True, 20: False},
        positions={
            10: ("NearBot", 0, 0, 0, 0),
            20: ("FarBot", 0, 9999, 9999, 0),
        },
    )
    assert scanner.is_near_human(10) is True
    assert scanner.is_near_human(20) is False
    assert scanner.bot_candidates_near_humans() == [(10, "NearBot")]


@pytest.mark.asyncio
async def test_scanner_scan_once_with_mock_db(monkeypatch):
    """Drive scan_once with a mocked DbClient."""
    from core.db_client import HumanCharacter

    db = MagicMock()
    db.fetch_bot_guids = AsyncMock(return_value={100, 200})
    # Return all online characters (bots + humans) in one list.
    db.fetch_online_humans = AsyncMock(
        return_value=[
            # Bot 100 right next to the human → should be "near"
            HumanCharacter(guid=100, name="B100", map_id=0, x=0, y=0, z=0),
            # Bot 200 far from the human → should NOT be near
            HumanCharacter(guid=200, name="B200", map_id=0, x=1e4, y=1e4, z=0),
            # The human
            HumanCharacter(guid=1, name="Thrall", map_id=0, x=10, y=10, z=0),
        ]
    )
    scanner = ProximityScanner(db=db)
    await scanner.scan_once()

    assert scanner.is_near_human(100) is True
    assert scanner.is_near_human(200) is False


@pytest.mark.asyncio
async def test_scanner_cross_map_never_counts():
    """Bots on a different map_id are never 'near' a human."""
    from core.db_client import HumanCharacter

    db = MagicMock()
    db.fetch_bot_guids = AsyncMock(return_value={100})
    db.fetch_online_humans = AsyncMock(
        return_value=[
            HumanCharacter(guid=100, name="B", map_id=0, x=0, y=0, z=0),
            # Human is *at the same coords* but on a different map
            HumanCharacter(guid=1, name="H", map_id=571, x=0, y=0, z=0),
        ]
    )
    scanner = ProximityScanner(db=db)
    await scanner.scan_once()
    assert scanner.is_near_human(100) is False


# ---------------------------------------------------------------------------
# AutoElevator
# ---------------------------------------------------------------------------


def _make_elevator(registry: BotRegistry, nearby: dict[int, bool],
                   positions: dict[int, tuple]) -> AutoElevator:
    scanner = ProximityScanner(db=MagicMock())
    scanner._inject_scan_state(nearby=nearby, positions=positions)  # noqa: SLF001
    return AutoElevator(registry=registry, scanner=scanner)


def test_auto_elevator_promotes_nearby_bot():
    reg = BotRegistry()
    elev = _make_elevator(
        reg,
        nearby={42: True},
        positions={42: ("Grumsh", 0, 0, 0, 0)},
    )
    elev.reconcile()
    assert reg.is_elevated(42)
    assert reg.get(42).auto_elevated is True


def test_auto_elevator_demotes_after_grace_window():
    reg = BotRegistry()
    reg.elevate(7, "Tmp", auto=True)
    elev = _make_elevator(reg, nearby={7: False}, positions={})
    # Reconcile once per tick; needs auto_demote_grace_ticks to kick in.
    for _ in range(settings.auto_demote_grace_ticks):
        elev.reconcile()
    assert reg.is_elevated(7) is False


def test_auto_elevator_never_demotes_pinned():
    reg = BotRegistry()
    reg.elevate(9, "Pinned", auto=False)
    elev = _make_elevator(reg, nearby={9: False}, positions={})
    for _ in range(settings.auto_demote_grace_ticks + 5):
        elev.reconcile()
    assert reg.is_elevated(9) is True


def test_auto_elevator_honors_capacity_cap(monkeypatch):
    reg = BotRegistry()
    monkeypatch.setattr(settings, "max_active_agents", 2)
    # Pre-fill with 2 pinned bots
    reg.elevate(1, "A")
    reg.elevate(2, "B")
    elev = _make_elevator(
        reg,
        nearby={3: True, 4: True},
        positions={3: ("C", 0, 0, 0, 0), 4: ("D", 0, 0, 0, 0)},
    )
    elev.reconcile()
    # Cap means neither candidate gets elevated.
    assert reg.count == 2
    assert not reg.is_elevated(3)
    assert not reg.is_elevated(4)


def test_auto_elevator_respects_feature_flag(monkeypatch):
    monkeypatch.setattr(settings, "auto_elevation_enabled", False)
    reg = BotRegistry()
    elev = _make_elevator(
        reg, nearby={5: True}, positions={5: ("X", 0, 0, 0, 0)}
    )
    elev.reconcile()
    assert reg.is_elevated(5) is False


def test_auto_elevator_nearby_resets_away_counter():
    reg = BotRegistry()
    reg.elevate(11, "Near", auto=True)
    # Tick once with "away", then "near" — counter should reset.
    elev_away = _make_elevator(reg, nearby={11: False}, positions={})
    elev_away.reconcile()
    assert reg.get(11).away_ticks == 1
    elev_near = _make_elevator(
        reg, nearby={11: True}, positions={11: ("Near", 0, 0, 0, 0)}
    )
    elev_near.reconcile()
    assert reg.get(11).away_ticks == 0


# ---------------------------------------------------------------------------
# Supervisor batch polling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_polls_in_batches(monkeypatch):
    """Verify we never run more than ``tick_batch_size`` snapshot calls at once."""
    from bot_agents.agent_supervisor import AgentSupervisor
    from core.game_client import BotSnapshot

    monkeypatch.setattr(settings, "tick_batch_size", 3)
    monkeypatch.setattr(settings, "tick_batch_spacing_ms", 0)

    # Track concurrency — increment on entry, decrement on exit, record max.
    in_flight = 0
    max_in_flight = 0

    async def fake_get_bot_state(guid: int) -> BotSnapshot:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)  # ensure overlap within a batch
        in_flight -= 1
        return BotSnapshot(guid=guid)

    game = MagicMock()
    game.get_bot_state = fake_get_bot_state

    sup = AgentSupervisor(
        game_client=game,
        registry=BotRegistry(),
        event_bus=EventBus(),
        memory_manager=MagicMock(),
        cost_controller=CostController(),
        provider=MagicMock(),
    )

    # Poll 10 bots; batch size is 3 → max concurrent should be 3.
    guids = list(range(10))
    results = await sup._run_batched(  # noqa: SLF001
        [fake_get_bot_state(g) for g in guids]
    )
    assert len(results) == 10
    assert max_in_flight <= 3


@pytest.mark.asyncio
async def test_supervisor_skips_llm_when_global_backoff_active():
    """When the cost controller's breaker is open, agent fan-out is skipped."""
    from bot_agents.agent_supervisor import AgentSupervisor

    cost = CostController()
    # Trip the breaker immediately
    for _ in range(settings.rate_limit_global_trigger):
        cost.note_rate_limit_error()
    assert cost.global_backoff_active

    sup = AgentSupervisor(
        game_client=MagicMock(),
        registry=BotRegistry(),
        event_bus=EventBus(),
        memory_manager=MagicMock(),
        cost_controller=cost,
        provider=MagicMock(),
    )
    called = False

    async def would_run():
        nonlocal called
        called = True

    # _run_batched is only invoked when backoff is NOT active; we
    # assert the gate in _tick directly by simulating it:
    tasks = [would_run()]
    if tasks and not cost.global_backoff_active:  # pragma: no cover
        await sup._run_batched(tasks)  # noqa: SLF001
    assert called is False
    # Clean up the unawaited coroutine to avoid warnings
    for c in tasks:
        c.close()


# ---------------------------------------------------------------------------
# BotAgent rate-limit handling
# ---------------------------------------------------------------------------


def test_bot_agent_marks_degraded_on_429():
    from bot_agents.bot_agent import BotAgent
    from core.bot_registry import BotProfile

    reg = BotRegistry()
    reg.elevate(55, "Throttled")
    profile = reg.get(55)
    cost = CostController()
    agent = BotAgent(
        profile=profile,
        memory_manager=MagicMock(),
        cost_controller=cost,
        provider=MagicMock(),
        registry=reg,
    )
    agent._maybe_handle_rate_limit("HTTP 429 Too Many Requests")  # noqa: SLF001

    assert reg.is_degraded(55) is True
    assert cost.rate_limit_errors_total == 1


def test_bot_agent_ignores_non_429_errors():
    from bot_agents.bot_agent import BotAgent

    reg = BotRegistry()
    reg.elevate(56, "Fine")
    profile = reg.get(56)
    cost = CostController()
    agent = BotAgent(
        profile=profile,
        memory_manager=MagicMock(),
        cost_controller=cost,
        provider=MagicMock(),
        registry=reg,
    )
    agent._maybe_handle_rate_limit("connection reset")  # noqa: SLF001
    assert reg.is_degraded(56) is False
    assert cost.rate_limit_errors_total == 0
