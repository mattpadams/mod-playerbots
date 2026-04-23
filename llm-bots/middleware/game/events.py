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
    MANA_CRITICAL = "mana_critical"

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

    # Admin / dashboard-injected
    ADMIN_FORCE_SAY = "admin_force_say"

    # Party coordination (M4)
    PARTY_QUEST_PROGRESS = "party_quest_progress"
    LOOT_ROLL_STARTED = "loot_roll_started"
    VENDOR_NEARBY = "vendor_nearby"
    CRAFT_REQUESTED = "craft_requested"

    # Dungeon coordination (M5)
    DUNGEON_ENTERED = "dungeon_entered"
    DUNGEON_EXITED = "dungeon_exited"
    BOSS_ENGAGED = "boss_engaged"
    BOSS_DEFEATED = "boss_defeated"
    BOSS_PHASE_CHANGED = "boss_phase_changed"
    PARTY_MEMBER_DIED = "party_member_died"
    PARTY_WIPE = "party_wipe"
    ADDS_SPAWNED = "adds_spawned"


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


class ManaCriticalEvent(GameEvent):
    event_type: Literal[EventType.MANA_CRITICAL] = EventType.MANA_CRITICAL
    mana_pct: int = 0


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


# -- Admin injected ------------------------------------------------------------


class AdminForceSayEvent(GameEvent):
    """Dashboard admin asks the bot to react to a synthetic prompt."""

    event_type: Literal[EventType.ADMIN_FORCE_SAY] = EventType.ADMIN_FORCE_SAY
    text: str = ""


# -- Party coordination events (M4) -------------------------------------------


class PartyQuestProgressEvent(GameEvent):
    """A party member picked up a shared collection objective item.

    Fires on every pickup (low-drop quests make each item noteworthy).
    The bot assigned as the progress broadcaster is expected to whisper
    "/p ItemName cur/req" in party chat.
    """

    event_type: Literal[EventType.PARTY_QUEST_PROGRESS] = EventType.PARTY_QUEST_PROGRESS
    quest_name: str = ""
    item_name: str = ""
    picker_guid: int = 0
    picker_name: str = ""
    new_count: int = 0
    required: int = 0


class LootRollStartedEvent(GameEvent):
    """A roll window opened on an item eligible for this bot.

    The winner (resolved synchronously by ``LootRollHandler``) receives
    this event and decides need vs greed. Non-winners are told to pass
    via direct command; they do not receive the event.
    """

    event_type: Literal[EventType.LOOT_ROLL_STARTED] = EventType.LOOT_ROLL_STARTED
    roll_id: str = ""
    item_id: int = 0
    item_link: str = ""
    item_name: str = ""


class VendorNearbyEvent(GameEvent):
    """Bot is near a vendor and inventory is full or has gray items.

    ``invoke_llm=False`` — supervisor dispatches ``s gray`` / ``s vendor``
    directly. The event is recorded for memory/trace purposes only.
    """

    event_type: Literal[EventType.VENDOR_NEARBY] = EventType.VENDOR_NEARBY
    vendor_name: str = ""
    inventory_pct: int = 0
    has_gray: bool = False


class CraftRequestedEvent(GameEvent):
    """Party member asked this crafter bot to make consumables, or the
    coordinator detected a shortage (e.g. nobody has mana potions
    before a dungeon zone-in) and this bot has the materials.
    """

    event_type: Literal[EventType.CRAFT_REQUESTED] = EventType.CRAFT_REQUESTED
    item_name: str = ""
    requested_by: str = ""
    reason: str = ""


# -- Dungeon coordination events (M5) -----------------------------------------


class DungeonEnteredEvent(GameEvent):
    """Bot zoned into a known dungeon instance.

    ``dungeon_key`` matches a loaded ``Dungeon.key``. ``role`` is the
    resolved role for this bot (tank | healer | dps). The coordinator
    also dispatches the ``strategy_key`` activation via the command
    executor before this event is emitted.
    """

    event_type: Literal[EventType.DUNGEON_ENTERED] = EventType.DUNGEON_ENTERED
    dungeon_key: str = ""
    dungeon_name: str = ""
    map_id: int = 0
    difficulty: str = "normal"
    role: str = "dps"


class DungeonExitedEvent(GameEvent):
    """Bot left the instance map. Pre-dungeon strategy has already been
    restored by the coordinator before the event fires."""

    event_type: Literal[EventType.DUNGEON_EXITED] = EventType.DUNGEON_EXITED
    dungeon_key: str = ""
    dungeon_name: str = ""


class BossEngagedEvent(GameEvent):
    """Combat started against a boss encounter known in the dungeon YAML.

    Fires once per encounter — a boss swap (e.g. Skarvald/Dalronn) does
    not re-emit until combat ends and a new boss is engaged.
    """

    event_type: Literal[EventType.BOSS_ENGAGED] = EventType.BOSS_ENGAGED
    dungeon_key: str = ""
    boss_name: str = ""
    role: str = "dps"
    is_leader: bool = False


class BossDefeatedEvent(GameEvent):
    """Fires when combat ends after a boss engagement. The coordinator
    does not verify the boss actually died — any combat-end after a
    BossEngagedEvent emits this. Recorded only (no LLM call)."""

    event_type: Literal[EventType.BOSS_DEFEATED] = EventType.BOSS_DEFEATED
    dungeon_key: str = ""
    boss_name: str = ""


class BossPhaseChangedEvent(GameEvent):
    """Boss HP crossed downward through a phase threshold.

    ``phase_name`` is the name of the phase that just became active.
    Only fires for bots who see the boss as their current target.
    """

    event_type: Literal[EventType.BOSS_PHASE_CHANGED] = EventType.BOSS_PHASE_CHANGED
    dungeon_key: str = ""
    boss_name: str = ""
    phase_index: int = 0
    phase_name: str = ""
    role: str = "dps"


class PartyMemberDiedEvent(GameEvent):
    """A single member of the dungeon party died (pre-wipe).

    Emitted to the instance leader once per death — re-arms only after
    the member revives. Separate from BOT_DIED (self-death) so the
    leader gets a cross-party signal without each bot firing its own.
    """

    event_type: Literal[EventType.PARTY_MEMBER_DIED] = EventType.PARTY_MEMBER_DIED
    dungeon_key: str = ""
    dungeon_name: str = ""
    dead_bot_guid: int = 0
    dead_bot_name: str = ""
    dead_bot_role: str = "dps"


class PartyWipeEvent(GameEvent):
    """All elevated bots inside the same dungeon instance are dead.

    Emitted once per wipe (to the leader) and cleared when anyone
    revives. The leader is expected to acknowledge and suggest a
    different approach in party chat.
    """

    event_type: Literal[EventType.PARTY_WIPE] = EventType.PARTY_WIPE
    dungeon_key: str = ""
    dungeon_name: str = ""
    dead_bot_names: list[str] = Field(default_factory=list)


class AddsSpawnedEvent(GameEvent):
    """New enemies entered combat — the attacker count jumped.

    Emitted opportunistically by ``CombatContextBuilder`` when it sees
    at least ``ADDS_MIN_DELTA`` new attackers compared to its last
    build for the same bot. Not a proactive scan — only fires during a
    tick that already needed combat context (HEALTH_CRITICAL,
    COMBAT_START, BOSS_ENGAGED, etc.), which is the moment the LLM
    most wants the signal anyway.
    """

    event_type: Literal[EventType.ADDS_SPAWNED] = EventType.ADDS_SPAWNED
    new_attacker_count: int = 0
    previous_attacker_count: int = 0
    delta: int = 0
