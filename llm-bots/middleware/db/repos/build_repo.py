"""Build template CRUD (build_templates)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BuildTemplate


@dataclass
class BuildTemplateWrite:
    name: str
    class_id: int
    race_id: int
    spec_index: int = 0
    level: int = 1
    gear_tier: str = "starter"
    starting_zone: str = ""
    personality: str = "default"
    notes: str | None = None


class BuildRepo:
    """CRUD for bot build templates."""

    async def list_all(self, session: AsyncSession) -> list[BuildTemplate]:
        result = await session.execute(
            select(BuildTemplate).order_by(BuildTemplate.name)
        )
        return list(result.scalars())

    async def get_by_id(
        self, session: AsyncSession, template_id: int
    ) -> BuildTemplate | None:
        return await session.get(BuildTemplate, template_id)

    async def get_by_name(
        self, session: AsyncSession, name: str
    ) -> BuildTemplate | None:
        result = await session.execute(
            select(BuildTemplate).where(BuildTemplate.name == name)
        )
        return result.scalar_one_or_none()

    async def create(
        self, session: AsyncSession, data: BuildTemplateWrite
    ) -> BuildTemplate:
        row = BuildTemplate(
            name=data.name,
            class_id=data.class_id,
            race_id=data.race_id,
            spec_index=data.spec_index,
            level=data.level,
            gear_tier=data.gear_tier,
            starting_zone=data.starting_zone,
            personality=data.personality,
            notes=data.notes,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def update(
        self,
        session: AsyncSession,
        template_id: int,
        data: BuildTemplateWrite,
    ) -> BuildTemplate | None:
        row = await self.get_by_id(session, template_id)
        if row is None:
            return None
        row.name = data.name
        row.class_id = data.class_id
        row.race_id = data.race_id
        row.spec_index = data.spec_index
        row.level = data.level
        row.gear_tier = data.gear_tier
        row.starting_zone = data.starting_zone
        row.personality = data.personality
        row.notes = data.notes
        await session.commit()
        await session.refresh(row)
        return row

    async def delete(self, session: AsyncSession, template_id: int) -> bool:
        row = await self.get_by_id(session, template_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
