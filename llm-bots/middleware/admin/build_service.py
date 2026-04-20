"""Build template service: CRUD wrapper with basic validation."""

from __future__ import annotations

import structlog

from db.engine import session_factory
from db.models import BuildTemplate
from db.repos.build_repo import BuildRepo, BuildTemplateWrite

logger = structlog.get_logger()

# WoW WotLK classes (1..11, 10 unused). Gating here prevents obvious typos
# from reaching SOAP ``.character create``; not an authoritative lookup.
VALID_CLASS_IDS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11}
VALID_RACE_IDS = {1, 2, 3, 4, 5, 6, 7, 8, 10, 11}
VALID_GEAR_TIERS = {"starter", "leveling", "heroic", "raid"}


class BuildService:
    def __init__(self, repo: BuildRepo) -> None:
        self._repo = repo

    def _validate(self, data: BuildTemplateWrite) -> None:
        if data.class_id not in VALID_CLASS_IDS:
            raise ValueError(f"Invalid class_id: {data.class_id}")
        if data.race_id not in VALID_RACE_IDS:
            raise ValueError(f"Invalid race_id: {data.race_id}")
        if not 1 <= data.level <= 80:
            raise ValueError(f"Invalid level: {data.level}")
        if data.gear_tier not in VALID_GEAR_TIERS:
            raise ValueError(f"Invalid gear_tier: {data.gear_tier}")
        if not data.name.strip():
            raise ValueError("Template name required")

    async def list_all(self) -> list[BuildTemplate]:
        async with session_factory()() as session:
            return await self._repo.list_all(session)

    async def get(self, template_id: int) -> BuildTemplate | None:
        async with session_factory()() as session:
            return await self._repo.get_by_id(session, template_id)

    async def create(self, data: BuildTemplateWrite) -> BuildTemplate:
        self._validate(data)
        async with session_factory()() as session:
            row = await self._repo.create(session, data)
        logger.info("build_service.created", id=row.id, name=row.name)
        return row

    async def update(
        self, template_id: int, data: BuildTemplateWrite
    ) -> BuildTemplate | None:
        self._validate(data)
        async with session_factory()() as session:
            row = await self._repo.update(session, template_id, data)
        if row is not None:
            logger.info("build_service.updated", id=row.id, name=row.name)
        return row

    async def delete(self, template_id: int) -> bool:
        async with session_factory()() as session:
            ok = await self._repo.delete(session, template_id)
        if ok:
            logger.info("build_service.deleted", id=template_id)
        return ok
