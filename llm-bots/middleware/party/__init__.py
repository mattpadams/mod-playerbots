"""Party coordination package — multi-bot shared state and arbitration.

M4 introduces the ``PartyCoordinator`` layer: a per-tick refresh of party
rosters, shared quest progress, gear/loot arbitration, and proximity
triggers. ``BotAgent`` receives an immutable ``PartyState`` snapshot at
event-handling time; it does not hold a reference back into coordinator
state.
"""
from __future__ import annotations

from party.arbitration import ArbitrationEngine
from party.coordinator import PartyCoordinator
from party.models import (
    PartyMember,
    PartyState,
    QuestProgress,
    RollCandidate,
)

__all__ = [
    "ArbitrationEngine",
    "PartyCoordinator",
    "PartyMember",
    "PartyState",
    "QuestProgress",
    "RollCandidate",
]
