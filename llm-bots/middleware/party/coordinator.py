"""Facade for multi-bot party coordination (M4).

Wires ``RosterTracker``, ``SharedQuestTracker``, ``LootRollHandler``,
and the ``ArbitrationEngine`` behind one ``update()`` entry point that
the supervisor calls at the top of every tick.

The coordinator publishes its output via three channels:
  1. ``pop_events()`` — returns events the supervisor should push into
     the agent event queues (quest progress, craft requests, vendor-
     nearby bookkeeping).
  2. ``get_party_state(guid)`` — read-only snapshot rendered into the
     LLM prompt.
  3. Direct command dispatch for non-LLM actions (passes for loot
     rolls, auto-vendor ``s gray`` / ``s vendor``).
"""
from __future__ import annotations

import structlog

from core.bot_registry import BotRegistry
from core.command_executor import CommandExecutor
from core.game_client import BotSnapshot, GameClient
from game.commands import BotCommand, CommandType
from game.events import (
    CraftRequestedEvent,
    GameEvent,
    LootRollStartedEvent,
    PartyQuestProgressEvent,
    VendorNearbyEvent,
)
from party.arbitration import ArbitrationEngine
from party.loot_roll_handler import LootRollHandler
from party.models import PartyMember, PartyState, RollCandidate
from party.quest_tracker import SharedQuestTracker
from party.roster import RosterTracker

logger = structlog.get_logger()


class PartyCoordinator:
    """Single owner of all cross-bot coordination state."""

    def __init__(
        self,
        game_client: GameClient,
        registry: BotRegistry,
        executor: CommandExecutor,
    ) -> None:
        self._game = game_client
        self._registry = registry
        self._executor = executor
        self._arbitration = ArbitrationEngine()
        self._roster = RosterTracker(game_client, registry)
        self._quests = SharedQuestTracker()
        self._loot = LootRollHandler(self._arbitration, executor)
        self._pending_events: list[GameEvent] = []

    # -- Public API -----------------------------------------------------------

    async def update(
        self,
        snapshots: dict[int, BotSnapshot],
        *,
        force_roster_refresh: bool = False,
    ) -> None:
        """Run one coordination cycle. Must be called from ``_tick()``."""
        # 1. Keep rosters up to date (poll-based, debounced).
        await self._roster.refresh(snapshots, force=force_roster_refresh)

        # 2. Diff shared quest objectives → per-pickup events. Restrict
        #    tracking to partied bots; solo bots produce no useful
        #    events (broadcast chat tool is a no-op for them).
        partied = {
            guid for guid in snapshots
            if self._roster.get_party_id(guid) is not None
        }
        quest_events = await self._quests.update(
            self._game,
            snapshots,
            partied_guids=partied,
            name_lookup=self._name_for,
        )
        self._pending_events.extend(quest_events)

        # 3. Drop tracker state for bots no longer present.
        stale = self._quests.tracked_guids() - set(snapshots.keys())
        if stale:
            self._quests.forget(stale)

    def get_party_state(self, guid: int) -> PartyState | None:
        """Return an immutable party snapshot for the LLM prompt, or None."""
        state = self._roster.build_state(guid)
        if state is None:
            return None
        members = state.members
        shared = self._quests.shared_progress(members)
        # Replace with full state carrying shared-quest info.
        return PartyState(
            party_id=state.party_id,
            members=members,
            shared_quests=shared,
        )

    def pop_events(self) -> list[GameEvent]:
        """Drain and return all events the coordinator has queued.

        Supervisor folds these into each bot's event list during the
        same tick in which they were produced.
        """
        out = self._pending_events
        self._pending_events = []
        return out

    # -- Event hooks called from api/events.py --------------------------------

    async def on_loot_roll_started(
        self,
        roll_id: str,
        item_id: int,
        item_link: str,
        item_name: str,
        candidate_guids: list[int],
        item_scores: dict[int, float] | None = None,
    ) -> LootRollStartedEvent | None:
        """Called when mod-playerbots POSTs a loot_roll_started event.

        Only elevated bots can have their roll decisions driven by the
        LLM, so non-elevated candidates (real players, rule-engine
        bots) are filtered out before arbitration. If the resulting
        candidate list is empty, we skip: the rule engine will roll
        normally for everyone else.

        ``item_scores`` is optional; if absent we assume every eligible
        bot gets a neutral score of 1.0 (so the role+level tiebreak
        decides). The winner event is queued for the supervisor to
        route to the correct BotAgent.
        """
        candidates: list[RollCandidate] = []
        for guid in candidate_guids:
            # Drop non-elevated candidates — we cannot drive their
            # rolls and routing a winner event to a missing BotAgent
            # would silently drop the decision.
            if not self._registry.is_elevated(guid):
                continue
            member = self._roster_member(guid)
            if member is None:
                continue
            score = (item_scores or {}).get(guid, 1.0)
            candidates.append(
                RollCandidate(
                    guid=guid,
                    name=member.name,
                    score_delta=score,
                    level=member.level,
                    role_rank=member.role_rank,
                    is_player=member.is_player,
                )
            )

        if not candidates:
            return None

        winner_event = await self._loot.handle(
            roll_id=roll_id,
            item_id=item_id,
            item_link=item_link,
            item_name=item_name,
            candidates=candidates,
        )
        if winner_event is not None:
            self._pending_events.append(winner_event)
        return winner_event

    async def fire_craft_request(
        self,
        bot_guid: int,
        item_name: str,
        requested_by: str,
        reason: str = "",
    ) -> None:
        """Queue a craft request for the given bot (called by proximity layer)."""
        self._pending_events.append(
            CraftRequestedEvent(
                bot_guid=bot_guid,
                bot_name=self._name_for(bot_guid),
                item_name=item_name,
                requested_by=requested_by,
                reason=reason,
            )
        )

    async def fire_vendor_nearby(
        self,
        bot_guid: int,
        vendor_name: str,
        inventory_pct: int,
        has_gray: bool,
    ) -> None:
        """Queue a vendor-nearby event AND dispatch the sell commands.

        ``VENDOR_NEARBY`` has ``invoke_llm=False``, so the LLM never
        sees this; we just want the memory trail.
        """
        self._pending_events.append(
            VendorNearbyEvent(
                bot_guid=bot_guid,
                bot_name=self._name_for(bot_guid),
                vendor_name=vendor_name,
                inventory_pct=inventory_pct,
                has_gray=has_gray,
            )
        )
        if has_gray:
            await self._executor.execute(
                BotCommand(
                    command_type=CommandType.VENDOR_SELL,
                    bot_guid=bot_guid,
                    payload={"filter": "gray"},
                )
            )
        if inventory_pct >= 70:
            await self._executor.execute(
                BotCommand(
                    command_type=CommandType.VENDOR_SELL,
                    bot_guid=bot_guid,
                    payload={"filter": "vendor"},
                )
            )

    # -- Internals ------------------------------------------------------------

    def _roster_member(self, guid: int) -> PartyMember | None:
        """Return the cached roster entry for a guid, or None if unknown.

        We deliberately do NOT fabricate a minimal member from the
        registry alone — that would hand the arbitration a bot with
        role_rank=DPS and level=0 even if it's actually a high-level
        tank, silently skewing results when the roster poll hasn't
        refreshed yet. Returning ``None`` makes the caller skip the
        candidate so the next tick (with fresh roster) wins.
        """
        for m in self._roster.get_members(guid):
            if m.guid == guid:
                return m
        return None

    def _name_for(self, guid: int) -> str:
        profile = self._registry.get(guid)
        return profile.name if profile else ""
