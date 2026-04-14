"""Qdrant vector store wrapper for bot long-term memory.

All blocking operations (embedding + Qdrant I/O) are offloaded to a
thread-pool executor so they don't block the asyncio event loop.
"""

from __future__ import annotations

import asyncio
from functools import partial

import structlog
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from core.config import settings
from memory.schemas import MemoryDocument

logger = structlog.get_logger()

COLLECTION_NAME = "bot_memories"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
VECTOR_SIZE = 384


class QdrantStore:
    """Manages bot memory storage and retrieval via Qdrant."""

    def __init__(self) -> None:
        self._client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        self._embedder = SentenceTransformer(EMBEDDING_MODEL)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        collections = [c.name for c in self._client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            logger.info("qdrant.collection_created", name=COLLECTION_NAME)

    def _embed_sync(self, text: str) -> list[float]:
        return self._embedder.encode(text).tolist()

    async def _embed(self, text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._embed_sync, text))

    async def store(self, memory: MemoryDocument) -> None:
        """Store a memory document with its embedding."""
        vector = await self._embed(memory.content)
        point = PointStruct(
            id=memory.id,
            vector=vector,
            payload=memory.to_payload(),
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            partial(self._client.upsert, collection_name=COLLECTION_NAME, points=[point]),
        )
        logger.debug(
            "qdrant.stored",
            bot_guid=memory.bot_guid,
            memory_type=memory.memory_type,
            content_preview=memory.content[:80],
        )

    async def recall(
        self,
        bot_guid: int,
        query: str,
        limit: int = 5,
        memory_type: str | None = None,
    ) -> list[MemoryDocument]:
        """Retrieve the most relevant memories for a bot given a query."""
        vector = await self._embed(query)

        conditions = [FieldCondition(key="bot_guid", match=MatchValue(value=bot_guid))]
        if memory_type:
            conditions.append(
                FieldCondition(key="memory_type", match=MatchValue(value=memory_type))
            )

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            partial(
                self._client.query_points,
                collection_name=COLLECTION_NAME,
                query=vector,
                query_filter=Filter(must=conditions),
                limit=limit,
            ),
        )

        memories = []
        for point in results.points:
            payload = point.payload or {}
            memories.append(
                MemoryDocument(
                    id=str(point.id),
                    bot_guid=payload.get("bot_guid", bot_guid),
                    bot_name=payload.get("bot_name", ""),
                    memory_type=payload.get("memory_type", "conversation"),
                    content=payload.get("content", ""),
                    importance=payload.get("importance", 0.5),
                    related_players=payload.get("related_players", []),
                    zone=payload.get("zone", ""),
                )
            )
        return memories

    async def recall_about_player(
        self, bot_guid: int, player_name: str, limit: int = 3
    ) -> list[MemoryDocument]:
        """Retrieve memories related to a specific player."""
        return await self.recall(
            bot_guid=bot_guid,
            query=f"interactions with {player_name}",
            limit=limit,
        )

    def clear_bot_memories(self, bot_guid: int) -> None:
        """Delete all memories for a bot."""
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[FieldCondition(key="bot_guid", match=MatchValue(value=bot_guid))]
            ),
        )
        logger.info("qdrant.cleared", bot_guid=bot_guid)

    def count_bot_memories(self, bot_guid: int) -> int:
        """Count memories stored for a bot."""
        result = self._client.count(
            collection_name=COLLECTION_NAME,
            count_filter=Filter(
                must=[FieldCondition(key="bot_guid", match=MatchValue(value=bot_guid))]
            ),
        )
        return result.count
