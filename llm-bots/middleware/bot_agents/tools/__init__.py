"""Per-bot tool factories.

Each ``create_*_tools(bot_guid, ...)`` returns a list of SDK ``@tool``
functions that close over the bot's GUID. Aggregated into a single
in-process MCP server per bot in :mod:`bot_agents.bot_agent`.
"""
from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from core.command_executor import CommandExecutor
from memory.memory_manager import MemoryManager

from bot_agents.tools.chat_tools import create_chat_tools
from bot_agents.tools.combat_tools import create_combat_tools
from bot_agents.tools.memory_tools import create_memory_tools

MCP_SERVER_NAME = "bot"


def build_bot_mcp(
    bot_guid: int, bot_name: str,
    executor: CommandExecutor, memory_manager: MemoryManager,
) -> tuple[object, list[str]]:
    """Build the per-bot MCP server and matching ``allowed_tools`` list."""
    tools = [
        *create_chat_tools(bot_guid, executor),
        *create_combat_tools(bot_guid, executor),
        *create_memory_tools(bot_guid, bot_name, memory_manager),
    ]
    server = create_sdk_mcp_server(name=MCP_SERVER_NAME, tools=tools)
    allowed = [f"mcp__{MCP_SERVER_NAME}__{t.name}" for t in tools]
    return server, allowed


__all__ = ["build_bot_mcp", "MCP_SERVER_NAME"]
