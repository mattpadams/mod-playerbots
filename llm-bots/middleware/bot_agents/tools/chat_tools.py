"""Chat and emote tools — shared MCP server, bot_guid as input param."""

from __future__ import annotations

from core.command_executor import CommandExecutor
from game.commands import BotCommand, CommandType
from providers.tool_adapter import tool


def create_chat_tools(executor: CommandExecutor) -> list:
    """Create chat tools that close over the shared executor.

    Each tool takes ``bot_guid`` as an input parameter — the system prompt
    tells the LLM which guid to use for the current bot.
    """

    @tool(
        name="say",
        description="Speak aloud so nearby players and NPCs can hear you.",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer", "description": "Your bot GUID (from your state)"},
                "message": {"type": "string", "description": "What to say"},
            },
            "required": ["bot_guid", "message"],
        },
    )
    async def say(args):
        cmd = BotCommand(
            command_type=CommandType.SAY, bot_guid=args["bot_guid"],
            payload={"message": args["message"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"You said: {args['message']}"}]}

    @tool(
        name="yell",
        description="Yell loudly so players in a wide area can hear you.",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": ["bot_guid", "message"],
        },
    )
    async def yell(args):
        cmd = BotCommand(
            command_type=CommandType.YELL, bot_guid=args["bot_guid"],
            payload={"message": args["message"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"You yelled: {args['message']}"}]}

    @tool(
        name="whisper",
        description="Send a private message to a specific player.",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "target_player": {"type": "string", "description": "Player name to whisper"},
                "message": {"type": "string"},
            },
            "required": ["bot_guid", "target_player", "message"],
        },
    )
    async def whisper(args):
        cmd = BotCommand(
            command_type=CommandType.WHISPER, bot_guid=args["bot_guid"],
            payload={"target_player": args["target_player"], "message": args["message"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"You whispered to {args['target_player']}: {args['message']}"}]}

    @tool(
        name="party_chat",
        description="Send a message to your party or group.",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": ["bot_guid", "message"],
        },
    )
    async def party_chat(args):
        cmd = BotCommand(
            command_type=CommandType.PARTY_CHAT, bot_guid=args["bot_guid"],
            payload={"message": args["message"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"You said in party: {args['message']}"}]}

    @tool(
        name="guild_chat",
        description="Send a message to your guild.",
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "message": {"type": "string"},
            },
            "required": ["bot_guid", "message"],
        },
    )
    async def guild_chat(args):
        cmd = BotCommand(
            command_type=CommandType.GUILD_CHAT, bot_guid=args["bot_guid"],
            payload={"message": args["message"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"You said in guild: {args['message']}"}]}

    @tool(
        name="emote",
        description=(
            "Perform an in-game emote. "
            "Available: wave, bow, laugh, cry, dance, cheer, sit, kneel, "
            "point, roar, salute, flex, shrug, clap, thank, beg."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_guid": {"type": "integer"},
                "emote_name": {"type": "string"},
            },
            "required": ["bot_guid", "emote_name"],
        },
    )
    async def emote(args):
        cmd = BotCommand(
            command_type=CommandType.EMOTE, bot_guid=args["bot_guid"],
            payload={"emote": args["emote_name"]},
        )
        await executor.execute(cmd)
        return {"content": [{"type": "text", "text": f"You performed: {args['emote_name']}"}]}

    return [say, yell, whisper, party_chat, guild_chat, emote]
