"""Milestone 1: Chat MVP smoke tests (Claude Agent SDK).

Run with:
    cd llm-bots/middleware
    python -m pytest tests/test_m1_chat_mvp.py -v

Tests the per-bot session architecture: tool factories close over
``bot_guid``, the provider session aggregates SDK messages into an
``AgentResult``, and ``BotAgent`` wires the two together.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot_agents.tools import MCP_SERVER_NAME, build_bot_mcp
from bot_agents.tools.chat_tools import create_chat_tools
from bot_agents.tools.combat_tools import create_combat_tools
from bot_agents.tools.memory_tools import create_memory_tools
from game.commands import CommandType
from providers.base import AgentResult


# ---------------------------------------------------------------------------
# Tool factory tests — bot_guid is baked into the closure (no LLM param)
# ---------------------------------------------------------------------------

class TestToolClosures:
    @pytest.mark.asyncio
    async def test_say_routes_to_correct_bot(self):
        executor = MagicMock()
        executor.execute = AsyncMock()
        tools = create_chat_tools(bot_guid=4242, executor=executor)
        say = next(t for t in tools if t.name == "say")

        await say({"message": "hello"})

        executor.execute.assert_awaited_once()
        cmd = executor.execute.await_args.args[0]
        assert cmd.bot_guid == 4242
        assert cmd.command_type == CommandType.SAY
        assert cmd.payload == {"message": "hello"}

    @pytest.mark.asyncio
    async def test_two_bots_dont_share_guid(self):
        executor = MagicMock()
        executor.execute = AsyncMock()
        tools_a = create_chat_tools(1, executor)
        tools_b = create_chat_tools(2, executor)

        await next(t for t in tools_a if t.name == "say")({"message": "A"})
        await next(t for t in tools_b if t.name == "say")({"message": "B"})

        guids = [c.args[0].bot_guid for c in executor.execute.await_args_list]
        assert guids == [1, 2]

    @pytest.mark.asyncio
    async def test_combat_tool_no_args(self):
        executor = MagicMock()
        executor.execute = AsyncMock()
        stay = next(t for t in create_combat_tools(7, executor) if t.name == "stay")

        await stay({})

        cmd = executor.execute.await_args.args[0]
        assert cmd.bot_guid == 7
        assert cmd.command_type == CommandType.STAY

    @pytest.mark.asyncio
    async def test_memory_recall_uses_bot_guid(self):
        memory = MagicMock()
        memory.get_context = AsyncMock(return_value=["a memory"])
        recall = next(
            t for t in create_memory_tools(99, "Bob", memory) if t.name == "recall"
        )

        result = await recall({"query": "the king"})

        memory.get_context.assert_awaited_once()
        assert memory.get_context.await_args.kwargs["bot_guid"] == 99
        assert "a memory" in result["content"][0]["text"]


class TestBuildBotMcp:
    def test_returns_server_and_allowed_tool_names(self):
        executor = MagicMock()
        memory = MagicMock()
        server, allowed = build_bot_mcp(
            bot_guid=1, bot_name="Bob",
            executor=executor, memory_manager=memory,
        )
        assert server is not None
        prefix = f"mcp__{MCP_SERVER_NAME}__"
        assert all(name.startswith(prefix) for name in allowed)
        assert f"{prefix}say" in allowed
        assert f"{prefix}recall" in allowed
        assert f"{prefix}change_strategy" in allowed


# ---------------------------------------------------------------------------
# ClaudeSession — drains SDK messages into AgentResult
# ---------------------------------------------------------------------------

class TestClaudeSession:
    @pytest.fixture
    def session(self):
        from providers.claude import ClaudeSession
        client = MagicMock()
        client.query = AsyncMock()
        return ClaudeSession(client), client

    @pytest.mark.asyncio
    async def test_drains_text_and_tool_calls_and_usage(self, session):
        # Use duck-typed mocks so the test isn't coupled to the SDK's
        # internal dataclass constructors. ClaudeSession dispatches via
        # isinstance() against the real SDK types, so register the spec.
        from claude_agent_sdk.types import (
            AssistantMessage, ResultMessage, TextBlock, ToolUseBlock,
        )
        sess, client = session

        text_block = MagicMock(spec=TextBlock)
        text_block.text = "Greeted them."
        tool_block = MagicMock(spec=ToolUseBlock)
        tool_block.name = "mcp__bot__say"

        assistant_with_tool = MagicMock(spec=AssistantMessage)
        assistant_with_tool.content = [tool_block]
        assistant_with_text = MagicMock(spec=AssistantMessage)
        assistant_with_text.content = [text_block]

        result_msg = MagicMock(spec=ResultMessage)
        result_msg.usage = {
            "input_tokens": 100, "output_tokens": 20,
            "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 10,
        }
        result_msg.total_cost_usd = 0.001

        msgs = [assistant_with_tool, assistant_with_text, result_msg]

        async def gen():
            for m in msgs:
                yield m
        client.receive_response = MagicMock(return_value=gen())

        result = await sess.send("Say hi")

        assert result.text == "Greeted them."
        assert result.tool_calls == ["mcp__bot__say"]
        assert result.tokens_in == 100
        assert result.tokens_out == 20
        assert result.cache_read_tokens == 50
        assert result.cache_creation_tokens == 10
        assert result.cost_usd == 0.001
        assert result.error is None

    @pytest.mark.asyncio
    async def test_exception_captured_in_error(self, session):
        sess, client = session
        client.query = AsyncMock(side_effect=RuntimeError("boom"))

        result = await sess.send("hi")

        assert result.error == "boom"
        assert result.text == ""


# ---------------------------------------------------------------------------
# BotAgent — wires session + tools + cost controller
# ---------------------------------------------------------------------------

class TestBotAgent:
    @pytest.fixture
    def deps(self):
        from core.bot_registry import BotProfile
        from scheduler.cost_controller import CostController

        profile = BotProfile(guid=1, name="Bob", personality="gruff_warrior")
        executor = MagicMock()
        executor.execute = AsyncMock()
        memory = MagicMock()
        memory.maybe_store_event = AsyncMock()
        memory.get_context = AsyncMock(return_value=[])
        cost = CostController()
        provider = MagicMock()
        session = MagicMock()
        session.send = AsyncMock(return_value=AgentResult(
            text="ok", tool_calls=["mcp__bot__say"],
            tokens_in=10, tokens_out=5, cost_usd=0.0001,
        ))
        session.aclose = AsyncMock()
        provider.create_session = AsyncMock(return_value=session)
        return profile, executor, memory, cost, provider, session

    @pytest.mark.asyncio
    async def test_lifecycle_opens_and_closes_session(self, deps):
        from bot_agents.bot_agent import BotAgent
        profile, executor, memory, cost, provider, session = deps

        agent = BotAgent(
            profile=profile, executor=executor, memory_manager=memory,
            cost_controller=cost, provider=provider,
            default_model="claude-haiku-4-5",
        )
        await agent.start()
        provider.create_session.assert_awaited_once()
        kwargs = provider.create_session.await_args.kwargs
        assert kwargs["model"] == "claude-haiku-4-5"
        assert MCP_SERVER_NAME in kwargs["mcp_servers"]
        assert any("say" in t for t in kwargs["allowed_tools"])

        await agent.stop()
        session.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_event_invokes_session_and_records_cost(self, deps):
        from bot_agents.bot_agent import BotAgent
        from game.events import ChatReceivedEvent
        profile, executor, memory, cost, provider, session = deps

        agent = BotAgent(
            profile=profile, executor=executor, memory_manager=memory,
            cost_controller=cost, provider=provider,
            default_model="claude-haiku-4-5",
        )
        await agent.start()

        event = ChatReceivedEvent(
            bot_guid=1, bot_name="Bob",
            sender_name="Alice", channel="say", message="hello",
        )
        trace = await agent.handle_event(event)

        session.send.assert_awaited_once()
        # Player chat is wrapped in untrusted envelope (defense in depth)
        prompt = session.send.await_args.args[0]
        assert "PLAYER_CHAT" in prompt
        assert "Alice" in prompt
        assert trace is not None
        assert trace.tool_calls == ["mcp__bot__say"]
        assert trace.tokens_in == 10
        assert profile.total_llm_calls == 1

    @pytest.mark.asyncio
    async def test_handle_event_without_session_is_safe(self, deps):
        from bot_agents.bot_agent import BotAgent
        from game.events import IdleTickEvent
        profile, executor, memory, cost, provider, _ = deps

        agent = BotAgent(
            profile=profile, executor=executor, memory_manager=memory,
            cost_controller=cost, provider=provider,
            default_model="claude-haiku-4-5",
        )
        # No start() — session is None
        trace = await agent.handle_event(
            IdleTickEvent(bot_guid=1, bot_name="Bob", idle_seconds=30)
        )
        assert trace is None


# ---------------------------------------------------------------------------
# Supervisor priority/filter
# ---------------------------------------------------------------------------

class TestSupervisorPicksBestEvent:
    def test_chat_wins_over_idle(self):
        from bot_agents.agent_supervisor import AgentSupervisor
        from game.events import ChatReceivedEvent, IdleTickEvent

        sup = AgentSupervisor.__new__(AgentSupervisor)
        events = [
            IdleTickEvent(bot_guid=1, bot_name="Bob", idle_seconds=30),
            ChatReceivedEvent(bot_guid=1, bot_name="Bob",
                              sender_name="X", channel="say", message="hi"),
        ]
        best = sup._pick_best_event(events)
        assert best.event_type.value == "chat_received"

    def test_returns_none_when_no_invocation_event(self):
        from bot_agents.agent_supervisor import AgentSupervisor
        from game.events import CombatEndEvent

        sup = AgentSupervisor.__new__(AgentSupervisor)
        events = [CombatEndEvent(bot_guid=1, bot_name="Bob")]
        assert sup._pick_best_event(events) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
