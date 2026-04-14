"""Core types and abstract base class for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator


class EventType(Enum):
    """Types of events yielded by a provider during a query."""

    NARRATIVE = "narrative"
    TOOL_CALL = "tool_call"
    ERROR = "error"
    USAGE = "usage"


@dataclass
class ResponseEvent:
    """A single event emitted by the provider.

    ``data`` contents by type:
    - NARRATIVE: ``{"text": str}``
    - TOOL_CALL: ``{"name": str, "input": dict}``
    - ERROR:     ``{"text": str}``
    """

    type: EventType
    data: dict


@dataclass
class ProviderConfig:
    """Per-query configuration passed to the provider.

    Tools are NOT included here — they live on the persistent MCP server.
    Only the system prompt and model vary per bot/query.
    """

    model: str
    system_prompt: str


class LLMProvider(ABC):
    """Abstract interface that every LLM provider must implement."""

    @abstractmethod
    async def query(
        self, prompt: str, config: ProviderConfig
    ) -> AsyncIterator[ResponseEvent]:
        """Send *prompt* to the model and yield response events."""
        yield  # pragma: no cover
