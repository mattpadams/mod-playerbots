"""Translates BotCommand models into game server calls.

Uses the TCP command server for bot-level actions and SOAP for admin commands.
"""

from __future__ import annotations

import structlog

from core.game_client import GameClient
from core.soap_client import SoapClient
from game.commands import BotCommand, CommandType

logger = structlog.get_logger()


class CommandExecutor:
    """Executes BotCommand instances against the live game server."""

    def __init__(self, game_client: GameClient, soap_client: SoapClient) -> None:
        self._game = game_client
        self._soap = soap_client

    async def execute(self, cmd: BotCommand) -> str:
        """Dispatch a command and return the server response."""
        handler = _DISPATCH.get(cmd.command_type)
        if not handler:
            logger.warning("command_executor.unknown_type", command_type=cmd.command_type)
            return ""
        result = await handler(self, cmd)
        logger.info(
            "command_executor.executed",
            bot_guid=cmd.bot_guid,
            command_type=cmd.command_type,
            payload=cmd.payload,
        )
        return result

    # -- Chat ------------------------------------------------------------------

    async def _say(self, cmd: BotCommand) -> str:
        message = cmd.payload.get("message", "")
        return await self._game.send_command(cmd.bot_guid, f"say {message}")

    async def _yell(self, cmd: BotCommand) -> str:
        message = cmd.payload.get("message", "")
        return await self._game.send_command(cmd.bot_guid, f"yell {message}")

    async def _whisper(self, cmd: BotCommand) -> str:
        target = cmd.payload.get("target_player", "")
        message = cmd.payload.get("message", "")
        return await self._game.send_command(cmd.bot_guid, f"whisper {target} {message}")

    async def _party_chat(self, cmd: BotCommand) -> str:
        message = cmd.payload.get("message", "")
        return await self._game.send_command(cmd.bot_guid, f"#p {message}")

    async def _raid_chat(self, cmd: BotCommand) -> str:
        message = cmd.payload.get("message", "")
        return await self._game.send_command(cmd.bot_guid, f"#r {message}")

    async def _guild_chat(self, cmd: BotCommand) -> str:
        message = cmd.payload.get("message", "")
        return await self._game.send_command(cmd.bot_guid, f"#g {message}")

    async def _emote(self, cmd: BotCommand) -> str:
        emote_name = cmd.payload.get("emote", "wave")
        return await self._game.send_command(cmd.bot_guid, f"emote {emote_name}")

    # -- Strategy --------------------------------------------------------------

    async def _set_strategy(self, cmd: BotCommand) -> str:
        strategy = cmd.payload.get("strategy", "")
        return await self._game.send_command(cmd.bot_guid, f"co {strategy}")

    async def _add_strategy(self, cmd: BotCommand) -> str:
        strategy = cmd.payload.get("strategy", "")
        return await self._game.send_command(cmd.bot_guid, f"co +{strategy}")

    async def _remove_strategy(self, cmd: BotCommand) -> str:
        strategy = cmd.payload.get("strategy", "")
        return await self._game.send_command(cmd.bot_guid, f"co -{strategy}")

    # -- Actions ---------------------------------------------------------------

    async def _execute_action(self, cmd: BotCommand) -> str:
        action = cmd.payload.get("action", "")
        return await self._game.send_command(cmd.bot_guid, action)

    # -- Movement --------------------------------------------------------------

    async def _follow_player(self, cmd: BotCommand) -> str:
        player = cmd.payload.get("player_name", "")
        return await self._game.send_command(cmd.bot_guid, f"follow {player}")

    async def _stay(self, cmd: BotCommand) -> str:
        return await self._game.send_command(cmd.bot_guid, "stay")

    async def _go_to(self, cmd: BotCommand) -> str:
        x = cmd.payload.get("x", 0)
        y = cmd.payload.get("y", 0)
        z = cmd.payload.get("z", 0)
        return await self._game.send_command(cmd.bot_guid, f"go {x} {y} {z}")

    # -- Social ----------------------------------------------------------------

    async def _invite_player(self, cmd: BotCommand) -> str:
        player = cmd.payload.get("player_name", "")
        return await self._game.send_command(cmd.bot_guid, f"invite {player}")

    async def _accept_invite(self, cmd: BotCommand) -> str:
        return await self._game.send_command(cmd.bot_guid, "accept")

    async def _leave_group(self, cmd: BotCommand) -> str:
        return await self._game.send_command(cmd.bot_guid, "leave")

    # -- Quest -----------------------------------------------------------------

    async def _accept_quest(self, cmd: BotCommand) -> str:
        quest_id = cmd.payload.get("quest_id", "")
        return await self._game.send_command(cmd.bot_guid, f"accept quest {quest_id}")

    async def _abandon_quest(self, cmd: BotCommand) -> str:
        quest_id = cmd.payload.get("quest_id", "")
        return await self._game.send_command(cmd.bot_guid, f"abandon quest {quest_id}")


# Dispatch table mapping CommandType → handler method
_DISPATCH: dict = {
    CommandType.SAY: CommandExecutor._say,
    CommandType.YELL: CommandExecutor._yell,
    CommandType.WHISPER: CommandExecutor._whisper,
    CommandType.PARTY_CHAT: CommandExecutor._party_chat,
    CommandType.RAID_CHAT: CommandExecutor._raid_chat,
    CommandType.GUILD_CHAT: CommandExecutor._guild_chat,
    CommandType.EMOTE: CommandExecutor._emote,
    CommandType.SET_STRATEGY: CommandExecutor._set_strategy,
    CommandType.ADD_STRATEGY: CommandExecutor._add_strategy,
    CommandType.REMOVE_STRATEGY: CommandExecutor._remove_strategy,
    CommandType.EXECUTE_ACTION: CommandExecutor._execute_action,
    CommandType.FOLLOW_PLAYER: CommandExecutor._follow_player,
    CommandType.STAY: CommandExecutor._stay,
    CommandType.GO_TO: CommandExecutor._go_to,
    CommandType.INVITE_PLAYER: CommandExecutor._invite_player,
    CommandType.ACCEPT_INVITE: CommandExecutor._accept_invite,
    CommandType.LEAVE_GROUP: CommandExecutor._leave_group,
    CommandType.ACCEPT_QUEST: CommandExecutor._accept_quest,
    CommandType.ABANDON_QUEST: CommandExecutor._abandon_quest,
}
