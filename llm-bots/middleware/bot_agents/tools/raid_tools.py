"""Raid coordination tools — M3 additions.

These tools are deliberately thin wrappers that compose over existing
``PARTY_CHAT`` / ``RAID_CHAT`` / ``EXECUTE_ACTION`` / ``SET_STRATEGY``
commands. No new ``CommandType`` enums are needed — each tool just
constructs the correct payload string.

The value of these as named tools (rather than letting the LLM call
``party_chat`` directly) is discoverability: the LLM sees a clear
"focus_target" function in its tool list and uses it situationally.
"""
from __future__ import annotations

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType
from providers.tool_adapter import tool

# Cap LLM-generated chat strings before broadcasting in-game.
_MAX_CHAT_LEN = 100


def _truncate(s: str) -> str:
    return s if len(s) <= _MAX_CHAT_LEN else s[: _MAX_CHAT_LEN - 1] + "…"


def create_raid_tools(executor: CommandExecutor) -> list:
    """Create raid coordination tools, closing over the shared executor."""

    @tool(
        name="focus_target",
        description=(
            "Call the group to focus fire on a specific target. "
            "Posts a party-chat callout and switches your stance to assist DPS. "
            "Use to coordinate burst on priority adds or a new boss phase."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "target_name": {
                    "type": "string",
                    "description": "Name of the enemy to focus.",
                },
            },
            "required": ["bot_guid", "target_name"],
        },
    )
    async def focus_target(args):
        target = _truncate(args["target_name"])
        await executor.execute(
            BotCommand(
                command_type=CommandType.PARTY_CHAT,
                bot_guid=args["bot_guid"],
                payload={"message": f"Focus {target}!"},
            )
        )
        await executor.execute(
            BotCommand(
                command_type=CommandType.SET_STRATEGY,
                bot_guid=args["bot_guid"],
                payload={"strategy": "+dps assist"},
            )
        )
        return {"content": [{"type": "text", "text": f"Calling focus on {target}."}]}

    @tool(
        name="mark_target",
        description=(
            "Place a raid marker on a target. Skull = kill first, Cross = "
            "crowd control. Marker is communicated via party chat."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "target_name": {"type": "string"},
                "marker": {
                    "type": "string",
                    "enum": [
                        "skull", "cross", "square", "moon",
                        "triangle", "diamond", "circle", "star",
                    ],
                    "description": "Raid marker icon.",
                },
            },
            "required": ["bot_guid", "target_name", "marker"],
        },
    )
    async def mark_target(args):
        target = _truncate(args["target_name"])
        marker = args["marker"]
        # Mod-playerbots accepts `mark <icon> <target>` via the action path.
        await executor.execute(
            BotCommand(
                command_type=CommandType.EXECUTE_ACTION,
                bot_guid=args["bot_guid"],
                payload={"action": f"mark {marker} {target}"},
            )
        )
        await executor.execute(
            BotCommand(
                command_type=CommandType.PARTY_CHAT,
                bot_guid=args["bot_guid"],
                payload={"message": f"{{{marker}}} on {target}"},
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Marked {target} with {marker}."}
            ]
        }

    @tool(
        name="assist_player",
        description=(
            "Switch to attacking the same target as another player. "
            "Useful for matching the tank's target or following kill order."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "player_name": {
                    "type": "string",
                    "description": "Name of the player to assist.",
                },
            },
            "required": ["bot_guid", "player_name"],
        },
    )
    async def assist_player(args):
        player = _truncate(args["player_name"])
        await executor.execute(
            BotCommand(
                command_type=CommandType.EXECUTE_ACTION,
                bot_guid=args["bot_guid"],
                payload={"action": f"assist {player}"},
            )
        )
        return {"content": [{"type": "text", "text": f"Assisting {player}."}]}

    @tool(
        name="request_heal",
        description=(
            "Verbally call for a heal in party chat. Use only when health "
            "is genuinely low — otherwise it becomes spam."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "urgency": {
                    "type": "string",
                    "enum": ["low", "medium", "critical"],
                    "description": "How urgent the heal request is.",
                },
            },
            "required": ["bot_guid", "urgency"],
        },
    )
    async def request_heal(args):
        urgency = args["urgency"]
        messages = {
            "low": "Could use a heal when you get a chance.",
            "medium": "Healer, I need heals!",
            "critical": "HEALS NOW! Going down!",
        }
        msg = messages.get(urgency, "Need heals!")
        await executor.execute(
            BotCommand(
                command_type=CommandType.PARTY_CHAT,
                bot_guid=args["bot_guid"],
                payload={"message": msg},
            )
        )
        return {
            "content": [
                {"type": "text", "text": f"Called for {urgency} heals."}
            ]
        }

    @tool(
        name="call_out_mechanic",
        description=(
            "Warn the party about a dangerous boss mechanic. Examples: "
            "'Bone Storm! Spread out!', 'Adds incoming from the north', "
            "'Tank, save Shield Wall for next phase'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "message": {
                    "type": "string",
                    "description": "Short callout, ideally under 100 characters.",
                },
            },
            "required": ["bot_guid", "message"],
        },
    )
    async def call_out_mechanic(args):
        prefix = "[!] "
        # Truncate so the final prefixed message fits within _MAX_CHAT_LEN.
        msg = args["message"]
        if len(msg) > _MAX_CHAT_LEN - len(prefix):
            msg = msg[: _MAX_CHAT_LEN - len(prefix) - 1] + "…"
        full = prefix + msg
        await executor.execute(
            BotCommand(
                command_type=CommandType.PARTY_CHAT,
                bot_guid=args["bot_guid"],
                payload={"message": full},
            )
        )
        return {"content": [{"type": "text", "text": f"Called out: {msg}"}]}

    return [
        focus_target,
        mark_target,
        assist_player,
        request_heal,
        call_out_mechanic,
    ]
