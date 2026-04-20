"""Gear arbitration scoring — tiebreak ladder for M4.

User-specified precedence:
    1. Highest item-score delta (spec-weighted, from mod-playerbots)
    2. Higher level
    3. Role rank: Player current spec > Bot Tank > Bot Healer > Bot DPS

The scoring function returns a Python tuple compared lexicographically,
so ``ArbitrationEngine.pick_winner`` selects the candidate that is
best on (1); ties go to (2); further ties go to (3).
"""
from __future__ import annotations

from party.models import RollCandidate


def gear_score(candidate: RollCandidate) -> tuple:
    """Lexicographic tiebreak tuple for gear / loot-roll arbitration.

    All fields are negated or inverted so that ``min(..., key=...)``
    picks the winner:
      - ``-score_delta``: bigger upgrade wins
      - ``-level``: higher level wins
      - ``role_rank``: lower rank number wins (player=0, tank=1, ...)
    """
    return (-candidate.score_delta, -candidate.level, candidate.role_rank)


def gear_eligible(candidate: RollCandidate) -> bool:
    """A candidate is eligible only if the item is actually an upgrade.

    A non-positive ``score_delta`` means the candidate already has
    equal-or-better gear; arbitration should skip them so that a lower
    priority bot who *would* upgrade wins by default.
    """
    return candidate.score_delta > 0
