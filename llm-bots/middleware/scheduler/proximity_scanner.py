"""Periodically scan the characters DB for humans near bots.

The scanner is the single source of truth for "where are the real
players right now" — it runs on its own slow-tick (5s default) and
publishes a per-bot proximity map that the AutoElevator reads on every
supervisor tick without ever touching the DB itself.

Positions used for bots come from ``AgentSupervisor.last_snapshots`` so
elevated bots benefit from the 3s poll and we don't re-query positions
for them. Non-elevated bot positions are fetched directly from the
characters DB in the same query as humans — we filter humans and bots
out of the same row set.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from api import metrics
from core.config import settings
from core.db_client import DbClient, HumanCharacter

logger = structlog.get_logger()


class ProximityScanner:
    """Async task that refreshes the set of bots near any human."""

    def __init__(self, db: DbClient) -> None:
        self._db = db
        # GUID → True if any human is within proximity_radius_yards
        # this scan cycle. Populated for EVERY bot guid in
        # acore_playerbots, not only elevated bots, so the auto-elevator
        # can discover candidates to promote.
        self._nearby: dict[int, bool] = {}
        # GUID → (name, map, x, y, z) for all known bots at last scan.
        # The auto-elevator uses this to discover candidates to elevate.
        self._bot_positions: dict[int, tuple[str, int, float, float, float]] = {}
        self._last_scan_monotonic: float = 0.0
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # -- Public read surface --------------------------------------------------

    def is_near_human(self, bot_guid: int) -> bool:
        return self._nearby.get(bot_guid, False)

    def bot_candidates_near_humans(self) -> list[tuple[int, str]]:
        """Return (guid, name) for every bot currently near a human.

        Used by the AutoElevator to find bots to promote. Ordered is
        deterministic for stable test assertions.
        """
        out: list[tuple[int, str]] = []
        for guid, near in self._nearby.items():
            if not near:
                continue
            meta = self._bot_positions.get(guid)
            if meta is None:
                continue
            out.append((guid, meta[0]))
        out.sort(key=lambda t: t[0])
        return out

    @property
    def last_scan_age_seconds(self) -> float:
        if self._last_scan_monotonic == 0.0:
            return float("inf")
        return time.monotonic() - self._last_scan_monotonic

    # -- Lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run())
        logger.info(
            "proximity_scanner.started",
            interval_s=settings.proximity_scan_interval_seconds,
            radius_y=settings.proximity_radius_yards,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        logger.info("proximity_scanner.stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.scan_once()
            except Exception as exc:
                logger.error("proximity_scanner.scan_error", error=str(exc))
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=settings.proximity_scan_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    # -- Scan -----------------------------------------------------------------

    async def scan_once(self) -> None:
        """One pass: pull bot GUIDs, pull online chars, compute proximity."""
        start = time.monotonic()
        bot_guids = await self._db.fetch_bot_guids()
        if not bot_guids:
            # Nothing to elevate / nothing to exclude → empty scan.
            self._nearby = {}
            self._bot_positions = {}
            self._last_scan_monotonic = time.monotonic()
            metrics.proximity_scan_duration_seconds.observe(
                time.monotonic() - start
            )
            return
        # One query: all online characters (bots + humans share the
        # table). We pass an empty bot set so the DB call returns every
        # online row, then split locally — this gives us bot positions
        # and human positions with a single query.
        all_rows = await self._db.fetch_online_humans(bot_guids=set())
        if not all_rows:
            # Treat an empty result as a transient DB hiccup: keep the
            # previous proximity map instead of flipping every bot to
            # "away" and triggering a cascade of auto-demotions.
            logger.warning(
                "proximity_scanner.empty_result_preserving_state"
            )
            self._last_scan_monotonic = time.monotonic()
            metrics.proximity_scan_duration_seconds.observe(
                time.monotonic() - start
            )
            return
        humans = [h for h in all_rows if h.guid not in bot_guids]
        bots_online = [h for h in all_rows if h.guid in bot_guids]

        # Index humans by map_id so we only compare bots to humans on
        # the same map — cross-map distance is always "far".
        humans_by_map: dict[int, list[HumanCharacter]] = {}
        for h in humans:
            humans_by_map.setdefault(h.map_id, []).append(h)

        radius_sq = settings.proximity_radius_yards ** 2
        nearby: dict[int, bool] = {guid: False for guid in bot_guids}
        positions: dict[int, tuple[str, int, float, float, float]] = {}

        for bot in bots_online:
            positions[bot.guid] = (bot.name, bot.map_id, bot.x, bot.y, bot.z)
            for human in humans_by_map.get(bot.map_id, ()):
                dx = bot.x - human.x
                dy = bot.y - human.y
                dz = bot.z - human.z
                if dx * dx + dy * dy + dz * dz <= radius_sq:
                    nearby[bot.guid] = True
                    break

        self._nearby = nearby
        self._bot_positions = positions
        self._last_scan_monotonic = time.monotonic()
        duration = time.monotonic() - start
        metrics.proximity_scan_duration_seconds.observe(duration)
        logger.debug(
            "proximity_scanner.scan_complete",
            humans=len(humans),
            bots_online=len(bots_online),
            near_human=sum(1 for v in nearby.values() if v),
            duration_ms=round(duration * 1000),
        )

    # -- Test helpers ---------------------------------------------------------

    def _inject_scan_state(
        self,
        nearby: dict[int, bool],
        positions: dict[int, tuple[str, int, float, float, float]],
    ) -> None:
        """Testing hook — bypass DB and set state directly."""
        self._nearby = dict(nearby)
        self._bot_positions = dict(positions)
        self._last_scan_monotonic = time.monotonic()


def distance_squared(
    ax: float, ay: float, az: float, bx: float, by: float, bz: float
) -> float:
    """Squared 3D distance — exposed for tests."""
    dx, dy, dz = ax - bx, ay - by, az - bz
    return dx * dx + dy * dy + dz * dz
