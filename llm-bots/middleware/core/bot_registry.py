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


class BotRegistry:
    """Manages the set of LLM-elevated bots."""

    def __init__(self) -> None:
        self._bots: dict[int, BotProfile] = {}

    def elevate(self, guid: int, name: str, personality: str = "default") -> bool:
        """Elevate a bot to LLM mode.  Returns False if at capacity."""
        if guid in self._bots:
            return True
        if len(self._bots) >= settings.max_active_agents:
            logger.warning(
                "bot_registry.at_capacity",
                current=len(self._bots),
                max=settings.max_active_agents,
            )
            return False
        self._bots[guid] = BotProfile(guid=guid, name=name, personality=personality)
        logger.info("bot_registry.elevated", guid=guid, name=name, personality=personality)
        return True

    def demote(self, guid: int) -> bool:
        """Return a bot to rule-engine mode."""
        if guid not in self._bots:
            return False
        del self._bots[guid]
        logger.info("bot_registry.demoted", guid=guid)
        return True

    def is_elevated(self, guid: int) -> bool:
        return guid in self._bots

    def get(self, guid: int) -> BotProfile | None:
        return self._bots.get(guid)

    def all_elevated(self) -> list[BotProfile]:
        return list(self._bots.values())

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
