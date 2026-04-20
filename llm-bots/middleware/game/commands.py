"""Typed command models emitted by agents and executed against the game server."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CommandType(str, Enum):
    # Chat
    SAY = "say"
    YELL = "yell"
    WHISPER = "whisper"
    PARTY_CHAT = "party"
    RAID_CHAT = "raid"
    GUILD_CHAT = "guild"
    EMOTE = "emote"

    # Strategy
    SET_STRATEGY = "set_strategy"
    ADD_STRATEGY = "add_strategy"
    REMOVE_STRATEGY = "remove_strategy"

    # Actions
    EXECUTE_ACTION = "execute_action"

    # Movement
    FOLLOW_PLAYER = "follow_player"
    STAY = "stay"
    GO_TO = "go_to"

    # Social
    INVITE_PLAYER = "invite_player"
    ACCEPT_INVITE = "accept_invite"
    LEAVE_GROUP = "leave_group"

    # Quest
    ACCEPT_QUEST = "accept_quest"
    DROP_QUEST = "drop_quest"
    SHARE_QUEST = "share_quest"

    # M4: Items + interaction
    TRADE_ITEM = "trade_item"
    VENDOR_BUY = "vendor_buy"
    VENDOR_SELL = "vendor_sell"
    CRAFT_ITEM = "craft_item"
    LOOT_ROLL = "loot_roll"
    CAST_SPELL = "cast_spell"
    USE_ITEM = "use_item"
    INTERACT_OBJECT = "interact_object"
    TALK_TO_NPC = "talk_to_npc"

    # M4: RPG behavior
    SET_RPG_MODE = "set_rpg_mode"


class BotCommand(BaseModel):
    """A single command to be executed by a bot in the game world."""

    command_type: CommandType
    bot_guid: int
    bot_name: str = ""
    payload: dict = Field(default_factory=dict)
    priority: int = 5  # 1 = immediate, 10 = low
