"""Typed game event models.

Every event flowing through the system is a concrete subclass of ``GameEvent``.
The event *source* (polling, HTTP push, Redis) is irrelevant to consumers —
they only see these models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class EventType(str, Enum):
    # State transitions
    COMBAT_START = "combat_start"
    COMBAT_END = "combat_end"
    BOT_DIED = "bot_died"
    BOT_REVIVED = "bot_revived"
    HEALTH_CRITICAL = "health_critical"

    # Chat
    CHAT_RECEIVED = "chat_received"

    # Social
    PLAYER_NEARBY = "player_nearby"
    GROUP_INVITE = "group_invite"

    # World
    ZONE_CHANGED = "zone_changed"
    TARGET_CHANGED = "target_changed"
    STRATEGY_CHANGED = "strategy_changed"
    ACTION_CHANGED = "action_changed"

    # Periodic
    STATE_SNAPSHOT = "state_snapshot"

    # Proactive
    IDLE_TICK = "idle_tick"


class GameEvent(BaseModel):
    """Base event envelope."""

    event_type: EventType
    bot_guid: int
    bot_name: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# -- State transition events --------------------------------------------------


class CombatStartEvent(GameEvent):
    event_type: Literal[EventType.COMBAT_START] = EventType.COMBAT_START
    target_name: str = ""


class CombatEndEvent(GameEvent):
    event_type: Literal[EventType.COMBAT_END] = EventType.COMBAT_END


class BotDiedEvent(GameEvent):
    event_type: Literal[EventType.BOT_DIED] = EventType.BOT_DIED


class BotRevivedEvent(GameEvent):
    event_type: Literal[EventType.BOT_REVIVED] = EventType.BOT_REVIVED


class HealthCriticalEvent(GameEvent):
    event_type: Literal[EventType.HEALTH_CRITICAL] = EventType.HEALTH_CRITICAL
    hp_pct: int = 0


# -- Chat events ---------------------------------------------------------------


class ChatReceivedEvent(GameEvent):
    event_type: Literal[EventType.CHAT_RECEIVED] = EventType.CHAT_RECEIVED
    channel: str = "say"
    sender_name: str = ""
    message: str = ""


# -- World events --------------------------------------------------------------


class ZoneChangedEvent(GameEvent):
    event_type: Literal[EventType.ZONE_CHANGED] = EventType.ZONE_CHANGED
    old_zone: str = ""
    new_zone: str = ""


class TargetChangedEvent(GameEvent):
    event_type: Literal[EventType.TARGET_CHANGED] = EventType.TARGET_CHANGED
    old_target: str = ""
    new_target: str = ""


class StrategyChangedEvent(GameEvent):
    event_type: Literal[EventType.STRATEGY_CHANGED] = EventType.STRATEGY_CHANGED
    old_strategy: str = ""
    new_strategy: str = ""


class ActionChangedEvent(GameEvent):
    event_type: Literal[EventType.ACTION_CHANGED] = EventType.ACTION_CHANGED
    old_action: str = ""
    new_action: str = ""


# -- Social events -------------------------------------------------------------


class PlayerNearbyEvent(GameEvent):
    event_type: Literal[EventType.PLAYER_NEARBY] = EventType.PLAYER_NEARBY
    player_name: str = ""


class GroupInviteEvent(GameEvent):
    event_type: Literal[EventType.GROUP_INVITE] = EventType.GROUP_INVITE
    inviter_name: str = ""


# -- Periodic ------------------------------------------------------------------


class StateSnapshotEvent(GameEvent):
    event_type: Literal[EventType.STATE_SNAPSHOT] = EventType.STATE_SNAPSHOT
    state: str = ""
    hp_pct: int = 100
    target_name: str = ""
    zone: str = ""
    strategy: str = ""
    last_action: str = ""
    position_x: float = 0.0
    position_y: float = 0.0
    position_z: float = 0.0
    map_id: int = 0


class IdleTickEvent(GameEvent):
    event_type: Literal[EventType.IDLE_TICK] = EventType.IDLE_TICK
    idle_seconds: float = 0.0
