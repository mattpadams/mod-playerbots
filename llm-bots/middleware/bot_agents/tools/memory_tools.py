"""Memory tools — shared MCP server, bot_guid as input param."""

from __future__ import annotations

from memory.memory_manager import MemoryManager
from memory.schemas import MemoryType
from providers.tool_adapter import tool


def create_memory_tools(memory_manager: MemoryManager) -> list:
    """Create memory tools that close over the shared memory manager."""

    @tool(
        name="remember_this",
        description=(
            "Store something important to your long-term memory. "
            "Use for facts about players, events, promises, or lessons learned."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "content": {"type": "string", "description": "What to remember"},
                "memory_type": {
                    "type": "string",
                    "enum": ["conversation", "relationship", "world_event", "personality"],
                },
            },
            "required": ["bot_guid", "content"],
        },
    )
    async def remember_this(args):
        try:
            mt = MemoryType(args.get("memory_type", "conversation"))
        except ValueError:
            mt = MemoryType.CONVERSATION

        await memory_manager.store_explicit(
            bot_guid=args["bot_guid"], bot_name="",
            content=args["content"], memory_type=mt,
        )
        return {"content": [{"type": "text", "text": f"Remembered: {args['content']}"}]}

    @tool(
        name="recall",
        description="Search your long-term memory for information about a topic, player, or event.",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "query": {"type": "string", "description": "What to search for"},
            },
            "required": ["bot_guid", "query"],
        },
    )
    async def recall(args):
        memories = await memory_manager.get_context(
            bot_guid=args["bot_guid"], situation_query=args["query"], limit=5,
        )
        if not memories:
            return {"content": [{"type": "text", "text": "I don't remember anything about that."}]}
        text = "Memories:\n" + "\n".join(f"- {m}" for m in memories)
        return {"content": [{"type": "text", "text": text}]}

    return [remember_this, recall]
