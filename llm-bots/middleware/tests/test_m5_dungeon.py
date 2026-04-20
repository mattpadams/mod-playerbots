"""Milestone 5 (phase a2): dungeon coordination tests.

Run with::

    cd llm-bots/middleware
    python -m pytest tests/test_m5_dungeon.py -v

Coverage:
  - YAML loader: indexes by (map_id, difficulty, sub_zone); overlays merge
    heroic-only fields onto the base dungeon without adding phases.
  - Role resolution: explicit override > class/spec heuristic > dps default.
  - Coordinator: detects instance enter/exit, queues strategy add/set,
    stashes the pre-dungeon strategy, and restores it on exit.
  - Boss lookup by alias matches target names.
  - Prompt builder renders [DUNGEON MODE] only when a context is provided.
  - event_policy registers both new event types.
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
from dungeons.loader import DungeonRegistry
from dungeons.models import Boss, BossPhase, Difficulty, Dungeon, DungeonRole
from dungeons.role import infer_role
from game.commands import CommandType
from game.event_policy import POLICY_REGISTRY, get_policy
from game.events import DungeonEnteredEvent, DungeonExitedEvent, EventType
from personality.prompt_builder import build_context_message


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

def test_dungeon_events_registered():
    assert EventType.DUNGEON_ENTERED in POLICY_REGISTRY
    assert EventType.DUNGEON_EXITED in POLICY_REGISTRY


def test_dungeon_entered_invokes_llm_with_important_tier():
    p = get_policy(EventType.DUNGEON_ENTERED)
    assert p.invoke_llm is True
    assert p.model_tier == "important"


def test_dungeon_exited_recorded_only():
    assert get_policy(EventType.DUNGEON_EXITED).invoke_llm is False


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

def test_infer_role_uses_explicit_override():
    assert infer_role({"dungeon_role": "healer"}) is DungeonRole.HEALER


def test_infer_role_prot_warrior_is_tank():
    assert infer_role({"class": "warrior", "spec": "protection"}) is DungeonRole.TANK


def test_infer_role_holy_priest_is_healer():
    assert infer_role({"class": "priest", "spec": "holy"}) is DungeonRole.HEALER


def test_infer_role_default_dps():
    assert infer_role({"class": "mage", "spec": "fire"}) is DungeonRole.DPS


def test_infer_role_invalid_override_falls_back():
    # "bogus" is not a valid DungeonRole, so fall back to spec heuristic.
    assert (
        infer_role(
            {"dungeon_role": "bogus", "class": "paladin", "spec": "protection"}
        )
        is DungeonRole.TANK
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def sample_registry(tmp_path: Path) -> DungeonRegistry:
    base = tmp_path / "base.yaml"
    overlay = tmp_path / "base_heroic.yaml"
    _write_yaml(
        base,
        """
key: sample_keep
name: Sample Keep
map_id: 999
sub_zone: null
expansion: wotlk
difficulty: normal
overlay_of: null
strategy_key: wotlk-sk
cpp_coverage: full
min_level: 68
max_level: 72
leader_role: tank
general_notes: A test dungeon.
bosses:
  - name: Boss One
    order: 1
    aliases: [BossAlpha]
    phases:
      - name: Phase 1
        hp_threshold: null
        description: fight
        tank: Tank it still
        healer: Heal the tank
        dps: Burn it
        mechanics:
          - Do not stand in fire
""".lstrip(),
    )
    _write_yaml(
        overlay,
        """
key: sample_keep_heroic
name: Sample Keep (Heroic)
difficulty: heroic
overlay_of: sample_keep
min_level: 80
max_level: 80
general_notes: Heroic overlay notes.
bosses:
  - name: Boss One
    phases:
      - name: Phase 1
        mechanics:
          - Fire hits harder on heroic
""".lstrip(),
    )
    reg = DungeonRegistry()
    reg.load_dir(tmp_path)
    return reg


def test_loader_indexes_normal_and_heroic(sample_registry: DungeonRegistry):
    normal = sample_registry.lookup(999, Difficulty.NORMAL)
    heroic = sample_registry.lookup(999, Difficulty.HEROIC)
    assert normal is not None and normal.key == "sample_keep"
    assert heroic is not None and heroic.key == "sample_keep_heroic"


def test_overlay_merges_onto_base(sample_registry: DungeonRegistry):
    heroic = sample_registry.lookup(999, Difficulty.HEROIC)
    assert heroic is not None
    # Inherited from base:
    assert heroic.strategy_key == "wotlk-sk"
    assert heroic.leader_role == DungeonRole.TANK
    boss = heroic.bosses[0]
    # Base text preserved where overlay omits it:
    assert "Burn" in boss.phases[0].dps
    # Overlay text wins where present:
    assert any("heroic" in m for m in boss.phases[0].mechanics)


def test_loader_skips_orphan_overlay(tmp_path: Path):
    _write_yaml(
        tmp_path / "orphan_heroic.yaml",
        """
