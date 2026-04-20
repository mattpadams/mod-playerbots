"""Elect one leader per dungeon group.

Priority:

1. Any bot with an explicit ``dungeon_role: leader`` in its personality
   profile — there can only be one; if multiple, first-seen wins.
2. A bot whose inferred role matches the dungeon's ``leader_role``
   (tank for tank-led dungeons, healer for the rare healer-led ones).
3. Role fall-through: tank > healer > dps.

Membership is the set of GUIDs currently inside the same dungeon
(keyed by ``dungeon_key``). Ties are broken by lowest GUID to make the
choice deterministic across ticks.
"""

from __future__ import annotations

from dataclasses import dataclass

from dungeons.models import Dungeon, DungeonRole


@dataclass(frozen=True)
class LeaderCandidate:
    guid: int
    role: DungeonRole
    explicit_leader: bool


_ROLE_RANK = {
    DungeonRole.TANK: 0,
    DungeonRole.HEALER: 1,
    DungeonRole.DPS: 2,
}


class LeaderTracker:
    """Caches the chosen leader per dungeon key. Recomputes when the
    membership set changes."""

    def __init__(self) -> None:
        self._by_dungeon: dict[str, tuple[frozenset[int], int | None]] = {}

    def resolve(
        self,
        dungeon: Dungeon,
        candidates: list[LeaderCandidate],
    ) -> int | None:
        """Return the chosen leader GUID for a dungeon, or ``None`` when
        the membership set is empty."""
        if not candidates:
            self._by_dungeon.pop(dungeon.key, None)
            return None

        membership = frozenset(c.guid for c in candidates)
        cached = self._by_dungeon.get(dungeon.key)
        if cached is not None and cached[0] == membership:
            return cached[1]

        chosen = self._elect(dungeon, candidates)
        self._by_dungeon[dungeon.key] = (membership, chosen)
        return chosen

    @staticmethod
    def _elect(
        dungeon: Dungeon, candidates: list[LeaderCandidate]
    ) -> int:
        explicit = [c for c in candidates if c.explicit_leader]
        if explicit:
            return min(c.guid for c in explicit)

        wanted_role = (
            dungeon.leader_role
            if isinstance(dungeon.leader_role, DungeonRole)
            else DungeonRole(dungeon.leader_role)
        )
        preferred = [c for c in candidates if c.role is wanted_role]
        if preferred:
            return min(c.guid for c in preferred)

        candidates_sorted = sorted(
            candidates, key=lambda c: (_ROLE_RANK[c.role], c.guid)
        )
        return candidates_sorted[0].guid

    def clear(self, dungeon_key: str) -> None:
        self._by_dungeon.pop(dungeon_key, None)
