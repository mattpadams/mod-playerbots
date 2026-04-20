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
        # ``GoAction`` parses three semicolon-separated floats as an
        # absolute map coord. ``destination`` (named zone / NPC / stored
        # position / "travel <name>") short-circuits the coord path.
        destination = cmd.payload.get("destination")
        if destination:
            return await self._game.send_command(
                cmd.bot_guid, f"go {destination}"
            )
        x = cmd.payload.get("x", 0)
        y = cmd.payload.get("y", 0)
        z = cmd.payload.get("z", 0)
        return await self._game.send_command(cmd.bot_guid, f"go {x};{y};{z}")

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
        # ``AcceptQuestAction`` parses a quest link or ``"*"`` for all
        # available quests at the current quest giver.
        link = (
            cmd.payload.get("quest_link")
            or cmd.payload.get("quest_id", "")
        )
        return await self._game.send_command(cmd.bot_guid, f"accept {link}")

    async def _drop_quest(self, cmd: BotCommand) -> str:
        # ``DropQuestAction`` takes either a quest link or a title
        # substring; do not prefix with "abandon".
        target = (
            cmd.payload.get("quest_link")
            or cmd.payload.get("quest_name")
            or cmd.payload.get("quest_id", "")
        )
        return await self._game.send_command(cmd.bot_guid, f"drop {target}")

    async def _share_quest(self, cmd: BotCommand) -> str:
        link = cmd.payload.get("item_link") or cmd.payload.get("quest_name", "")
        return await self._game.send_command(cmd.bot_guid, f"share {link}")

    # -- M4: Items and interaction --------------------------------------------

    async def _trade_item(self, cmd: BotCommand) -> str:
        target = cmd.payload.get("target_player", "")
        link = cmd.payload.get("item_link", "")
        count = cmd.payload.get("count")
        # mod-playerbots trade command: ``t [link] [target] [count]``
        suffix = f" {count}" if count else ""
        return await self._game.send_command(
            cmd.bot_guid, f"t {link} {target}{suffix}"
        )

    async def _vendor_sell(self, cmd: BotCommand) -> str:
        # filter: "gray", "vendor", or a specific item link
        filt = cmd.payload.get("filter", "gray")
        return await self._game.send_command(cmd.bot_guid, f"s {filt}")

    async def _vendor_buy(self, cmd: BotCommand) -> str:
        # ``BuyAction`` accepts the literal "vendor" (auto-buy useful
        # items) or a parsed item link.
        filt = cmd.payload.get("filter") or cmd.payload.get("item_link") or "vendor"
        return await self._game.send_command(cmd.bot_guid, f"b {filt}")

    async def _set_rpg_mode(self, cmd: BotCommand) -> str:
        mode = cmd.payload.get("mode", "idle")
        return await self._game.send_command(cmd.bot_guid, f"rpg mode {mode}")

    async def _craft_item(self, cmd: BotCommand) -> str:
        link = cmd.payload.get("item_link", "")
        count = cmd.payload.get("count", 1)
        # mod-playerbots craft command sets a craft target; count is
        # advisory, so we run it ``count`` times via its built-in queue.
        cmd_str = f"craft {link}" + (f" {count}" if count and count != 1 else "")
        return await self._game.send_command(cmd.bot_guid, cmd_str)

    async def _loot_roll(self, cmd: BotCommand) -> str:
        decision = cmd.payload.get("decision", "pass")   # need | greed | pass
        link = cmd.payload.get("item_link", "")
        return await self._game.send_command(
            cmd.bot_guid, f"roll {decision} {link}".rstrip()
        )

    async def _cast_spell(self, cmd: BotCommand) -> str:
        spell = cmd.payload.get("spell", "")
        target = cmd.payload.get("target", "")
        tail = f" {target}" if target else ""
        return await self._game.send_command(cmd.bot_guid, f"cast {spell}{tail}")

    async def _use_item(self, cmd: BotCommand) -> str:
        link = cmd.payload.get("item_link", "")
        target = cmd.payload.get("target", "")
        tail = f" {target}" if target else ""
        return await self._game.send_command(cmd.bot_guid, f"u {link}{tail}")

    async def _interact_object(self, cmd: BotCommand) -> str:
        name = cmd.payload.get("object_name", "")
        # ``go`` also handles named destinations / GameObjects
        return await self._game.send_command(cmd.bot_guid, f"go {name}")

    async def _talk_to_npc(self, cmd: BotCommand) -> str:
        name = cmd.payload.get("npc_name", "")
        return await self._game.send_command(cmd.bot_guid, f"talk {name}")


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
    CommandType.DROP_QUEST: CommandExecutor._drop_quest,
    CommandType.SHARE_QUEST: CommandExecutor._share_quest,
    CommandType.TRADE_ITEM: CommandExecutor._trade_item,
    CommandType.VENDOR_BUY: CommandExecutor._vendor_buy,
    CommandType.VENDOR_SELL: CommandExecutor._vendor_sell,
    CommandType.SET_RPG_MODE: CommandExecutor._set_rpg_mode,
    CommandType.CRAFT_ITEM: CommandExecutor._craft_item,
    CommandType.LOOT_ROLL: CommandExecutor._loot_roll,
    CommandType.CAST_SPELL: CommandExecutor._cast_spell,
    CommandType.USE_ITEM: CommandExecutor._use_item,
    CommandType.INTERACT_OBJECT: CommandExecutor._interact_object,
    CommandType.TALK_TO_NPC: CommandExecutor._talk_to_npc,
}
