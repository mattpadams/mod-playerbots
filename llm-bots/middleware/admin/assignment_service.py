"""Player <-> bot assignment and party-logoff policy.

Owns the business rules the user described:

  * 39 bots per player, organised as one main party of 4 + seven
    secondary parties of 5.
  * Main party bots must match the player's starting zone; remaining
    bots fill the secondary parties in the caller-provided order.
  * Per-party logoff: when a party's average capped level is >= the
    player's level, every bot in that party logs out.
  * The main party always logs off when the player is offline.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from db.engine import session_factory
from db.models import PlayerBotAssignment
from db.repos.assignment_repo import AssignmentRepo, AssignmentWrite

logger = structlog.get_logger()

MAIN_PARTY_SLOT = 0
SECONDARY_SLOT_COUNT = 7
MAIN_PARTY_SIZE = 4
SECONDARY_PARTY_SIZE = 5
TOTAL_BOTS_PER_PLAYER = MAIN_PARTY_SIZE + SECONDARY_SLOT_COUNT * SECONDARY_PARTY_SIZE


@dataclass
class CandidateBot:
    """Enough info to order bots by starting-zone affinity for assignment."""

    guid: int
    starting_zone: str


def capped_level(bot_level: int, player_level: int) -> int:
    """Apply the user's custom level cap for averaging.

    Player 1..60: bots above 60 contribute as 60.
    Player 60..70: bots above 70 contribute as 70.
    Else: raw level, capped to the 80 max.
    """
    if player_level <= 60:
        return min(bot_level, 60)
    if player_level <= 70:
        return min(bot_level, 70)
    return min(bot_level, 80)


def party_avg_capped(bot_levels: list[int], player_level: int) -> float:
    if not bot_levels:
        return 0.0
    return sum(capped_level(bl, player_level) for bl in bot_levels) / len(
        bot_levels
    )


class AssignmentService:
    def __init__(self, repo: AssignmentRepo) -> None:
        self._repo = repo

    async def list_for_player(
        self, player_guid: int
    ) -> list[PlayerBotAssignment]:
        async with session_factory()() as session:
            return await self._repo.list_for_player(session, player_guid)

    async def clear(self, player_guid: int) -> int:
        async with session_factory()() as session:
            return await self._repo.clear_for_player(session, player_guid)

    async def unassign_one(self, player_guid: int, bot_guid: int) -> bool:
        async with session_factory()() as session:
            return await self._repo.unassign_bot(
                session, player_guid, bot_guid
            )

    def plan(
        self,
        player_guid: int,
        player_starting_zone: str,
        candidates: list[CandidateBot],
    ) -> list[AssignmentWrite]:
        """Produce an assignment plan without writing to DB.

        Candidates are split into main-party material (starting zone
        matches the player's) and everything else; the main party fills
        from the matching pool first, then secondaries fill in the
        caller's declared order from the remaining pool. The caller is
        responsible for supplying enough candidates (up to 39).
        """
        main_pool = [c for c in candidates if c.starting_zone == player_starting_zone]
        other_pool = [c for c in candidates if c.starting_zone != player_starting_zone]
        ordered = main_pool + other_pool

        plan: list[AssignmentWrite] = []
        # Main party.
        for pos, bot in enumerate(ordered[:MAIN_PARTY_SIZE]):
            plan.append(
                AssignmentWrite(
                    player_guid=player_guid,
                    bot_guid=bot.guid,
                    party_slot=MAIN_PARTY_SLOT,
                    slot_position=pos,
                )
            )
        # Secondary parties.
        remaining = ordered[MAIN_PARTY_SIZE:]
        for slot in range(1, SECONDARY_SLOT_COUNT + 1):
            start = (slot - 1) * SECONDARY_PARTY_SIZE
            party = remaining[start : start + SECONDARY_PARTY_SIZE]
            for pos, bot in enumerate(party):
                plan.append(
                    AssignmentWrite(
                        player_guid=player_guid,
                        bot_guid=bot.guid,
                        party_slot=slot,
                        slot_position=pos,
                    )
                )
        return plan

    async def replace_for_player(
        self, player_guid: int, plan: list[AssignmentWrite]
    ) -> int:
        async with session_factory()() as session:
            n = await self._repo.bulk_replace_for_player(
                session, player_guid, plan
            )
        logger.info(
            "assignment_service.replaced",
            player_guid=player_guid,
            rows=n,
        )
        return n
