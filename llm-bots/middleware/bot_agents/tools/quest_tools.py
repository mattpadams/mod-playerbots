"""Quest and interaction primitives — M4.

Generic building blocks the LLM composes to drive quests the rule
engine can't script (class quests, escort quests, unusual objectives
like 'Cast Lesser Heal on Henze Faulk').

The quest objective text appears in the ``[PARTY STATE]`` prompt
section, so the LLM reads what's needed and picks the right tool.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType
from memory.schemas import MemoryType
from providers.tool_adapter import tool

if TYPE_CHECKING:
    from core.bot_registry import BotRegistry
    from memory.memory_manager import MemoryManager


def create_quest_tools(
    executor: CommandExecutor,
    memory: "MemoryManager | None" = None,
    registry: "BotRegistry | None" = None,
) -> list:
    """Create quest / interaction tools, closing over the shared executor.

    When ``memory`` and ``registry`` are provided, accept / share /
    drop calls also write a high-importance memory entry so the LLM
    can reason about quest progress across sessions (Story 4.5).
    """

    async def _remember(bot_guid: int, content: str) -> None:
        if memory is None or registry is None:
            return
        profile = registry.get(bot_guid)
        if profile is None:
            return
        await memory.store_explicit(
            bot_guid=bot_guid,
            bot_name=profile.name,
            content=content,
            memory_type=MemoryType.QUEST_OUTCOME,
            importance=0.85,
        )

    @tool(
        name="accept_quest",
        description=(
            "Accept a quest by link from the nearest quest giver you "
            "are currently talking to. The rule engine handles most "
            "quest acceptance automatically; call this for quests you "
            "want to pick up proactively."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "quest_link": {
                    "type": "string",
                    "description": "Quest link or '*' to accept all available.",
                },
            },
            "required": ["bot_guid", "quest_link"],
        },
    )
    async def accept_quest(args):
        link = args["quest_link"]
        await executor.execute(
            BotCommand(
                command_type=CommandType.ACCEPT_QUEST,
                bot_guid=args["bot_guid"],
                payload={"quest_link": link},
            )
        )
        await _remember(args["bot_guid"], f"Accepted quest {link}.")
        return {
            "content": [
                {"type": "text", "text": f"Accepting quest {link}."}
            ]
        }

    @tool(
        name="share_quest",
        description=(
            "Share a quest with your party. Use when a party member "
            "is missing a quest you just picked up."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "quest_link": {"type": "string"},
            },
            "required": ["bot_guid", "quest_link"],
        },
    )
    async def share_quest(args):
        await executor.execute(
            BotCommand(
                command_type=CommandType.SHARE_QUEST,
                bot_guid=args["bot_guid"],
                payload={"item_link": args["quest_link"]},
            )
        )
        await _remember(
            args["bot_guid"], f"Shared quest {args['quest_link']} with party."
        )
        return {
            "content": [
                {"type": "text", "text": f"Sharing quest {args['quest_link']}."}
            ]
        }

    @tool(
        name="drop_quest",
        description=(
            "Abandon a quest from your quest log. Use when a quest is "
            "too high level, not worth completing, or blocking a slot "
            "you need for a new pickup."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "quest_link_or_title": {
                    "type": "string",
                    "description": (
                        "Quest link or a substring of the quest title."
                    ),
                },
            },
            "required": ["bot_guid", "quest_link_or_title"],
        },
    )
    async def drop_quest(args):
        target = args["quest_link_or_title"]
        await executor.execute(
            BotCommand(
                command_type=CommandType.DROP_QUEST,
                bot_guid=args["bot_guid"],
                payload={"quest_link": target},
            )
        )
        await _remember(args["bot_guid"], f"Dropped quest {target}.")
        return {
            "content": [
                {"type": "text", "text": f"Dropping quest {target}."}
            ]
        }

    @tool(
        name="list_quests",
        description=(
            "List quests in your quest log. Filter by 'all', 'completed', "
            "or 'incompleted'. Use to check progress before visiting a "
            "quest giver or deciding to drop."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "filter": {
                    "type": "string",
                    "enum": ["all", "completed", "incompleted"],
                    "description": "Quest log filter. Default: all.",
                },
            },
            "required": ["bot_guid"],
        },
    )
    async def list_quests(args):
        filt = args.get("filter", "all")
        action = "quests" if filt == "all" else f"quests {filt}"
        await executor.execute(
            BotCommand(
                command_type=CommandType.EXECUTE_ACTION,
                bot_guid=args["bot_guid"],
                payload={"action": action},
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Listing {filt} quests."}
            ]
        }

    @tool(
        name="cast_spell_on_target",
        description=(
            "Cast a specific spell on a named target. Use for quest "
            "objectives that require casting (e.g. heal an injured "
            "NPC, cleanse a cursed item). The target must be visible "
            "and within range."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "spell": {"type": "string", "description": "Spell name or id."},
                "target": {"type": "string", "description": "Target name."},
            },
            "required": ["bot_guid", "spell", "target"],
        },
    )
    async def cast_spell_on_target(args):
        await executor.execute(
            BotCommand(
                command_type=CommandType.CAST_SPELL,
                bot_guid=args["bot_guid"],
                payload={"spell": args["spell"], "target": args["target"]},
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Casting {args['spell']} on {args['target']}."}
            ]
        }

    @tool(
        name="use_item",
        description=(
            "Use an item from your inventory, optionally on a target. "
            "Use for quest items (e.g. activate a totem, apply an "
            "elixir to an object)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "item_link": {"type": "string"},
                "target": {
                    "type": "string",
                    "description": "Optional target name.",
                },
            },
            "required": ["bot_guid", "item_link"],
        },
    )
    async def use_item(args):
        await executor.execute(
            BotCommand(
                command_type=CommandType.USE_ITEM,
                bot_guid=args["bot_guid"],
                payload={
                    "item_link": args["item_link"],
                    "target": args.get("target", ""),
                },
            )
        )
        return {"content": [{"type": "text", "text": f"Using {args['item_link']}."}]}

    @tool(
        name="interact_with_object",
        description=(
            "Walk to and interact with a named world object (chest, "
            "lever, altar, container). Use for quest objectives that "
            "require clicking something in the world."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "object_name": {"type": "string"},
            },
            "required": ["bot_guid", "object_name"],
        },
    )
    async def interact_with_object(args):
        await executor.execute(
            BotCommand(
                command_type=CommandType.INTERACT_OBJECT,
                bot_guid=args["bot_guid"],
                payload={"object_name": args["object_name"]},
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Interacting with {args['object_name']}."}
            ]
        }

    @tool(
        name="talk_to_npc",
        description=(
            "Walk to and open gossip with a named NPC. Triggers quest "
            "turn-in dialog when appropriate."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "npc_name": {"type": "string"},
            },
            "required": ["bot_guid", "npc_name"],
        },
    )
    async def talk_to_npc(args):
        await executor.execute(
            BotCommand(
                command_type=CommandType.TALK_TO_NPC,
                bot_guid=args["bot_guid"],
                payload={"npc_name": args["npc_name"]},
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Talking to {args['npc_name']}."}
            ]
        }

    @tool(
        name="craft_item",
        description=(
            "Craft an item using your profession. Use when a party "
            "member asks for consumables (pots, flasks, bandages, "
            "bags) and you have the relevant profession and materials."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "item_link": {"type": "string"},
                "count": {"type": "integer", "description": "Stack count to craft."},
            },
            "required": ["bot_guid", "item_link"],
        },
    )
    async def craft_item(args):
        await executor.execute(
            BotCommand(
                command_type=CommandType.CRAFT_ITEM,
                bot_guid=args["bot_guid"],
                payload={
                    "item_link": args["item_link"],
                    "count": args.get("count", 1),
                },
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Crafting {args['item_link']}."}
            ]
        }

    return [
        accept_quest,
        drop_quest,
        list_quests,
        share_quest,
        cast_spell_on_target,
        use_item,
        interact_with_object,
        talk_to_npc,
        craft_item,
    ]
