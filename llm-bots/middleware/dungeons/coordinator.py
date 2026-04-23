"""Per-tick dungeon detection, strategy activation, and context tracking.

Shape mirrors ``party/coordinator.PartyCoordinator``:

1. Supervisor hands ``update(snapshots)`` every tick.
2. Coordinator detects ``map_id`` transitions into/out of a known
   dungeon, stashes the pre-dungeon strategy string, and queues
   ``ADD_STRATEGY`` / ``SET_STRATEGY`` commands via the command executor.
3. Per-tick encounter tracking (a3): boss engage/defeat, phase
   transitions from target HP, and party-wipe detection across all
   bots inside the same dungeon.
4. Emits dungeon / boss / wipe events on ``pop_events()`` for the
   supervisor to fold into the tick's event stream.
5. Exposes ``get_context(guid)`` returning a ``DungeonContext`` for the
   prompt builder.

Difficulty heuristic: a heroic YAML wins only if the bot's level meets
the heroic gate (>=80 WotLK, >=70 TBC).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import structlog

from core.bot_registry import BotRegistry
from core.command_executor import CommandExecutor
from core.game_client import BotSnapshot
from dungeons.leader import LeaderCandidate, LeaderTracker
from dungeons.loader import DungeonRegistry, get_registry
from dungeons.models import Boss, Difficulty, Dungeon, DungeonRole
from dungeons.role import infer_role
from game.commands import BotCommand, CommandType
from game.events import (
    BossDefeatedEvent,
    BossEngagedEvent,
    BossPhaseChangedEvent,
    DungeonEnteredEvent,
    DungeonExitedEvent,
    GameEvent,
    PartyMemberDiedEvent,
    PartyWipeEvent,
)
from personality.loader import load_profile

logger = structlog.get_logger()


@dataclass
class DungeonContext:
    """Snapshot injected into the prompt when a bot is inside a dungeon."""

    dungeon: Dungeon
    role: DungeonRole
    current_boss: Optional[Boss] = None
    phase_index: int = 0
    is_leader: bool = False


@dataclass
class _BotDungeonState:
    dungeon_key: str
    pre_dungeon_strategy: str
    role: DungeonRole
    added_strategy_key: Optional[str]
    explicit_leader: bool = False
    active_boss: Optional[str] = None   # boss name, if engaged
    phase_index: int = 0


@dataclass
class _DungeonGroupState:
    wipe_announced: bool = False
    # Per-bot death announcement state. A guid in this set means we've
    # already fired PARTY_MEMBER_DIED for that bot's current death; we
    # re-arm (drop the guid) once the bot is alive again. This keeps
    # the leader from getting the same death repeated every tick.
    announced_deaths: set[int] = field(default_factory=set)


def _difficulty_for(level: int, expansion: str) -> Difficulty:
    """Heuristic heroic gate — see module docstring."""
    exp = (expansion or "").lower()
    if exp == "wotlk" and level >= 80:
        return Difficulty.HEROIC
    if exp == "tbc" and level >= 70:
        return Difficulty.HEROIC
    return Difficulty.NORMAL


class DungeonCoordinator:
    """Tracks which bots are inside which dungeon and manages strategy."""

    def __init__(
        self,
        registry: BotRegistry,
        command_executor: Optional[CommandExecutor] = None,
        dungeon_registry: Optional[DungeonRegistry] = None,
    ) -> None:
        self._registry = registry
        self._executor = command_executor
        self._dungeons = dungeon_registry or get_registry()
        self._states: dict[int, _BotDungeonState] = {}
        self._last_map_id: dict[int, int] = {}
        self._pending_events: list[GameEvent] = []
        self._leaders = LeaderTracker()
        self._current_leader: dict[str, Optional[int]] = {}
        self._group_state: dict[str, _DungeonGroupState] = {}

    # -- Public API -----------------------------------------------------------

    def pop_events(self) -> list[GameEvent]:
        events = self._pending_events
        self._pending_events = []
        return events

    def is_leader(self, bot_guid: int) -> bool:
        state = self._states.get(bot_guid)
        if state is None:
            return False
        return self._current_leader.get(state.dungeon_key) == bot_guid

    def get_context(self, bot_guid: int) -> Optional[DungeonContext]:
        state = self._states.get(bot_guid)
        if state is None:
            return None
        dungeon = self._dungeon_by_key(state.dungeon_key)
        if dungeon is None:
            return None
        return DungeonContext(
            dungeon=dungeon,
            role=state.role,
            phase_index=state.phase_index,
            is_leader=self.is_leader(bot_guid),
        )

    def get_context_with_target(
        self, bot_guid: int, target_name: str
    ) -> Optional[DungeonContext]:
        """Same as ``get_context`` but resolves the current boss via target."""
        ctx = self.get_context(bot_guid)
        if ctx is None:
            return None
        ctx.current_boss = ctx.dungeon.find_boss(target_name)
        return ctx

    async def update(self, snapshots: dict[int, BotSnapshot]) -> None:
        # Entry / exit detection first so wipe + leader logic see the
        # right membership.
        for guid, snap in snapshots.items():
            await self._handle_entry_exit(guid, snap)

        # Per-bot encounter tracking (boss engage/phase/defeat).
        for guid, snap in snapshots.items():
            if guid in self._states:
                self._handle_encounter(guid, snap)

        # Per-dungeon group logic (leader election + wipe detection).
        self._refresh_groups(snapshots)

    # -- Internals ------------------------------------------------------------

    def _dungeon_by_key(self, key: str) -> Optional[Dungeon]:
        return next((d for d in self._dungeons.all() if d.key == key), None)

    def _resolve_dungeon(self, snap: BotSnapshot) -> Optional[Dungeon]:
        # Sub-zone lookup chain: try the inner area name first (wings),
        # then the outer zone, then no sub-zone. The loader's own
        # fallback still folds unknown sub-zones to the sub_zone=None
        # entry, so single-wing dungeons continue to work.
        sub_candidates: list[Optional[str]] = []
        if snap.area:
            sub_candidates.append(snap.area)
        if snap.zone and snap.zone != snap.area:
            sub_candidates.append(snap.zone)
        sub_candidates.append(None)
        # De-dupe while preserving order.
        seen: set[Optional[str]] = set()
        sub_candidates = [s for s in sub_candidates if not (s in seen or seen.add(s))]

        def _find(diff: Difficulty) -> Optional[Dungeon]:
            for sub in sub_candidates:
                hit = self._dungeons.lookup(snap.map_id, diff, sub)
                if hit is not None:
                    return hit
            return None

        normal = _find(Difficulty.NORMAL)
        if normal is None:
            return None
        if _difficulty_for(snap.level, normal.expansion) is Difficulty.HEROIC:
            heroic = _find(Difficulty.HEROIC)
            if heroic is not None:
                return heroic
        return normal

    async def _handle_entry_exit(self, guid: int, snap: BotSnapshot) -> None:
        prev_map = self._last_map_id.get(guid)
        self._last_map_id[guid] = snap.map_id

        in_dungeon = self._states.get(guid)

        if in_dungeon is None:
            if prev_map is not None and prev_map == snap.map_id:
                return
            dungeon = self._resolve_dungeon(snap)
            if dungeon is None:
                return
            await self._enter(guid, snap, dungeon)
            return

        if snap.map_id == 0:
            return
        dungeon = self._resolve_dungeon(snap)
        if dungeon is None or dungeon.key != in_dungeon.dungeon_key:
            await self._exit(guid, snap)
            if dungeon is not None:
                await self._enter(guid, snap, dungeon)

    def _handle_encounter(self, guid: int, snap: BotSnapshot) -> None:
        state = self._states[guid]
        dungeon = self._dungeon_by_key(state.dungeon_key)
        if dungeon is None:
            return

        in_combat = snap.state == "combat"
        boss = dungeon.find_boss(snap.target_name) if in_combat else None

        # Engage: combat with a boss target where we weren't already
        # engaged with that boss.
        if boss is not None and state.active_boss != boss.name:
            # If we were engaged with a *different* boss, close it out.
            if state.active_boss is not None:
                self._emit_boss_defeated(guid, dungeon, state.active_boss)
            state.active_boss = boss.name
            state.phase_index = 0
            self._pending_events.append(
                BossEngagedEvent(
                    bot_guid=guid,
                    bot_name=self._bot_name(guid),
                    dungeon_key=dungeon.key,
                    boss_name=boss.name,
                    role=state.role.value,
                    is_leader=self.is_leader(guid),
                )
            )
            logger.info(
                "dungeons.boss_engaged",
                bot_guid=guid,
                dungeon=dungeon.key,
                boss=boss.name,
            )
            return

        # Phase transition: engaged and HP crossed a threshold downward.
        if boss is not None and state.active_boss == boss.name:
            new_phase = boss.phase_for_hp(snap.target_hp_pct)
            if new_phase > state.phase_index:
                state.phase_index = new_phase
                phase_name = (
                    boss.phases[new_phase].name if new_phase < len(boss.phases)
                    else ""
                )
                self._pending_events.append(
                    BossPhaseChangedEvent(
                        bot_guid=guid,
                        bot_name=self._bot_name(guid),
                        dungeon_key=dungeon.key,
                        boss_name=boss.name,
                        phase_index=new_phase,
                        phase_name=phase_name,
                        role=state.role.value,
                    )
                )
                logger.info(
                    "dungeons.boss_phase_changed",
                    bot_guid=guid,
                    dungeon=dungeon.key,
                    boss=boss.name,
                    phase=phase_name,
                )
            return

        # Defeat: we had an active boss, now out of combat (or target
        # no longer matches any boss).
        if state.active_boss is not None and not in_combat:
            self._emit_boss_defeated(guid, dungeon, state.active_boss)
            state.active_boss = None
            state.phase_index = 0

    def _emit_boss_defeated(
        self, guid: int, dungeon: Dungeon, boss_name: str
    ) -> None:
        self._pending_events.append(
            BossDefeatedEvent(
                bot_guid=guid,
                bot_name=self._bot_name(guid),
                dungeon_key=dungeon.key,
                boss_name=boss_name,
            )
        )

    def _refresh_groups(self, snapshots: dict[int, BotSnapshot]) -> None:
        # Group bots by dungeon_key.
        by_dungeon: dict[str, list[int]] = {}
        for guid, state in self._states.items():
            by_dungeon.setdefault(state.dungeon_key, []).append(guid)

        # Drop stale group bookkeeping.
        for key in list(self._group_state):
            if key not in by_dungeon:
                del self._group_state[key]
                self._current_leader.pop(key, None)
                self._leaders.clear(key)

        for dungeon_key, guids in by_dungeon.items():
            dungeon = self._dungeon_by_key(dungeon_key)
            if dungeon is None:
                continue

            candidates = [
                LeaderCandidate(
                    guid=g,
                    role=self._states[g].role,
                    explicit_leader=self._states[g].explicit_leader,
                )
                for g in guids
            ]
            self._current_leader[dungeon_key] = self._leaders.resolve(
                dungeon, candidates
            )

            # Wipe detection: every dungeon member we have a snapshot
            # for must be dead. Members whose snapshots are missing
            # this tick abstain (don't count as alive or dead).
            deads: list[str] = []
            dead_guids: list[int] = []
            living = 0
            for g in guids:
                snap = snapshots.get(g)
                if snap is None:
                    continue
                if snap.state == "dead":
                    deads.append(self._bot_name(g))
                    dead_guids.append(g)
                else:
                    living += 1

            group = self._group_state.setdefault(
                dungeon_key, _DungeonGroupState()
            )

            # Single-member death signal (pre-wipe). Fires once per
            # death per revive cycle, to the leader only. Drop stale
            # revived bots from the announced set so a future death
            # re-fires.
            leader = self._current_leader.get(dungeon_key)
            dead_guid_set = set(dead_guids)
            group.announced_deaths &= dead_guid_set
            if leader is not None and living > 0:
                for g in dead_guids:
                    if g in group.announced_deaths or g == leader:
                        continue
                    self._pending_events.append(
                        PartyMemberDiedEvent(
                            bot_guid=leader,
                            bot_name=self._bot_name(leader),
                            dungeon_key=dungeon.key,
                            dungeon_name=dungeon.name,
                            dead_bot_guid=g,
                            dead_bot_name=self._bot_name(g),
                            dead_bot_role=self._states[g].role.value
                            if g in self._states
                            else "dps",
                        )
                    )
                    group.announced_deaths.add(g)

            all_dead = living == 0 and len(deads) >= 1
            if all_dead and not group.wipe_announced:
                leader = self._current_leader.get(dungeon_key)
                if leader is not None:
                    self._pending_events.append(
                        PartyWipeEvent(
                            bot_guid=leader,
                            bot_name=self._bot_name(leader),
                            dungeon_key=dungeon.key,
                            dungeon_name=dungeon.name,
                            dead_bot_names=deads,
                        )
                    )
                    logger.info(
                        "dungeons.party_wipe",
                        dungeon=dungeon.key,
                        dead=deads,
                        leader_guid=leader,
                    )
                group.wipe_announced = True
            elif not all_dead and group.wipe_announced:
                # Someone came back — reset so a future wipe re-fires.
                group.wipe_announced = False

    def _bot_name(self, guid: int) -> str:
        profile = self._registry.get(guid)
        return profile.name if profile else ""

    async def _enter(
        self, guid: int, snap: BotSnapshot, dungeon: Dungeon
    ) -> None:
        profile = self._registry.get(guid)
        personality_name = profile.personality if profile else "base"
        try:
            profile_data = load_profile(personality_name)
        except Exception:
            profile_data = {}

        role = infer_role(profile_data)
        explicit_leader = (
            str(profile_data.get("dungeon_role", "")).strip().lower() == "leader"
        )

        added_key: Optional[str] = None
        if self._executor is not None and dungeon.strategy_key:
            try:
                await self._executor.execute(
                    BotCommand(
                        bot_guid=guid,
                        command_type=CommandType.ADD_STRATEGY,
                        payload={"strategy": dungeon.strategy_key},
                    )
                )
                added_key = dungeon.strategy_key
            except Exception as exc:
                logger.warning(
                    "dungeons.strategy_add_failed",
                    bot_guid=guid,
                    strategy=dungeon.strategy_key,
                    error=str(exc),
                )

        self._states[guid] = _BotDungeonState(
            dungeon_key=dungeon.key,
            pre_dungeon_strategy=snap.strategy,
            role=role,
            added_strategy_key=added_key,
            explicit_leader=explicit_leader,
        )

        bot_name = profile.name if profile else ""
        self._pending_events.append(
            DungeonEnteredEvent(
                bot_guid=guid,
                bot_name=bot_name,
                dungeon_key=dungeon.key,
                dungeon_name=dungeon.name,
                map_id=dungeon.map_id,
                difficulty=dungeon.difficulty.value,
                role=role.value,
            )
        )
        logger.info(
            "dungeons.entered",
            bot_guid=guid,
            dungeon=dungeon.key,
            role=role.value,
            strategy_added=added_key,
        )

    async def _exit(self, guid: int, snap: BotSnapshot) -> None:
        state = self._states.pop(guid, None)
        if state is None:
            return

        dungeon = self._dungeon_by_key(state.dungeon_key)

        if self._executor is not None and state.added_strategy_key:
            try:
                await self._executor.execute(
                    BotCommand(
                        bot_guid=guid,
                        command_type=CommandType.SET_STRATEGY,
                        payload={"strategy": state.pre_dungeon_strategy},
                    )
                )
            except Exception as exc:
                logger.warning(
                    "dungeons.strategy_restore_failed",
                    bot_guid=guid,
                    error=str(exc),
                )

        profile = self._registry.get(guid)
        bot_name = profile.name if profile else ""
        self._pending_events.append(
            DungeonExitedEvent(
                bot_guid=guid,
                bot_name=bot_name,
                dungeon_key=state.dungeon_key,
                dungeon_name=dungeon.name if dungeon else "",
            )
        )
        logger.info("dungeons.exited", bot_guid=guid, dungeon=state.dungeon_key)