key: orphan_heroic
name: Orphan
difficulty: heroic
overlay_of: does_not_exist
""".lstrip(),
    )
    reg = DungeonRegistry()
    assert reg.load_dir(tmp_path) == 0


def test_real_dungeon_yaml_loads():
    """Smoke-test: the actual shipped YAMLs load without errors."""
    reg = DungeonRegistry()
    count = reg.load_dir()
    assert count > 0
    # Utgarde Keep is the canonical example used in the design doc.
    uk = reg.lookup(574, Difficulty.NORMAL)
    assert uk is not None
    assert uk.key == "utgarde_keep"
    assert uk.strategy_key == "wotlk-uk"


def test_real_multiwing_maps_resolve_by_sub_zone():
    """Dire Maul / SM / Stratholme / BRS wings all share a map_id."""
    reg = DungeonRegistry()
    reg.load_dir()
    # Dire Maul wings (map 429).
    assert reg.lookup(429, Difficulty.NORMAL, "Gordok Commons").key == "dire_maul_north"
    assert reg.lookup(429, Difficulty.NORMAL, "Capital Gardens").key == "dire_maul_west"
    assert (
        reg.lookup(429, Difficulty.NORMAL, "The Shrine of Eldretharr").key
        == "dire_maul_east"
    )
    # Scarlet Monastery wings (map 189).
    assert reg.lookup(189, Difficulty.NORMAL, "Cathedral").key == "scarlet_cathedral"
    assert reg.lookup(189, Difficulty.NORMAL, "Library").key == "scarlet_library"
    # Stratholme halves (map 329).
    assert (
        reg.lookup(329, Difficulty.NORMAL, "Crusader's Square").key
        == "stratholme_living"
    )
    assert reg.lookup(329, Difficulty.NORMAL, "The Gauntlet").key == "stratholme_undead"
    # Unknown sub_zone on a multi-wing map returns None (no default).
    assert reg.lookup(429, Difficulty.NORMAL, "Unknown Area") is None


# ---------------------------------------------------------------------------
# Boss lookup
# ---------------------------------------------------------------------------

def test_find_boss_by_name_and_alias(sample_registry: DungeonRegistry):
    d = sample_registry.lookup(999, Difficulty.NORMAL)
    assert d is not None
    assert d.find_boss("Boss One") is d.bosses[0]
    assert d.find_boss("bossalpha") is d.bosses[0]
    assert d.find_boss("Unknown") is None


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

@pytest.fixture
def coord(sample_registry: DungeonRegistry):
    registry = BotRegistry()
    registry.elevate(42, "Thrargor", "base")
    executor = AsyncMock()
    executor.execute = AsyncMock(return_value="ok")
    return (
        DungeonCoordinator(
            registry=registry,
            command_executor=executor,
            dungeon_registry=sample_registry,
        ),
        executor,
    )


def _snap(map_id: int, *, zone: str = "Sample", strategy: str = "combat", level: int = 70) -> BotSnapshot:
    return BotSnapshot(
        guid=42, map_id=map_id, zone=zone, strategy=strategy, level=level
    )


@pytest.mark.asyncio
async def test_coordinator_emits_entered_and_adds_strategy(coord):
    coordinator, executor = coord
    # Prime last_map_id as 0 (not inside the dungeon yet).
    await coordinator.update({42: _snap(0, zone="Stormwind")})
    assert coordinator.pop_events() == []

    await coordinator.update({42: _snap(999)})
    events = coordinator.pop_events()
    assert len(events) == 1
    evt = events[0]
    assert isinstance(evt, DungeonEnteredEvent)
    assert evt.dungeon_key == "sample_keep"
    assert evt.role == "dps"  # default personality is warrior/arms → dps
    # Strategy add was dispatched.
    call = executor.execute.await_args_list[0]
    cmd = call.args[0]
    assert cmd.command_type is CommandType.ADD_STRATEGY
    assert cmd.payload == {"strategy": "wotlk-sk"}


@pytest.mark.asyncio
async def test_coordinator_restores_strategy_on_exit(coord):
    coordinator, executor = coord
    await coordinator.update({42: _snap(0)})
    await coordinator.update({42: _snap(999, strategy="combat tank")})
    coordinator.pop_events()  # drain entered
    executor.execute.reset_mock()

    await coordinator.update({42: _snap(1, zone="Stormwind")})
    events = coordinator.pop_events()
    assert len(events) == 1
    assert isinstance(events[0], DungeonExitedEvent)
    # Final strategy restore used SET_STRATEGY with the captured string.
    restored = executor.execute.await_args_list[-1].args[0]
    assert restored.command_type is CommandType.SET_STRATEGY
    assert restored.payload == {"strategy": "combat tank"}


@pytest.mark.asyncio
async def test_coordinator_is_idempotent_inside_same_dungeon(coord):
    coordinator, executor = coord
    await coordinator.update({42: _snap(0)})
    await coordinator.update({42: _snap(999)})
    coordinator.pop_events()
    executor.execute.reset_mock()

    # Several ticks on the same map — must not re-enter or re-activate.
    for _ in range(3):
        await coordinator.update({42: _snap(999)})
    assert coordinator.pop_events() == []
    assert executor.execute.await_count == 0


@pytest.mark.asyncio
async def test_coordinator_heroic_gate_uses_level(
    sample_registry: DungeonRegistry,
):
    registry = BotRegistry()
    registry.elevate(42, "Thrargor", "base")
    executor = AsyncMock()
    executor.execute = AsyncMock(return_value="ok")
    coord = DungeonCoordinator(
        registry=registry,
        command_executor=executor,
        dungeon_registry=sample_registry,
    )
    # Level 80 → heroic wins the resolution.
    await coord.update({42: _snap(0)})
    await coord.update({42: _snap(999, level=80)})
    events = coord.pop_events()
    assert events and events[0].dungeon_key == "sample_keep_heroic"


@pytest.mark.asyncio
async def test_coordinator_picks_wing_from_area(tmp_path: Path):
    """Multi-wing YAMLs with the same map_id resolve via snapshot.area."""
    _write_yaml(
        tmp_path / "wing_a.yaml",
        """
