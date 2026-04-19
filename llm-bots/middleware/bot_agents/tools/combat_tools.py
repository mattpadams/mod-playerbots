"""Combat and strategy tools — per-bot, ``bot_guid`` baked into closures."""
from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType


def create_combat_tools(bot_guid: int, executor: CommandExecutor) -> list:

    @tool("change_strategy",
          "Change your combat behavior. Use + to add, - to remove. "
          "Examples: '+tank assist', '-ranged,+close', '+heal'.",
          {"strategy": str})
    async def change_strategy(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.SET_STRATEGY, bot_guid=bot_guid,
            payload={"strategy": args["strategy"]},
        ))
        return {"content": [{"type": "text",
                             "text": f"Strategy changed to: {args['strategy']}"}]}

    @tool("follow_player", "Follow a specific player, staying close to them.",
          {"player_name": str})
    async def follow_player(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.FOLLOW_PLAYER, bot_guid=bot_guid,
            payload={"player_name": args["player_name"]},
        ))
        return {"content": [{"type": "text",
                             "text": f"Now following {args['player_name']}"}]}

    @tool("stay", "Stop moving and hold your current position.", {})
    async def stay(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.STAY, bot_guid=bot_guid,
        ))
        return {"content": [{"type": "text", "text": "Holding position."}]}

    @tool("flee", "Run away from combat. Use when the fight is unwinnable.",
          {})
    async def flee(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.EXECUTE_ACTION, bot_guid=bot_guid,
            payload={"action": "flee"},
        ))
        return {"content": [{"type": "text", "text": "Fleeing from combat!"}]}

    @tool("invite_to_group", "Invite a player to join your group or party.",
          {"player_name": str})
    async def invite_to_group(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.INVITE_PLAYER, bot_guid=bot_guid,
            payload={"player_name": args["player_name"]},
        ))
        return {"content": [{"type": "text",
                             "text": f"Invited {args['player_name']} to group."}]}

    @tool("accept_group_invite", "Accept a pending group invitation.", {})
    async def accept_group_invite(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.ACCEPT_INVITE, bot_guid=bot_guid,
        ))
        return {"content": [{"type": "text", "text": "Accepted group invite."}]}

    @tool("leave_group", "Leave your current party or raid group.", {})
    async def leave_group(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.LEAVE_GROUP, bot_guid=bot_guid,
        ))
        return {"content": [{"type": "text", "text": "Left the group."}]}

    return [
        change_strategy, follow_player, stay, flee,
        invite_to_group, accept_group_invite, leave_group,
    ]
