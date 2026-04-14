"""Combat and strategy tools — shared MCP server, bot_guid as input param."""

from __future__ import annotations

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType
from providers.tool_adapter import tool


def create_combat_tools(executor: CommandExecutor) -> list:
    """Create combat tools that close over the shared executor."""

    @tool(
        name="change_strategy",
        description=(
            "Change your combat behavior. Use + to add, - to remove. "
            "Examples: '+tank assist', '-ranged,+close', '+heal'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "strategy": {"type": "string", "description": "Strategy change expression"},
            },
            "required": ["bot_guid", "strategy"],
        },
    )
    async def change_strategy(args):
        cmd = BotCommand(
            command_type=CommandType.SET_STRATEGY, bot_guid=args["bot_guid"],
            payload={"strategy": args["strategy"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"Strategy changed to: {args['strategy']}"}]}

    @tool(
        name="follow_player",
        description="Follow a specific player, staying close to them.",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "player_name": {"type": "string"},
            },
            "required": ["bot_guid", "player_name"],
        },
    )
    async def follow_player(args):
        cmd = BotCommand(
            command_type=CommandType.FOLLOW_PLAYER, bot_guid=args["bot_guid"],
            payload={"player_name": args["player_name"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"Now following {args['player_name']}"}]}

    @tool(
        name="stay",
        description="Stop moving and hold your current position.",
        input_schema={
            "type": "object",
            "properties": {"bot_guid": {"type": "integer"}},
            "required": ["bot_guid"],
        },
    )
    async def stay(args):
        cmd = BotCommand(command_type=CommandType.STAY, bot_guid=args["bot_guid"])
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": "Holding position."}]}

    @tool(
        name="flee",
        description="Run away from combat. Use when the fight is unwinnable.",
        input_schema={
            "type": "object",
            "properties": {"bot_guid": {"type": "integer"}},
            "required": ["bot_guid"],
        },
    )
    async def flee(args):
        cmd = BotCommand(
            command_type=CommandType.EXECUTE_ACTION, bot_guid=args["bot_guid"],
            payload={"action": "flee"},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": "Fleeing from combat!"}]}

    @tool(
        name="invite_to_group",
        description="Invite a player to join your group or party.",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "player_name": {"type": "string"},
            },
            "required": ["bot_guid", "player_name"],
        },
    )
    async def invite_to_group(args):
        cmd = BotCommand(
            command_type=CommandType.INVITE_PLAYER, bot_guid=args["bot_guid"],
            payload={"player_name": args["player_name"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"Invited {args['player_name']} to group."}]}

    @tool(
        name="accept_group_invite",
        description="Accept a pending group invitation.",
        input_schema={
            "type": "object",
            "properties": {"bot_guid": {"type": "integer"}},
            "required": ["bot_guid"],
        },
    )
    async def accept_group_invite(args):
        cmd = BotCommand(command_type=CommandType.ACCEPT_INVITE, bot_guid=args["bot_guid"])
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": "Accepted group invite."}]}

    @tool(
        name="leave_group",
        description="Leave your current party or raid group.",
        input_schema={
            "type": "object",
            "properties": {"bot_guid": {"type": "integer"}},
            "required": ["bot_guid"],
        },
    )
    async def leave_group(args):
        cmd = BotCommand(command_type=CommandType.LEAVE_GROUP, bot_guid=args["bot_guid"])
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": "Left the group."}]}

    return [change_strategy, follow_player, stay, flee, invite_to_group, accept_group_invite, leave_group]
