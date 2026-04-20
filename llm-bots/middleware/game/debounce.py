"""Per-bot event debouncing.

Sits between ``state_differ.diff()`` and the per-bot event queue.
Filters out events whose policy specifies a cooldown that has not yet
elapsed.

Why not put this in ``state_differ.diff()``?
``diff()`` is a pure function — it must stay pure for testability.
Debouncing is inherently stateful (tracks last-emission times per bot).
Keeping them separate preserves both properties.

The filter is created per-bot in ``AgentSupervisor`` with the same
lifecycle as the ``BotAgent``. Demoting and re-elevating a bot resets
the debounce state, which is the desired behavior.

Note on ``HEALTH_CRITICAL`` specifically: the diff emits the event only
on a threshold *crossing* (old.hp > 20, new.hp <= 20). HP that stays
at or below 20% indefinitely produces no further events to debounce.
Healing above 20% and re-dropping produces a new crossing — the
cooldown gate on its own is sufficient to prevent spam.
"""
from __future__ import annotations

import time

from game.event_policy import get_policy
from game.events import EventType, GameEvent


class DebounceFilter:
    """Filters a list of GameEvents per bot, suppressing events whose
    policy cooldown has not elapsed.

    Not thread-safe (asyncio single-threaded use only).
    """

    def __init__(self) -> None:
        # Maps EventType → monotonic timestamp of last emission
        self._last_emitted: dict[EventType, float] = {}

    def filter(
        self, events: list[GameEvent], current_hp_pct: int = 100
    ) -> list[GameEvent]:
        """Return only events that should be allowed through right now.

        Parameters
        ----------
        events:
            Raw events from ``state_differ.diff()``.
        current_hp_pct:
            The bot's current HP%. Currently unused — reserved for
            future per-policy gating rules that depend on live state.
        """
        del current_hp_pct  # reserved for future use

        now = time.monotonic()
        allowed: list[GameEvent] = []

        for event in events:
            policy = get_policy(event.event_type)

            # Events that don't trigger LLM calls still pass through —
            # they update the recent-events buffer and memory store.
            if not policy.invoke_llm:
                allowed.append(event)
                continue

            # Cooldown gate
            if policy.cooldown_seconds > 0:
                last = self._last_emitted.get(event.event_type, 0.0)
                if now - last < policy.cooldown_seconds:
                    continue

            allowed.append(event)
            if policy.cooldown_seconds > 0:
                self._last_emitted[event.event_type] = now

        return allowed

    def reset(self) -> None:
        """Clear all debounce state. Called when a bot is demoted."""
        self._last_emitted.clear()
