"""Milestone 1: Chat MVP smoke tests.

Run with:
    cd llm-bots/middleware
    python -m pytest tests/test_m1_chat_mvp.py -v

These tests verify the M1 provider refactor without needing the game
server, Qdrant, or live API credentials.  They use mocks for the
Anthropic API to validate the agent loop, tool dispatch, and
token tracking.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Allow imports from the middleware package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers.base import EventType, ResponseEvent
from providers.claude import ClaudeProvider, _extract_text
from providers.tool_adapter import tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_block(text: str):
    """Create a mock TextBlock."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    block.model_dump = MagicMock(return_value={"type": "text", "text": text})
    return block


def _make_tool_use_block(name: str, input_data: dict, tool_id: str = "toolu_01"):
    """Create a mock ToolUseBlock."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_data
    block.id = tool_id
    block.text = None
    block.model_dump = MagicMock(return_value={
        "type": "tool_use", "id": tool_id, "name": name, "input": input_data,
    })
    return block


def _make_response(content_blocks, stop_reason="end_turn", tokens_in=100, tokens_out=50):
    """Create a mock Anthropic Message response."""
    resp = MagicMock()
    resp.content = content_blocks
    resp.stop_reason = stop_reason
    resp.usage = MagicMock()
    resp.usage.input_tokens = tokens_in
    resp.usage.output_tokens = tokens_out
    return resp


def _make_test_tools():
    """Create a simple test tool for the provider."""
    @tool(
        name="test_say",
        description="Test say tool",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": ["bot_guid", "message"],
        },
    )
    async def test_say(args):
        return {"content": [{"type": "text", "text": f"Said: {args['message']}"}]}

    return [test_say]


async def _collect_events(provider, prompt, config):
    """Collect all ResponseEvents from a provider query."""
    events = []
    async for event in provider.query(prompt, config):
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# Unit tests: _extract_text
# ---------------------------------------------------------------------------

class TestExtractText:
    def test_plain_string(self):
        assert _extract_text("hello") == "hello"

    def test_mcp_format_single_block(self):
        raw = {"content": [{"type": "text", "text": "Done."}]}
        assert _extract_text(raw) == "Done."

    def test_mcp_format_multi_block(self):
        raw = {"content": [
            {"type": "text", "text": "Line 1"},
            {"type": "text", "text": "Line 2"},
        ]}
        assert _extract_text(raw) == "Line 1\nLine 2"

    def test_empty_content_list(self):
        raw = {"content": []}
        result = _extract_text(raw)
        assert isinstance(result, str)

    def test_non_text_blocks_skipped(self):
        raw = {"content": [
            {"type": "image", "url": "..."},
            {"type": "text", "text": "Only this"},
        ]}
        assert _extract_text(raw) == "Only this"

    def test_dict_without_content(self):
        raw = {"result": "ok"}
        result = _extract_text(raw)
        assert "result" in result

    def test_non_dict_non_string(self):
        assert _extract_text(42) == "42"
        assert _extract_text(None) == "None"


# ---------------------------------------------------------------------------
# Unit tests: ClaudeProvider.init_tools
# ---------------------------------------------------------------------------

class TestInitTools:
    def test_registers_tools(self):
        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider._tools_anthropic = []
        provider._tool_map = {}

        tools = _make_test_tools()
        provider.init_tools(tools, ["test_say"])

        assert len(provider._tools_anthropic) == 1
        assert provider._tools_anthropic[0]["name"] == "test_say"
        assert "test_say" in provider._tool_map

    def test_tool_schema_format(self):
        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider._tools_anthropic = []
        provider._tool_map = {}

        tools = _make_test_tools()
        provider.init_tools(tools, ["test_say"])

        schema = provider._tools_anthropic[0]
        assert "name" in schema
        assert "description" in schema
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"
        assert "message" in schema["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# Integration tests: agent loop (mocked API)
# ---------------------------------------------------------------------------

class TestAgentLoop:
    """Test the provider's agent loop with mocked Anthropic API calls."""

    @pytest.fixture
    def provider(self):
        """Create a ClaudeProvider with test tools, bypassing __init__."""
        p = ClaudeProvider.__new__(ClaudeProvider)
        p.auth = AsyncMock()
        p.auth.ensure_valid_token = AsyncMock(return_value="test-token")
        p._tools_anthropic = []
        p._tool_map = {}
        tools = _make_test_tools()
        p.init_tools(tools, ["test_say"])
        return p

    @pytest.fixture
    def config(self):
        from providers.base import ProviderConfig
        return ProviderConfig(model="claude-haiku-4-5", system_prompt="You are a test bot.")

    @pytest.mark.asyncio
    async def test_simple_text_response(self, provider, config):
        """LLM returns text only — no tool calls."""
        mock_response = _make_response(
            [_make_text_block("Greetings, traveler!")],
            stop_reason="end_turn",
            tokens_in=150, tokens_out=30,
        )
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_build_client", return_value=mock_client):
            events = await _collect_events(provider, "Hello bot", config)

        narratives = [e for e in events if e.type == EventType.NARRATIVE]
        usages = [e for e in events if e.type == EventType.USAGE]

        assert len(narratives) == 1
        assert narratives[0].data["text"] == "Greetings, traveler!"
        assert len(usages) == 1
        assert usages[0].data["tokens_in"] == 150
        assert usages[0].data["tokens_out"] == 30

    @pytest.mark.asyncio
    async def test_tool_call_and_followup(self, provider, config):
        """LLM calls a tool, gets result, then responds with text."""
        # Round 1: LLM calls test_say tool
        tool_block = _make_tool_use_block(
            "test_say", {"bot_guid": 1234, "message": "Aye, hello!"}
        )
        round1 = _make_response(
            [tool_block], stop_reason="tool_use", tokens_in=200, tokens_out=40,
        )

        # Round 2: LLM produces final text
        round2 = _make_response(
            [_make_text_block("I greeted the traveler.")],
            stop_reason="end_turn", tokens_in=250, tokens_out=20,
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[round1, round2])

        with patch.object(provider, "_build_client", return_value=mock_client):
            events = await _collect_events(provider, "Hello bot", config)

        tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
        narratives = [e for e in events if e.type == EventType.NARRATIVE]
        usages = [e for e in events if e.type == EventType.USAGE]

        assert len(tool_calls) == 1
        assert tool_calls[0].data["name"] == "test_say"
        assert len(narratives) == 1
        assert narratives[0].data["text"] == "I greeted the traveler."
        assert usages[0].data["tokens_in"] == 450  # 200 + 250
        assert usages[0].data["tokens_out"] == 60   # 40 + 20

    @pytest.mark.asyncio
    async def test_tool_result_passed_back(self, provider, config):
        """Verify the tool result is appended to messages correctly."""
        tool_block = _make_tool_use_block(
            "test_say", {"bot_guid": 1, "message": "Hi"}
        )
        round1 = _make_response(
            [tool_block], stop_reason="tool_use", tokens_in=100, tokens_out=20,
        )
        round2 = _make_response(
            [_make_text_block("Done")], stop_reason="end_turn",
            tokens_in=100, tokens_out=10,
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[round1, round2])

        with patch.object(provider, "_build_client", return_value=mock_client):
            await _collect_events(provider, "test", config)

        # Check the second API call included the tool result in messages
        second_call = mock_client.messages.create.call_args_list[1]
        messages = second_call.kwargs["messages"]

        # Find the tool_result message (user turn after the assistant tool_use)
        tool_result_msg = next(
            m for m in messages
            if m["role"] == "user" and isinstance(m["content"], list)
            and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in m["content"])
        )
        tool_result = tool_result_msg["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "toolu_01"
        assert "Said: Hi" in tool_result["content"]

    @pytest.mark.asyncio
    async def test_unknown_tool_handled(self, provider, config):
        """LLM calls a tool that doesn't exist — should not crash."""
        tool_block = _make_tool_use_block(
            "nonexistent_tool", {"foo": "bar"}
        )
        round1 = _make_response(
            [tool_block], stop_reason="tool_use", tokens_in=100, tokens_out=20,
        )
        round2 = _make_response(
            [_make_text_block("Hmm")], stop_reason="end_turn",
            tokens_in=100, tokens_out=10,
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[round1, round2])

        with patch.object(provider, "_build_client", return_value=mock_client):
            events = await _collect_events(provider, "test", config)

        # Should still complete without errors
        errors = [e for e in events if e.type == EventType.ERROR]
        assert len(errors) == 0
        # The tool result should contain "Unknown tool"
        second_call = mock_client.messages.create.call_args_list[1]
        tool_result = second_call.kwargs["messages"][2]["content"][0]
        assert "Unknown tool" in tool_result["content"]

    @pytest.mark.asyncio
    async def test_max_tool_rounds_safety(self, provider, config):
        """Agent loop stops after MAX_TOOL_ROUNDS even if LLM keeps calling tools."""
        tool_block = _make_tool_use_block(
            "test_say", {"bot_guid": 1, "message": "loop"}
        )
        # Every round returns a tool call
        endless_response = _make_response(
            [tool_block], stop_reason="tool_use", tokens_in=50, tokens_out=10,
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=endless_response)

        with patch.object(provider, "_build_client", return_value=mock_client):
            events = await _collect_events(provider, "test", config)

        tool_calls = [e for e in events if e.type == EventType.TOOL_CALL]
        assert len(tool_calls) == 5  # MAX_TOOL_ROUNDS

    @pytest.mark.asyncio
    async def test_auth_error_yields_error_event(self, provider, config):
        """AuthenticationError triggers refresh and yields ERROR event."""
        import anthropic as anthropic_mod

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {}
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic_mod.AuthenticationError(
                message="Invalid token",
                response=mock_response,
                body={},
            )
        )
        provider.auth.refresh = AsyncMock(return_value=False)

        with patch.object(provider, "_build_client", return_value=mock_client):
            events = await _collect_events(provider, "test", config)

        errors = [e for e in events if e.type == EventType.ERROR]
        assert len(errors) == 1
        assert "Auth failed" in errors[0].data["text"]

    @pytest.mark.asyncio
    async def test_no_credentials_yields_error(self, provider, config):
        """No OAuth token and no API key yields ERROR event."""
        provider.auth.ensure_valid_token = AsyncMock(return_value=None)

        with patch("providers.claude.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            events = await _collect_events(provider, "test", config)

        errors = [e for e in events if e.type == EventType.ERROR]
        assert len(errors) == 1
        assert "No Anthropic credentials" in errors[0].data["text"]


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
