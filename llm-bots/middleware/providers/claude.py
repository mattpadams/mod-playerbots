"""Claude provider — direct Anthropic SDK with manual tool-use loop.

Auth priority:
  1. OAuth token from ~/.claude/.credentials.json (ClaudeAuthManager)
  2. API key from settings.anthropic_api_key / ANTHROPIC_API_KEY env var
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import anthropic

from core.config import settings
from providers.base import LLMProvider, ProviderConfig, ResponseEvent, EventType
from providers.auth.claude_auth import ClaudeAuthManager

logger = logging.getLogger("llm_bots.provider.claude")

MAX_TOOL_ROUNDS = 5


class ClaudeProvider(LLMProvider):
    """LLM provider backed by the Anthropic Python SDK.

    Call ``init_tools(tools)`` once at startup to register the tool
    definitions. All subsequent ``query()`` calls reuse them.
    """

    def __init__(self):
        self.auth = ClaudeAuthManager()
        self._tools_anthropic: list[dict] = []
        self._tool_map: dict[str, object] = {}

    def init_tools(self, tools: list, tool_names: list[str]) -> None:
        """Convert provider-agnostic tools to Anthropic tool-spec dicts.

        Called once during app startup.
        """
        self._tool_map = {fn.tool_name: fn for fn in tools}
        self._tools_anthropic = [
            {
                "name": fn.tool_name,
                "description": fn.tool_description,
                "input_schema": fn.tool_input_schema,
            }
            for fn in tools
        ]
        logger.info(
            "Tools initialized with %d tools: %s",
            len(tool_names), tool_names,
        )

    def _build_client(self, token: str | None) -> anthropic.AsyncAnthropic:
        """Build an Anthropic client from OAuth token or API key."""
        if token:
            return anthropic.AsyncAnthropic(auth_token=token)
        if settings.anthropic_api_key:
            return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        raise RuntimeError(
            "No Anthropic credentials available. "
            "Mount credentials.json or set ANTHROPIC_API_KEY."
        )

    async def query(
        self, prompt: str, config: ProviderConfig
    ) -> AsyncIterator[ResponseEvent]:
        if not self._tools_anthropic:
            logger.warning("No tools registered — call init_tools() at startup")

        token = await self.auth.ensure_valid_token()

        try:
            client = self._build_client(token)
        except RuntimeError as e:
            yield ResponseEvent(EventType.ERROR, {"text": str(e)})
            return

        messages: list[dict] = [{"role": "user", "content": prompt}]
        total_in = 0
        total_out = 0

        try:
            for _round in range(MAX_TOOL_ROUNDS):
                response = await client.messages.create(
                    model=config.model,
                    system=config.system_prompt,
                    tools=self._tools_anthropic or anthropic.NOT_GIVEN,
                    messages=messages,
                    max_tokens=1024,
                )

                total_in += response.usage.input_tokens
                total_out += response.usage.output_tokens

                # Append the full assistant turn to conversation history
                messages.append({
                    "role": "assistant",
                    "content": [block.model_dump() for block in response.content],
                })

                # Yield text blocks immediately
                for block in response.content:
                    if block.type == "text":
                        yield ResponseEvent(
                            EventType.NARRATIVE, {"text": block.text}
                        )

                # Stop if the model is done (no more tool calls)
                if response.stop_reason != "tool_use":
                    break

                # Dispatch all tool calls in this turn
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    logger.info(
                        "Tool: %s(%s)", block.name, json.dumps(block.input)[:120]
                    )
                    yield ResponseEvent(
                        EventType.TOOL_CALL,
                        {"name": block.name, "input": block.input},
                    )

                    fn = self._tool_map.get(block.name)
                    if fn is None:
                        result_text = f"Unknown tool: {block.name}"
                    else:
                        try:
                            raw = await fn(block.input)
                            result_text = _extract_text(raw)
                        except Exception as exc:
                            result_text = f"Tool error: {exc}"
                            logger.error("Tool %s failed: %s", block.name, exc)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

                # Feed all results back as a single user turn
                messages.append({"role": "user", "content": tool_results})

        except anthropic.AuthenticationError:
            if await self.auth.refresh():
                yield ResponseEvent(
                    EventType.ERROR,
                    {"text": "Token refreshed — please retry."},
                )
            else:
                yield ResponseEvent(
                    EventType.ERROR,
                    {"text": "Auth failed. Run 'claude login' on host."},
                )
            return
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            yield ResponseEvent(EventType.ERROR, {"text": str(e)})
            return

        # Emit token usage as the final event
        yield ResponseEvent(
            EventType.USAGE,
            {"tokens_in": total_in, "tokens_out": total_out},
        )


def _extract_text(raw: object) -> str:
    """Normalize MCP-style tool return value to a plain string.

    Tools return ``{"content": [{"type": "text", "text": "..."}]}``.
    The Anthropic API accepts a plain string for ``tool_result.content``.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        content = raw.get("content", [])
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if parts:
                return "\n".join(parts)
        return json.dumps(raw)
    return str(raw)
