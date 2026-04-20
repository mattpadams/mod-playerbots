"""Personality template CRUD (personality_templates)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PersonalityTemplate


class PersonalityRepo:
    """CRUD for DB-backed personality templates."""

    async def list_all(self, session: AsyncSession) -> list[PersonalityTemplate]:
        result = await session.execute(
            select(PersonalityTemplate).order_by(PersonalityTemplate.name)
        )
        return list(result.scalars())

    async def get_by_name(
        self, session: AsyncSession, name: str
    ) -> PersonalityTemplate | None:
        result = await session.execute(
            select(PersonalityTemplate).where(PersonalityTemplate.name == name)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, session: AsyncSession, name: str, yaml_data: str
    ) -> PersonalityTemplate:
        existing = await self.get_by_name(session, name)
        if existing is not None:
            existing.yaml_data = yaml_data
            await session.commit()
            await session.refresh(existing)
            return existing
        row = PersonalityTemplate(name=name, yaml_data=yaml_data)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def delete(self, session: AsyncSession, name: str) -> bool:
        row = await self.get_by_name(session, name)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
