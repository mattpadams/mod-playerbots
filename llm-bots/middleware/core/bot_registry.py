"""Tracks which bots are elevated to LLM mode vs. running the rule engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from core.config import settings

logger = structlog.get_logger()


@dataclass
class BotProfile:
    """Runtime state for an LLM-elevated bot."""

    guid: int
    name: str
    personality: str = "default"
    elevated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    degraded_until: datetime | None = None
    total_llm_calls: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    last_llm_action: str = ""
    # True when the AutoElevator promoted this bot based on player
    # proximity. Admin/manual elevations keep this False and are treated
    # as "pinned" — the auto-demoter never touches them.
    auto_elevated: bool = False
    # Number of consecutive proximity scans with no human nearby. The
    # auto-demoter uses this for grace-window logic; only meaningful when
    # auto_elevated is True.
    away_ticks: int = 0


class BotRegistry:
    """Manages the set of LLM-elevated bots."""

    def __init__(self) -> None:
        self._bots: dict[int, BotProfile] = {}

    def elevate(
        self,
        guid: int,
        name: str,
        personality: str = "default",
        auto: bool = False,
    ) -> bool:
        """Elevate a bot to LLM mode.

        Returns False if already elevated *as pinned* (so re-elevation by
        the auto-elevator can't downgrade a pin) or if we're at capacity.
        ``auto=True`` marks the elevation as proximity-driven and
        eligible for auto-demotion; the default is manual/admin and
        treated as pinned.
        """
        existing = self._bots.get(guid)
        if existing is not None:
            # Re-elevation as pinned promotes an auto bot to pinned.
            if not auto and existing.auto_elevated:
                existing.auto_elevated = False
                existing.away_ticks = 0
                logger.info("bot_registry.promoted_to_pinned", guid=guid)
            return True
        if len(self._bots) >= settings.max_active_agents:
            logger.warning(
                "bot_registry.at_capacity",
                current=len(self._bots),
                max=settings.max_active_agents,
            )
            return False
        self._bots[guid] = BotProfile(
            guid=guid, name=name, personality=personality, auto_elevated=auto
        )
        logger.info(
            "bot_registry.elevated",
            guid=guid,
            name=name,
            personality=personality,
            auto=auto,
        )
        return True

    def demote(self, guid: int, only_if_auto: bool = False) -> bool:
        """Return a bot to rule-engine mode.

        ``only_if_auto=True`` protects admin-pinned bots from the
        auto-demoter; returns False without demoting when the bot is
        pinned.
        """
        profile = self._bots.get(guid)
        if profile is None:
            return False
        if only_if_auto and not profile.auto_elevated:
            return False
        del self._bots[guid]
        logger.info(
            "bot_registry.demoted", guid=guid, auto=profile.auto_elevated
        )
        return True

    def is_elevated(self, guid: int) -> bool:
        return guid in self._bots

    def get(self, guid: int) -> BotProfile | None:
        return self._bots.get(guid)

    def all_elevated(self) -> list[BotProfile]:
        return list(self._bots.values())

    def all_auto_elevated(self) -> list[BotProfile]:
        return [p for p in self._bots.values() if p.auto_elevated]

    def all_pinned(self) -> list[BotProfile]:
        return [p for p in self._bots.values() if not p.auto_elevated]

    @property
    def count(self) -> int:
        return len(self._bots)

    def mark_degraded(self, guid: int, until: datetime) -> None:
        """Temporarily disable LLM calls for a bot (API errors, etc.)."""
        profile = self._bots.get(guid)
        if profile:
            profile.degraded_until = until

    def is_degraded(self, guid: int) -> bool:
        profile = self._bots.get(guid)
        if not profile or not profile.degraded_until:
            return False
        if datetime.now(timezone.utc) >= profile.degraded_until:
            profile.degraded_until = None
            return False
        return True
