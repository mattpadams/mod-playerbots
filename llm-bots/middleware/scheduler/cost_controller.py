"""Rate limiting, model routing, and budget tracking for LLM API calls."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

import structlog

from core.config import settings
from game.events import EventType

logger = structlog.get_logger()

# Approximate cost per 1M tokens (USD)
_MODEL_COSTS = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20241022": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}

# Events that warrant the "important" model
_IMPORTANT_EVENTS = {
    EventType.CHAT_RECEIVED,
    EventType.GROUP_INVITE,
    EventType.BOT_DIED,
}

# Max LLM calls per bot per minute
_DEFAULT_RATE_LIMIT = 6


@dataclass
class _BotBucket:
    """Token bucket for per-bot rate limiting."""

    tokens: float = _DEFAULT_RATE_LIMIT
    last_refill: float = field(default_factory=time.monotonic)

    def try_consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(_DEFAULT_RATE_LIMIT, self.tokens + elapsed * (_DEFAULT_RATE_LIMIT / 60.0))
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class CostController:
    """Manages API cost tracking, rate limiting, and model selection."""

    def __init__(self) -> None:
        self._buckets: dict[int, _BotBucket] = defaultdict(_BotBucket)
        self._hourly_spend: float = 0.0
        self._hourly_reset: float = time.monotonic()
        self._total_spend: float = 0.0
        self._call_count: int = 0

    def select_model(self, event_type: EventType) -> str | None:
        """Choose the appropriate model for an event, or None if budget exhausted."""
        self._maybe_reset_hour()
        if self._hourly_spend >= settings.max_hourly_spend_usd:
            logger.warning(
                "cost_controller.budget_exhausted",
                hourly_spend=self._hourly_spend,
                limit=settings.max_hourly_spend_usd,
            )
            return None

        if event_type in _IMPORTANT_EVENTS:
            return settings.model_important
        return settings.model_default

    def check_rate_limit(self, bot_guid: int) -> bool:
        """Return True if the bot can make an LLM call right now."""
        return self._buckets[bot_guid].try_consume()

    def record_usage(self, model: str, tokens_in: int, tokens_out: int) -> None:
        """Record token usage and update cost tracking."""
        costs = _MODEL_COSTS.get(model, {"input": 3.0, "output": 15.0})
        cost = (tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000
        self._hourly_spend += cost
        self._total_spend += cost
        self._call_count += 1

    def _maybe_reset_hour(self) -> None:
        now = time.monotonic()
        if now - self._hourly_reset >= 3600:
            self._hourly_spend = 0.0
            self._hourly_reset = now

    @property
    def hourly_spend(self) -> float:
        self._maybe_reset_hour()
        return self._hourly_spend

    @property
    def total_spend(self) -> float:
        return self._total_spend

    @property
    def call_count(self) -> int:
        return self._call_count

    def get_metrics(self) -> dict:
        return {
            "hourly_spend_usd": round(self.hourly_spend, 4),
            "total_spend_usd": round(self.total_spend, 4),
            "total_calls": self.call_count,
            "hourly_limit_usd": settings.max_hourly_spend_usd,
        }
