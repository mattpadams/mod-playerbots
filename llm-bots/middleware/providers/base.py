"""Provider abstraction over an LLM agent runtime.

A provider creates one ``AgentSession`` per bot. The session owns a
stateful conversation with the model and exposes a single
``send(prompt) -> AgentResult`` method per turn.

Tools are passed into ``create_session`` as provider-specific MCP
server configurations and stay attached for the session's lifetime.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Outcome of a single ``AgentSession.send`` call."""

    text: str = ""
    tool_calls: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None


class AgentSession(ABC):
    """A stateful conversation with the model for one bot."""

    @abstractmethod
    async def send(self, prompt: str) -> AgentResult:
        """Send a user turn and drain the response."""

    @abstractmethod
    async def aclose(self) -> None:
        """Tear down the underlying client and free resources."""


class LLMProvider(ABC):
    """Factory for per-bot agent sessions."""

    @abstractmethod
    async def create_session(
        self,
        *,
        system_prompt: str,
        model: str,
        mcp_servers: dict[str, Any],
        allowed_tools: list[str],
    ) -> AgentSession:
        """Build a session with tools pre-attached."""
