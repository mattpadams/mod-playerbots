"""Player <-> bot assignment CRUD (player_bot_assignments)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PlayerBotAssignment


@dataclass
class AssignmentWrite:
    player_guid: int
    bot_guid: int
    party_slot: int  # 0=main, 1..7=secondary
    slot_position: int  # 0..4 within the party


class AssignmentRepo:
    """CRUD for player-bot assignments."""

    async def list_all(
        self, session: AsyncSession
    ) -> list[PlayerBotAssignment]:
        result = await session.execute(
            select(PlayerBotAssignment).order_by(
                PlayerBotAssignment.player_guid,
                PlayerBotAssignment.party_slot,
                PlayerBotAssignment.slot_position,
            )
        )
        return list(result.scalars())

    async def list_for_player(
        self, session: AsyncSession, player_guid: int
    ) -> list[PlayerBotAssignment]:
        result = await session.execute(
            select(PlayerBotAssignment)
            .where(PlayerBotAssignment.player_guid == player_guid)
            .order_by(
                PlayerBotAssignment.party_slot,
                PlayerBotAssignment.slot_position,
            )
        )
        return list(result.scalars())

    async def list_for_bot(
        self, session: AsyncSession, bot_guid: int
    ) -> list[PlayerBotAssignment]:
        result = await session.execute(
            select(PlayerBotAssignment).where(
                PlayerBotAssignment.bot_guid == bot_guid
            )
        )
        return list(result.scalars())

    async def bulk_replace_for_player(
        self,
        session: AsyncSession,
        player_guid: int,
        assignments: list[AssignmentWrite],
    ) -> int:
        """Replace all assignments for a player in one transaction.

        Returns the number of new rows inserted.
        """
        await session.execute(
            delete(PlayerBotAssignment).where(
                PlayerBotAssignment.player_guid == player_guid
            )
        )
        rows = [
            PlayerBotAssignment(
                player_guid=a.player_guid,
                bot_guid=a.bot_guid,
                party_slot=a.party_slot,
                slot_position=a.slot_position,
            )
            for a in assignments
        ]
        session.add_all(rows)
        await session.commit()
        return len(rows)

    async def clear_for_player(
        self, session: AsyncSession, player_guid: int
    ) -> int:
        result = await session.execute(
            delete(PlayerBotAssignment).where(
                PlayerBotAssignment.player_guid == player_guid
            )
        )
        await session.commit()
        return result.rowcount or 0

    async def unassign_bot(
        self, session: AsyncSession, player_guid: int, bot_guid: int
    ) -> bool:
        result = await session.execute(
            delete(PlayerBotAssignment).where(
                PlayerBotAssignment.player_guid == player_guid,
                PlayerBotAssignment.bot_guid == bot_guid,
            )
        )
        await session.commit()
        return (result.rowcount or 0) > 0
