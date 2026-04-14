"""Memory document schemas for the vector database."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    CONVERSATION = "conversation"
    RELATIONSHIP = "relationship"
    WORLD_EVENT = "world_event"
    QUEST_OUTCOME = "quest_outcome"
    COMBAT_LESSON = "combat_lesson"
    PERSONALITY = "personality"


class MemoryDocument(BaseModel):
    """A single memory stored in the vector database."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    bot_guid: int
    bot_name: str = ""
    memory_type: MemoryType
    content: str
    importance: float = 0.5  # 0.0 to 1.0
    related_players: list[str] = Field(default_factory=list)
    zone: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_payload(self) -> dict:
        """Convert to Qdrant-compatible payload dict."""
        return {
            "bot_guid": self.bot_guid,
            "bot_name": self.bot_name,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "importance": self.importance,
            "related_players": self.related_players,
            "zone": self.zone,
            "created_at": self.created_at.isoformat(),
        }
