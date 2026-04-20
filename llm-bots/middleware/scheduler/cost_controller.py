"""Rate limiting, model routing, and budget tracking for LLM API calls."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

import structlog

from api import metrics
from core.config import settings

logger = structlog.get_logger()

# Approximate cost per 1M tokens (USD)
_MODEL_COSTS = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20241022": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
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
        self._hourly_calls: int = 0
        self._hourly_reset: float = time.monotonic()
        self._total_spend: float = 0.0
        self._call_count: int = 0
        self._per_model_calls: dict[str, int] = {}
        self._hourly_limit_override: float | None = None
        self._latency_sum_ms: float = 0.0
        self._latency_samples: int = 0
        # M7 global rate-limit circuit breaker. Set when the provider
        # repeatedly returns 429; cleared when the cooldown elapses.
        self._global_backoff_until: float = 0.0
        self._recent_rate_limit_errors: int = 0
        self._rate_limit_errors_total: int = 0

    def select_model(self, model_tier: str) -> str | None:
        """Return the configured model for a policy tier, or None if budget
        or the global rate-limit breaker is shutting calls down.

        Degradation ladder (M7):
          - admin kill switch on: return None
          - under ``budget_degrade_threshold``: normal tier routing (or
            the admin override if set)
          - between threshold and 100%: force ``"default"`` tier
          - at/over 100%: return None (no call)
          - global rate-limit breaker tripped: return None
        ``model_tier`` comes from ``EventPolicy.model_tier`` — typically
        "important" or "default". Any unknown value falls back to default.
        """
        self._maybe_reset_hour()
        if settings.llm_kill_switch:
            return None
        if self.global_backoff_active:
            logger.warning(
                "cost_controller.global_backoff_active",
                seconds_remaining=round(
                    self._global_backoff_until - time.monotonic(), 1
                ),
            )
            return None
        limit = self.hourly_limit
        if self._hourly_spend >= limit:
            logger.warning(
                "cost_controller.budget_exhausted",
                hourly_spend=self._hourly_spend,
                limit=limit,
            )
            return None

        # Budget-degrade: once we've spent the threshold share of the
        # hourly cap, every call drops to the default tier regardless of
        # the event's usual preference.
        if limit > 0 and self._hourly_spend >= limit * settings.budget_degrade_threshold:
            return settings.model_default

        # Admin override: a non-empty ``llm_model_override`` pins every
        # call to a single model, bypassing tier-based routing entirely.
        if settings.llm_model_override:
            return settings.llm_model_override

        if model_tier == "important":
            return settings.model_important
        return settings.model_default

    def check_rate_limit(self, bot_guid: int) -> bool:
        """Return True if the bot can make an LLM call right now."""
        return self._buckets[bot_guid].try_consume()

    def compute_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Return USD cost for a given model/token usage."""
        costs = _MODEL_COSTS.get(model, {"input": 3.0, "output": 15.0})
        return (tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000

    def record_usage(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Record token usage, update cost tracking, and return call cost."""
        self._maybe_reset_hour()
        cost = self.compute_cost(model, tokens_in, tokens_out)
        self._hourly_spend += cost
        self._hourly_calls += 1
        self._total_spend += cost
        self._call_count += 1
        self._per_model_calls[model] = self._per_model_calls.get(model, 0) + 1
        return cost

    def record_latency(self, latency_ms: float) -> None:
        """Record an LLM call's end-to-end latency for averaging."""
        if latency_ms <= 0:
            return
        self._latency_sum_ms += latency_ms
        self._latency_samples += 1

    def note_rate_limit_error(self) -> None:
        """Record a provider 429. Trips the global breaker after
        ``rate_limit_global_trigger`` consecutive errors."""
        self._rate_limit_errors_total += 1
        self._recent_rate_limit_errors += 1
        if self._recent_rate_limit_errors >= settings.rate_limit_global_trigger:
            self._global_backoff_until = (
                time.monotonic() + settings.rate_limit_global_backoff_seconds
            )
            self._recent_rate_limit_errors = 0
            metrics.rate_limit_errors_total.labels(scope="global").inc()
            logger.warning(
                "cost_controller.global_backoff_engaged",
                seconds=settings.rate_limit_global_backoff_seconds,
            )

    def note_successful_call(self) -> None:
        """Clear the streak of recent 429s once the provider is healthy again."""
        self._recent_rate_limit_errors = 0

    @property
    def global_backoff_active(self) -> bool:
        return time.monotonic() < self._global_backoff_until

    @property
    def global_backoff_remaining_seconds(self) -> float:
        return max(0.0, self._global_backoff_until - time.monotonic())

    @property
    def rate_limit_errors_total(self) -> int:
        return self._rate_limit_errors_total

    @property
    def budget_state(self) -> str:
        """One of ``normal``, ``degrading``, ``exhausted``."""
        self._maybe_reset_hour()
        limit = self.hourly_limit
        if limit <= 0:
            return "normal"
        if self._hourly_spend >= limit:
            return "exhausted"
        if self._hourly_spend >= limit * settings.budget_degrade_threshold:
            return "degrading"
        return "normal"

    def set_hourly_limit(self, limit_usd: float) -> None:
        """Adjust the hourly spend cap at runtime (dashboard admin control)."""
        self._hourly_limit_override = max(0.0, float(limit_usd))

    @property
    def hourly_limit(self) -> float:
        if self._hourly_limit_override is not None:
            return self._hourly_limit_override
        return settings.max_hourly_spend_usd

    @property
    def per_model_calls(self) -> dict[str, int]:
        return dict(self._per_model_calls)

    def _maybe_reset_hour(self) -> None:
        now = time.monotonic()
        if now - self._hourly_reset >= 3600:
            self._hourly_spend = 0.0
            self._hourly_calls = 0
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

    @property
    def calls_this_hour(self) -> int:
        self._maybe_reset_hour()
        return self._hourly_calls

    @property
    def avg_latency_ms(self) -> float:
        if self._latency_samples == 0:
            return 0.0
        return self._latency_sum_ms / self._latency_samples

    def get_metrics(self) -> dict:
        total = self._call_count or 1
        distribution = {m: c / total for m, c in self._per_model_calls.items()}
        return {
            "hourly_spend_usd": round(self.hourly_spend, 4),
            "total_spend_usd": round(self.total_spend, 4),
            "total_calls": self.call_count,
            "calls_this_hour": self.calls_this_hour,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "hourly_limit_usd": self.hourly_limit,
            "model_distribution": distribution,
            "budget_state": self.budget_state,
            "global_backoff_active": self.global_backoff_active,
            "global_backoff_remaining_s": round(
                self.global_backoff_remaining_seconds, 1
            ),
            "rate_limit_errors_total": self.rate_limit_errors_total,
        }
