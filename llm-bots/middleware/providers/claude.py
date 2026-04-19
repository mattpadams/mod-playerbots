"""Claude provider — backed by the Claude Agent SDK.

Auth is handled entirely by the SDK / underlying Claude Code CLI:
- ``ANTHROPIC_API_KEY`` env var if present, otherwise
- OAuth credentials at ``~/.claude/.credentials.json`` (run ``claude
  login`` on the host and mount the file into the container).
"""
from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from providers.base import AgentResult, AgentSession, LLMProvider

logger = logging.getLogger("llm_bots.provider.claude")

MAX_TURNS = 5


class ClaudeProvider(LLMProvider):
    async def create_session(
        self,
        *,
        system_prompt: str,
        model: str,
        mcp_servers: dict[str, Any],
        allowed_tools: list[str],
    ) -> AgentSession:
        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system_prompt,
            mcp_servers=mcp_servers,
            allowed_tools=allowed_tools,
            permission_mode="bypassPermissions",
            max_turns=MAX_TURNS,
        )
        client = ClaudeSDKClient(options=options)
        await client.__aenter__()
        return ClaudeSession(client)


class ClaudeSession(AgentSession):
    def __init__(self, client: ClaudeSDKClient) -> None:
        self._client = client

    async def send(self, prompt: str) -> AgentResult:
        result = AgentResult()
        try:
            await self._client.query(prompt)
            text_parts: list[str] = []
            async for message in self._client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text_parts.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            result.tool_calls.append(block.name)
                elif isinstance(message, ResultMessage):
                    usage = message.usage or {}
                    result.tokens_in = usage.get("input_tokens", 0)
                    result.tokens_out = usage.get("output_tokens", 0)
                    result.cache_read_tokens = usage.get(
                        "cache_read_input_tokens", 0
                    )
                    result.cache_creation_tokens = usage.get(
                        "cache_creation_input_tokens", 0
                    )
                    result.cost_usd = message.total_cost_usd or 0.0
            result.text = "\n".join(text_parts).strip()
        except Exception as exc:
            result.error = str(exc)
            logger.error("claude.session_error: %s", exc)
        return result

    async def aclose(self) -> None:
        try:
            await self._client.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning("claude.session_close_error: %s", exc)
