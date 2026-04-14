"""High-level memory operations for bot agents.

Handles importance scoring, storage decisions, and multi-query retrieval
with Reciprocal Rank Fusion.  All public methods are async.
"""

from __future__ import annotations

from game.events import (
    ChatReceivedEvent,
    CombatEndEvent,
    EventType,
    GameEvent,
    ZoneChangedEvent,
)
from memory.qdrant_store import QdrantStore
from memory.schemas import MemoryDocument, MemoryType

# Importance scores by event type
_IMPORTANCE: dict[EventType, float] = {
    EventType.CHAT_RECEIVED: 0.8,
    EventType.COMBAT_START: 0.4,
    EventType.COMBAT_END: 0.5,
    EventType.BOT_DIED: 0.9,
    EventType.ZONE_CHANGED: 0.3,
    EventType.TARGET_CHANGED: 0.2,
    EventType.STRATEGY_CHANGED: 0.2,
    EventType.STATE_SNAPSHOT: 0.1,
    EventType.IDLE_TICK: 0.0,
}

DEFAULT_IMPORTANCE_THRESHOLD = 0.4


class MemoryManager:
    """Manages memory storage and retrieval for bot agents."""

    def __init__(
        self, store: QdrantStore, importance_threshold: float = DEFAULT_IMPORTANCE_THRESHOLD
    ) -> None:
        self._store = store
        self._threshold = importance_threshold

    async def maybe_store_event(
        self,
        bot_guid: int,
        bot_name: str,
        event: GameEvent,
    ) -> bool:
        """Evaluate an event's importance and store it if above threshold."""
        importance = _IMPORTANCE.get(event.event_type, 0.3)
        if importance < self._threshold:
            return False

        content = self._event_to_memory_text(event)
        if not content:
            return False

        memory_type = self._event_to_memory_type(event)
        related_players = self._extract_related_players(event)

        doc = MemoryDocument(
            bot_guid=bot_guid,
            bot_name=bot_name,
            memory_type=memory_type,
            content=content,
            importance=importance,
            related_players=related_players,
            zone=getattr(event, "zone", ""),
        )
        await self._store.store(doc)
        return True

    async def store_explicit(
        self,
        bot_guid: int,
        bot_name: str,
        content: str,
        memory_type: MemoryType = MemoryType.CONVERSATION,
        importance: float = 0.7,
        related_players: list[str] | None = None,
    ) -> None:
        """Store a memory explicitly (e.g., from the agent's remember_this tool)."""
        doc = MemoryDocument(
            bot_guid=bot_guid,
            bot_name=bot_name,
            memory_type=memory_type,
            content=content,
            importance=importance,
            related_players=related_players or [],
        )
        await self._store.store(doc)

    async def get_context(
        self,
        bot_guid: int,
        situation_query: str,
        player_name: str | None = None,
        limit: int = 5,
    ) -> list[str]:
        """Retrieve relevant memories using multi-query RRF.

        Runs up to 3 queries and fuses results:
        1. Situational query (current events)
        2. Player-specific query (if a player is involved)
        3. General personality/relationship context
        """
        all_results: list[tuple[str, float]] = []

        # Query 1: situational
        situational = await self._store.recall(bot_guid, situation_query, limit=limit)
        for rank, mem in enumerate(situational):
            all_results.append((mem.content, 1.0 / (rank + 1)))

        # Query 2: player-specific
        if player_name:
            player_mems = await self._store.recall_about_player(bot_guid, player_name, limit=3)
            for rank, mem in enumerate(player_mems):
                all_results.append((mem.content, 1.0 / (rank + 1)))

        # Query 3: personality anchors
        personality = await self._store.recall(
            bot_guid, "my personality and values", limit=2, memory_type="personality"
        )
        for rank, mem in enumerate(personality):
            all_results.append((mem.content, 1.0 / (rank + 1)))

        # Reciprocal Rank Fusion: deduplicate and sort by combined score
        scored: dict[str, float] = {}
        for content, score in all_results:
            scored[content] = scored.get(content, 0.0) + score

        ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)
        return [content for content, _ in ranked[:limit]]

    def _event_to_memory_text(self, event: GameEvent) -> str:
        if isinstance(event, ChatReceivedEvent):
            return f'{event.sender_name} said in {event.channel}: "{event.message}"'
        if isinstance(event, CombatEndEvent):
            return "Combat ended."
        if isinstance(event, ZoneChangedEvent):
            return f"Traveled from {event.old_zone} to {event.new_zone}."
        if event.event_type == EventType.BOT_DIED:
            return "I died in battle."
        return ""

    def _event_to_memory_type(self, event: GameEvent) -> MemoryType:
        if isinstance(event, ChatReceivedEvent):
            return MemoryType.CONVERSATION
        if event.event_type in (
            EventType.COMBAT_START,
            EventType.COMBAT_END,
            EventType.BOT_DIED,
        ):
            return MemoryType.COMBAT_LESSON
        if isinstance(event, ZoneChangedEvent):
            return MemoryType.WORLD_EVENT
        return MemoryType.WORLD_EVENT

    def _extract_related_players(self, event: GameEvent) -> list[str]:
        if isinstance(event, ChatReceivedEvent):
            return [event.sender_name]
        return []
