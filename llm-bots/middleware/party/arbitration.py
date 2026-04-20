"""Generic winner-picker across a candidate list.

Used for:
  - Gear trade arbitration (who should equip this item?)
  - Loot roll arbitration (who should roll need?)
  - Future M5 uses: boss interrupt assignment, cooldown ownership.

The engine is a thin wrapper over ``min(..., key=score_fn)``. The value
is that every caller expresses its tiebreak as a single lexicographic
tuple — no branching logic scattered across the codebase.
"""
from __future__ import annotations

from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


class ArbitrationEngine:
    """Pure-function arbitration across typed candidate lists."""

    def pick_winner(
        self,
        candidates: Iterable[T],
        score_fn: Callable[[T], tuple],
        exclude: Callable[[T], bool] | None = None,
    ) -> T | None:
        """Return the candidate with the lowest score tuple, or None.

        ``score_fn`` returns a tuple compared lexicographically (Python
        tuple order). Callers should negate fields where "bigger is
        better" so that ``min`` picks the winner (e.g. ``-score_delta``).

        ``exclude`` optionally filters out ineligible candidates before
        scoring.
        """
        pool = [c for c in candidates if exclude is None or not exclude(c)]
        if not pool:
            return None
        return min(pool, key=score_fn)