key: wing_a
name: Wing A
map_id: 500
sub_zone: "North Wing"
expansion: vanilla
difficulty: normal
overlay_of: null
strategy_key: null
cpp_coverage: none
min_level: 50
max_level: 60
leader_role: tank
general_notes: North.
bosses: []
""".lstrip(),
    )
    _write_yaml(
        tmp_path / "wing_b.yaml",
        """
key: wing_b
name: Wing B
map_id: 500
sub_zone: "South Wing"
expansion: vanilla
difficulty: normal
overlay_of: null
strategy_key: null
cpp_coverage: none
min_level: 50
max_level: 60
leader_role: tank
general_notes: South.
bosses: []
""".lstrip(),
    )
    reg = DungeonRegistry()
    reg.load_dir(tmp_path)

    bot_registry = BotRegistry()
    bot_registry.elevate(42, "Thrargor", "base")
    coordinator = DungeonCoordinator(
        registry=bot_registry, dungeon_registry=reg
    )

    def _snap_wing(area: str) -> BotSnapshot:
        return BotSnapshot(
            guid=42, map_id=500, zone="Test Map", area=area,
            strategy="combat", level=60,
        )

    # First tick: outside, map_id=0. Second tick: entered with known area.
    await coordinator.update(
        {42: BotSnapshot(guid=42, map_id=0, zone="Stormwind", level=60)}
    )
    await coordinator.update({42: _snap_wing("North Wing")})
    evts = [e for e in coordinator.pop_events() if hasattr(e, "dungeon_key")]
    assert evts and evts[0].dungeon_key == "wing_a"


@pytest.mark.asyncio
async def test_coordinator_get_context_with_target(coord):
    coordinator, _ = coord
    await coordinator.update({42: _snap(0)})
    await coordinator.update({42: _snap(999)})
    ctx = coordinator.get_context_with_target(42, "BossAlpha")
    assert ctx is not None
    assert ctx.dungeon.key == "sample_keep"
    assert ctx.current_boss is not None
    assert ctx.current_boss.name == "Boss One"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _dungeon_for_prompt() -> Dungeon:
    return Dungeon(
        key="sample_keep",
        name="Sample Keep",
        map_id=999,
        expansion="wotlk",
        difficulty=Difficulty.NORMAL,
        strategy_key="wotlk-sk",
        cpp_coverage="full",
        leader_role=DungeonRole.TANK,
        general_notes="Test notes.",
        bosses=[
            Boss(
                name="Boss One",
                order=1,
                aliases=["BossAlpha"],
                phases=[
                    BossPhase(
                        name="Phase 1",
                        tank="Tank it hard",
                        healer="Heal hard",
                        dps="DPS hard",
                        mechanics=["Do the thing"],
                    )
                ],
            )
        ],
    )


def test_prompt_includes_dungeon_mode_when_context_supplied():
    snap = BotSnapshot(guid=1, zone="Sample", target_name="Boss One")
    ctx = DungeonContext(
        dungeon=_dungeon_for_prompt(),
        role=DungeonRole.DPS,
        current_boss=_dungeon_for_prompt().bosses[0],
    )
    msg = build_context_message(
        snapshot=snap,
        recent_events=[],
        memories=[],
        triggering_event="something",
        dungeon_context=ctx,
    )
    assert "[DUNGEON MODE]" in msg
    assert "Sample Keep" in msg
    assert "Your role: dps" in msg
    assert "Current boss: Boss One" in msg
    # DPS instructions surfaced, not tank/healer text.
    assert "DPS hard" in msg


def test_prompt_omits_dungeon_section_when_no_context():
    snap = BotSnapshot(guid=1, zone="Stormwind")
    msg = build_context_message(
        snapshot=snap,
        recent_events=[],
        memories=[],
        triggering_event="idle",
    )
    assert "[DUNGEON MODE]" not in msg
