"""Per-bot async event queue.

Each elevated bot gets its own queue.  The interface is abstract enough to
swap in Redis Streams later without changing any consumer code.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from game.events import GameEvent


class EventBus:
    """In-memory event bus with per-bot queues."""

    def __init__(self, max_queue_size: int = 100) -> None:
        self._queues: dict[int, asyncio.Queue[GameEvent]] = defaultdict(
            lambda: asyncio.Queue(maxsize=max_queue_size)
        )
        self._wake: asyncio.Event = asyncio.Event()

    async def publish(self, event: GameEvent) -> None:
        """Publish an event to the bot's queue.  Drops oldest if full."""
        q = self._queues[event.bot_guid]
        if q.full():
            try:
                q.get_nowait()  # drop oldest
            except asyncio.QueueEmpty:
                pass
        await q.put(event)
        self._wake.set()

    @property
    def wake_event(self) -> asyncio.Event:
        """Event that is set whenever a push event arrives.

        The supervisor waits on this to wake up immediately instead
        of sleeping the full tick interval.
        """
        return self._wake

    def clear_wake(self) -> None:
        """Reset the wake flag after the supervisor has processed events."""
        self._wake.clear()

    async def consume(self, bot_guid: int, timeout: float = 30.0) -> GameEvent | None:
        """Wait for the next event for a bot, or return None on timeout."""
        q = self._queues[bot_guid]
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def drain(self, bot_guid: int) -> list[GameEvent]:
        """Drain all pending events for a bot (non-blocking)."""
        q = self._queues[bot_guid]
        events = []
        while not q.empty():
            try:
                events.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    def remove_bot(self, bot_guid: int) -> None:
        """Clean up a bot's queue when it is demoted."""
        self._queues.pop(bot_guid, None)
