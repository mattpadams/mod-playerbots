"""Shared tool server for all bot agents.

Created once at startup, holds all game tool definitions.  Each tool
takes ``bot_guid`` as an input parameter so the same set of tools
serves every bot.
"""

from __future__ import annotations

import structlog

from core.bot_registry import BotRegistry
from core.command_executor import CommandExecutor
from memory.memory_manager import MemoryManager

from bot_agents.tools.chat_tools import create_chat_tools
from bot_agents.tools.combat_tools import create_combat_tools
from bot_agents.tools.memory_tools import create_memory_tools
from bot_agents.tools.party_tools import create_party_tools
from bot_agents.tools.quest_tools import create_quest_tools
from bot_agents.tools.raid_tools import create_raid_tools
from bot_agents.tools.rpg_tools import create_rpg_tools
from bot_agents.tools.trade_tools import create_trade_tools

logger = structlog.get_logger()


class ToolServer:
    """Holds all provider-agnostic tool definitions for the game.

    Tools close over shared services (executor, memory_manager) but
    receive per-bot context (bot_guid) as an input parameter from the LLM.
    """

    def __init__(
        self,
        executor: CommandExecutor,
        memory_manager: MemoryManager,
        registry: BotRegistry | None = None,
    ) -> None:
        self.tools: list = []
        self.tool_names: list[str] = []

        # Build all tools once, closing over shared services
        self.tools.extend(create_chat_tools(executor))
        self.tools.extend(create_combat_tools(executor))
        self.tools.extend(create_raid_tools(executor))
        self.tools.extend(create_party_tools(executor))
        self.tools.extend(
            create_quest_tools(executor, memory=memory_manager, registry=registry)
        )
        self.tools.extend(create_trade_tools(executor))
        self.tools.extend(create_rpg_tools(executor))
        self.tools.extend(create_memory_tools(memory_manager))

        self.tool_names = [t.tool_name for t in self.tools]

        logger.info(
            "tool_server.initialized",
            tool_count=len(self.tools),
            tool_names=self.tool_names,
        )
