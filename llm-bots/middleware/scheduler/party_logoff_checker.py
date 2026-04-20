"""Periodic enforcer for the per-player bot-logoff rules.

One scheduled task polls every ``interval_seconds`` (30 s default):

  1. Pulls every player-bot assignment from ``acore_llmbots``.
  2. Fetches live character meta (name / level / online) for the owning
     players and their assigned bots from ``acore_characters``.
  3. Groups bots by ``party_slot`` per player and, using the capped-level
     formula in :mod:`admin.assignment_service`, decides which bots must
     be offline.
  4. Issues ``.bot logoff <name>`` via SOAP for every still-online bot
     that should be down.
  5. Refreshes :mod:`core.player_policy` so the agent hot path can cheap
     out LLM calls for LLM-disabled owners.

Rules mirror the user's spec:

  * ``bots_enabled`` false on ``player_settings`` ⇒ every bot offline.
  * Player offline ⇒ every bot offline regardless of party slot.
  * Player online ⇒ per-party capped-avg rule: if avg capped level of
    the party ≥ the player's level, the whole party logs off.
  * Main party (slot 0) has no exception — the same rule applies when
    the player is online.

The checker never brings bots online; it only logs them off.  Login
flow is the C++ mod's responsibility.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass

import structlog

from admin.assignment_service import party_avg_capped
from core import player_policy
from core.db_client import DbClient
from core.soap_client import SoapClient
from db.engine import session_factory
from db.repos.assignment_repo import AssignmentRepo
from db.repos.player_settings_repo import PlayerSettingsRepo
from db.repos.bot_repo import BotRepo

logger = structlog.get_logger()


@dataclass
class _PartyDecision:
    player_guid: int
    party_slot: int
    bot_guids: list[int]
    avg_capped: float
    should_logoff: bool
    reason: str


class PartyLogoffChecker:
    """Background task that enforces assignment-based logoff rules."""

    def __init__(
        self,
        assignment_repo: AssignmentRepo,
        player_settings_repo: PlayerSettingsRepo,
        bot_repo: BotRepo,
        db_client: DbClient,
        soap: SoapClient,
        interval_seconds: float = 30.0,
    ) -> None:
        self._assignments = assignment_repo
        self._player_settings = player_settings_repo
        self._bots = bot_repo
        self._db = db_client
        self._soap = soap
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run())
        logger.info(
            "party_logoff_checker.started", interval_s=self._interval
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        logger.info("party_logoff_checker.stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception as exc:
                logger.error("party_logoff_checker.tick_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                continue

    async def tick(self) -> None:
        """One evaluation pass. Broken out so tests can call directly."""
        async with session_factory()() as session:
            all_assignments = await self._assignments.list_all(session)
            all_player_settings = await self._player_settings.list_all(session)
            all_bots = await self._bots.list_all(session)

        if not all_assignments:
            player_policy.update(llm_disabled=set(), bot_disabled=set())
            return

        by_player: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for row in all_assignments:
            by_player[row.player_guid].append((row.bot_guid, row.party_slot))

        ps_map = {ps.player_guid: ps for ps in all_player_settings}
        bot_levels = {b.character_guid: b.level for b in all_bots}

        bot_guids = {guid for parties in by_player.values() for guid, _ in parties}
        player_guids = set(by_player.keys())
        try:
            char_meta = await self._db.fetch_character_meta(
                bot_guids | player_guids
            )
        except Exception as exc:
            # Don't clobber the cached policy on a transient MySQL hiccup
            # — re-enabling LLM for every bot because the characters DB
            # was briefly unreachable is worse than a stale tick.
            logger.warning(
                "party_logoff_checker.meta_fetch_failed", error=str(exc)
            )
            return

        logoff_names: list[str] = []
        llm_disabled: set[int] = set()
        bot_disabled: set[int] = set()

        for player_guid, entries in by_player.items():
            ps = ps_map.get(player_guid)
            bots_enabled = ps.bots_enabled if ps else True
            llm_enabled = ps.llm_enabled if ps else True

            player_char = char_meta.get(player_guid)
            player_online = player_char.online if player_char else False
            player_level = player_char.level if player_char else 1

            player_bot_guids = {g for g, _ in entries}
            if not bots_enabled:
                bot_disabled.update(player_bot_guids)
            if not llm_enabled:
                llm_disabled.update(player_bot_guids)

            parties: dict[int, list[int]] = defaultdict(list)
            for guid, slot in entries:
                parties[slot].append(guid)

            for slot, guids in parties.items():
                levels = [bot_levels.get(g, 1) for g in guids]
                avg = party_avg_capped(levels, player_level)
                should_logoff = (
                    (not bots_enabled)
                    or (not player_online)
                    or (avg >= player_level)
                )
                if not should_logoff:
                    continue
                for guid in guids:
                    meta = char_meta.get(guid)
                    if meta is None or not meta.online:
                        continue
                    logoff_names.append(meta.name)

        player_policy.update(
            llm_disabled=llm_disabled, bot_disabled=bot_disabled
        )

        if not logoff_names:
            logger.debug(
                "party_logoff_checker.tick_complete",
                players=len(by_player),
                logoffs=0,
            )
            return

        for name in logoff_names:
            await self._soap.bot_command(name, "logoff")
        logger.info(
            "party_logoff_checker.logged_off",
            count=len(logoff_names),
            players=len(by_player),
        )

