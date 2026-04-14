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
    ABANDON_QUEST = "abandon_quest"


class BotCommand(BaseModel):
    """A single command to be executed by a bot in the game world."""

    command_type: CommandType
    bot_guid: int
    bot_name: str = ""
    payload: dict = Field(default_factory=dict)
    priority: int = 5  # 1 = immediate, 10 = low
