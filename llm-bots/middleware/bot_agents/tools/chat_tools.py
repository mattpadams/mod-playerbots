"""Chat and emote tools — per-bot, ``bot_guid`` baked into closures."""
from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType


def create_chat_tools(bot_guid: int, executor: CommandExecutor) -> list:
    """Build chat tools that operate on a single bot."""

    @tool("say", "Speak aloud so nearby players and NPCs can hear you.",
          {"message": str})
    async def say(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.SAY, bot_guid=bot_guid,
            payload={"message": args["message"]},
        ))
        return {"content": [{"type": "text",
                             "text": f"You said: {args['message']}"}]}

    @tool("yell", "Yell loudly so players in a wide area can hear you.",
          {"message": str})
    async def yell(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.YELL, bot_guid=bot_guid,
            payload={"message": args["message"]},
        ))
        return {"content": [{"type": "text",
                             "text": f"You yelled: {args['message']}"}]}

    @tool("whisper", "Send a private message to a specific player.",
          {"target_player": str, "message": str})
    async def whisper(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.WHISPER, bot_guid=bot_guid,
            payload={"target_player": args["target_player"],
                     "message": args["message"]},
        ))
        return {"content": [{"type": "text", "text":
            f"You whispered to {args['target_player']}: {args['message']}"}]}

    @tool("party_chat", "Send a message to your party or group.",
          {"message": str})
    async def party_chat(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.PARTY_CHAT, bot_guid=bot_guid,
            payload={"message": args["message"]},
        ))
        return {"content": [{"type": "text",
                             "text": f"You said in party: {args['message']}"}]}

    @tool("guild_chat", "Send a message to your guild.",
          {"message": str})
    async def guild_chat(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.GUILD_CHAT, bot_guid=bot_guid,
            payload={"message": args["message"]},
        ))
        return {"content": [{"type": "text",
                             "text": f"You said in guild: {args['message']}"}]}

    @tool("emote",
          "Perform an in-game emote. Available: wave, bow, laugh, cry, "
          "dance, cheer, sit, kneel, point, roar, salute, flex, shrug, "
          "clap, thank, beg.",
          {"emote_name": str})
    async def emote(args: dict[str, Any]) -> dict[str, Any]:
        await executor.execute(BotCommand(
            command_type=CommandType.EMOTE, bot_guid=bot_guid,
            payload={"emote": args["emote_name"]},
        ))
        return {"content": [{"type": "text",
                             "text": f"You performed: {args['emote_name']}"}]}

    return [say, yell, whisper, party_chat, guild_chat, emote]
