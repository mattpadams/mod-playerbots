"""Auto-elevate/demote bots based on player proximity.

Reconciles on every supervisor tick. Reads the latest results from the
``ProximityScanner`` and mutates the ``BotRegistry`` in two directions:

1. Promote bots with a human nearby that aren't yet elevated (auto=True).
2. Demote auto-elevated bots that have been away from any human for
   ``auto_demote_grace_ticks`` consecutive ticks. Pinned (admin)
   elevations are never touched.
"""

from __future__ import annotations

import structlog

from api import metrics
from core.bot_registry import BotRegistry
from core.config import settings
from scheduler.proximity_scanner import ProximityScanner

logger = structlog.get_logger()


class AutoElevator:
    def __init__(
        self,
        registry: BotRegistry,
        scanner: ProximityScanner,
    ) -> None:
        self._registry = registry
        self._scanner = scanner

    def reconcile(self) -> None:
        """Run one pass of promote/demote decisions."""
        if not settings.auto_elevation_enabled:
            return

        # --- Auto-demote: iterate over currently auto-elevated bots. ---
        # Mutates registry; copy the list so we're safe to demote mid-loop.
        for profile in self._registry.all_auto_elevated():
            near = self._scanner.is_near_human(profile.guid)
            if near:
                profile.away_ticks = 0
                continue
            profile.away_ticks += 1
            if profile.away_ticks >= settings.auto_demote_grace_ticks:
                if self._registry.demote(profile.guid, only_if_auto=True):
                    metrics.auto_demotions_total.inc()
                    logger.info(
                        "auto_elevator.demoted",
                        guid=profile.guid,
                        name=profile.name,
                    )

        # --- Auto-promote: bots near humans but not yet elevated. ---
        candidates = self._scanner.bot_candidates_near_humans()
        for guid, name in candidates:
            if self._registry.is_elevated(guid):
                continue
            if self._registry.count >= settings.max_active_agents:
                logger.debug(
                    "auto_elevator.capacity_reached",
                    count=self._registry.count,
                    max=settings.max_active_agents,
                )
                break
            ok = self._registry.elevate(
                guid=guid,
                name=name,
                personality=settings.auto_elevation_personality,
                auto=True,
            )
            if ok:
                metrics.auto_elevations_total.inc()
                logger.info(
                    "auto_elevator.elevated", guid=guid, name=name
                )

        # --- Gauges ---
        metrics.auto_agents_gauge.set(len(self._registry.all_auto_elevated()))
        metrics.pinned_agents_gauge.set(len(self._registry.all_pinned()))
