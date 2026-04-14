"""Compares two BotSnapshot instances and emits typed GameEvent objects.

This makes the polling path as structured as a push-based event system.
Consumers never see raw state — only typed events.
"""

from __future__ import annotations

from core.game_client import BotSnapshot
from game.events import (
    ActionChangedEvent,
    BotDiedEvent,
    BotRevivedEvent,
    CombatEndEvent,
    CombatStartEvent,
    GameEvent,
    HealthCriticalEvent,
    StrategyChangedEvent,
    TargetChangedEvent,
    ZoneChangedEvent,
)

HEALTH_CRITICAL_THRESHOLD = 20


def diff(
    old: BotSnapshot | None,
    new: BotSnapshot,
    bot_name: str = "",
) -> list[GameEvent]:
    """Return a list of events representing meaningful changes between snapshots."""
    events: list[GameEvent] = []
    guid = new.guid
    kwargs = {"bot_guid": guid, "bot_name": bot_name}

    if old is None:
        # First snapshot — no diff possible, just return empty
        return events

    # State transitions
    if old.state != new.state:
        if new.state == "combat":
            events.append(CombatStartEvent(target_name=new.target_name, **kwargs))
        elif old.state == "combat" and new.state == "non-combat":
            events.append(CombatEndEvent(**kwargs))
        elif new.state == "dead":
            events.append(BotDiedEvent(**kwargs))
        elif old.state == "dead" and new.state != "dead":
            events.append(BotRevivedEvent(**kwargs))

    # Health critical
    if (
        new.hp_pct <= HEALTH_CRITICAL_THRESHOLD
        and old.hp_pct > HEALTH_CRITICAL_THRESHOLD
    ):
        events.append(HealthCriticalEvent(hp_pct=new.hp_pct, **kwargs))

    # Zone change
    if old.zone != new.zone and new.zone:
        events.append(
            ZoneChangedEvent(old_zone=old.zone, new_zone=new.zone, **kwargs)
        )

    # Target change
    if old.target_name != new.target_name:
        events.append(
            TargetChangedEvent(
                old_target=old.target_name, new_target=new.target_name, **kwargs
            )
        )

    # Strategy change
    if old.strategy != new.strategy:
        events.append(
            StrategyChangedEvent(
                old_strategy=old.strategy, new_strategy=new.strategy, **kwargs
            )
        )

    # Action change (only meaningful ones, not spam)
    if old.last_action != new.last_action and new.last_action:
        events.append(
            ActionChangedEvent(
                old_action=old.last_action, new_action=new.last_action, **kwargs
            )
        )

    return events
