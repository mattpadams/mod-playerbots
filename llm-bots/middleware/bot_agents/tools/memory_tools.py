"""Memory tools — per-bot, ``bot_guid`` baked into closures."""
from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from memory.memory_manager import MemoryManager
from memory.schemas import MemoryType


def create_memory_tools(
    bot_guid: int, bot_name: str, memory_manager: MemoryManager,
) -> list:

    @tool("remember_this",
          "Store something important to your long-term memory. "
          "Use for facts about players, events, promises, or lessons learned.",
          {
              "type": "object",
              "properties": {
                  "content": {"type": "string"},
                  "memory_type": {
                      "type": "string",
                      "enum": ["conversation", "relationship",
                               "world_event", "personality"],
                  },
              },
              "required": ["content"],
          })
    async def remember_this(args: dict[str, Any]) -> dict[str, Any]:
        try:
            mt = MemoryType(args.get("memory_type", "conversation"))
        except ValueError:
            mt = MemoryType.CONVERSATION

        await memory_manager.store_explicit(
            bot_guid=bot_guid, bot_name=bot_name,
            content=args["content"], memory_type=mt,
        )
        return {"content": [{"type": "text",
                             "text": f"Remembered: {args['content']}"}]}

    @tool("recall",
          "Search your long-term memory for information about a topic, "
          "player, or event.",
          {"query": str})
    async def recall(args: dict[str, Any]) -> dict[str, Any]:
        memories = await memory_manager.get_context(
            bot_guid=bot_guid, situation_query=args["query"], limit=5,
        )
        if not memories:
            return {"content": [{"type": "text",
                                 "text": "I don't remember anything about that."}]}
        text = "Memories:\n" + "\n".join(f"- {m}" for m in memories)
        return {"content": [{"type": "text", "text": text}]}

    return [remember_this, recall]
