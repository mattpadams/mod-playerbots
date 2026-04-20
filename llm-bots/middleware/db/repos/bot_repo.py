"""Managed bot character CRUD (managed_bots)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ManagedBot


@dataclass
class ManagedBotWrite:
    account_id: int
    character_guid: int
    character_name: str
    class_id: int
    race_id: int
    level: int = 1
    build_template_id: int | None = None
    personality_name: str = "default"


class BotRepo:
    """CRUD for middleware-provisioned bot characters."""

    async def list_all(self, session: AsyncSession) -> list[ManagedBot]:
        result = await session.execute(
            select(ManagedBot).order_by(ManagedBot.character_name)
        )
        return list(result.scalars())

    async def list_for_account(
        self, session: AsyncSession, account_id: int
    ) -> list[ManagedBot]:
        result = await session.execute(
            select(ManagedBot)
            .where(ManagedBot.account_id == account_id)
            .order_by(ManagedBot.character_name)
        )
        return list(result.scalars())

    async def get_by_guid(
        self, session: AsyncSession, character_guid: int
    ) -> ManagedBot | None:
        result = await session.execute(
            select(ManagedBot).where(ManagedBot.character_guid == character_guid)
        )
        return result.scalar_one_or_none()

    async def count_for_account(
        self, session: AsyncSession, account_id: int
    ) -> int:
        result = await session.execute(
            select(func.count(ManagedBot.id)).where(
                ManagedBot.account_id == account_id
            )
        )
        return int(result.scalar_one())

    async def create(
        self, session: AsyncSession, data: ManagedBotWrite
    ) -> ManagedBot:
        row = ManagedBot(
            account_id=data.account_id,
            character_guid=data.character_guid,
            character_name=data.character_name,
            class_id=data.class_id,
            race_id=data.race_id,
            level=data.level,
            build_template_id=data.build_template_id,
            personality_name=data.personality_name,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def update_personality(
        self, session: AsyncSession, character_guid: int, personality: str
    ) -> bool:
        row = await self.get_by_guid(session, character_guid)
        if row is None:
            return False
        row.personality_name = personality
        await session.commit()
        return True

    async def update_level(
        self, session: AsyncSession, character_guid: int, level: int
    ) -> bool:
        row = await self.get_by_guid(session, character_guid)
        if row is None:
            return False
        row.level = level
        await session.commit()
        return True

    async def delete(self, session: AsyncSession, character_guid: int) -> bool:
        row = await self.get_by_guid(session, character_guid)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
