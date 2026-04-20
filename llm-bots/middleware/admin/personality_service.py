"""Personality template service: DB overrides on top of YAML.

When a DB row exists for a given ``name``, it supersedes any on-disk
YAML for that personality. Falls back to the existing YAML loader
otherwise. The YAML loader's cache is invalidated on write/delete so
downstream consumers pick up changes on the next call.
"""

from __future__ import annotations

import structlog
import yaml

import personality.loader as yaml_loader
from db.engine import session_factory
from db.models import PersonalityTemplate
from db.repos.personality_repo import PersonalityRepo

logger = structlog.get_logger()


class PersonalityService:
    def __init__(self, repo: PersonalityRepo) -> None:
        self._repo = repo

    async def hydrate(self) -> None:
        """Push all DB personalities into the YAML loader's override cache."""
        async with session_factory()() as session:
            rows = await self._repo.list_all(session)
        yaml_loader.clear_db_overrides()
        for row in rows:
            parsed = self._parse_yaml(row.name, row.yaml_data)
            if parsed is not None:
                yaml_loader.set_db_override(row.name, parsed)
        logger.info("personality_service.hydrated", count=len(rows))

    @staticmethod
    def _parse_yaml(name: str, yaml_data: str) -> dict | None:
        try:
            parsed = yaml.safe_load(yaml_data)
        except yaml.YAMLError as exc:
            logger.warning(
                "personality_service.yaml_parse_failed",
                name=name,
                error=str(exc),
            )
            return None
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            logger.warning(
                "personality_service.yaml_not_mapping", name=name
            )
            return None
        return parsed

    async def list_all(self) -> dict[str, list[str]]:
        """Return ``{"db": [...], "yaml": [...]}`` profile name lists."""
        async with session_factory()() as session:
            db_rows = await self._repo.list_all(session)
        return {
            "db": [row.name for row in db_rows],
            "yaml": yaml_loader.list_profiles(),
        }

    async def get(self, name: str) -> PersonalityTemplate | None:
        async with session_factory()() as session:
            return await self._repo.get_by_name(session, name)

    async def upsert(self, name: str, yaml_data: str) -> PersonalityTemplate:
        parsed = self._parse_yaml(name, yaml_data)
        if parsed is None:
            raise ValueError("Personality YAML must decode to a mapping")
        async with session_factory()() as session:
            row = await self._repo.upsert(session, name, yaml_data)
        yaml_loader.set_db_override(name, parsed)
        logger.info("personality_service.upserted", name=name)
        return row

    async def delete(self, name: str) -> bool:
        async with session_factory()() as session:
            ok = await self._repo.delete(session, name)
        if ok:
            yaml_loader.set_db_override(name, None)
            logger.info("personality_service.deleted", name=name)
        return ok

    async def get_db_override_dict(self, name: str) -> dict | None:
        """Return the parsed DB YAML for ``name``, or None if no DB row."""
        row = await self.get(name)
        if row is None:
            return None
        try:
            parsed = yaml.safe_load(row.yaml_data)
        except yaml.YAMLError as exc:
            logger.warning(
                "personality_service.db_yaml_parse_failed",
                name=name,
                error=str(exc),
            )
            return None
        return parsed if isinstance(parsed, dict) else None
