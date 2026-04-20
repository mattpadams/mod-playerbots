"""Runtime-mutable settings: global model + LLM kill switch.

Reads/writes ``llm_settings`` via ``SettingsRepo`` and keeps the
process-local ``Settings`` object in sync so the cost controller and
bot agents see updates without a restart.
"""

from __future__ import annotations

import structlog

from core.config import settings
from db.engine import session_factory
from db.repos.settings_repo import SettingsRepo

logger = structlog.get_logger()

KEY_KILL_SWITCH = "llm_kill_switch"
KEY_MODEL_OVERRIDE = "llm_model_override"


class SettingsService:
    """Wraps SettingsRepo with the in-memory mirror of runtime settings."""

    def __init__(self, repo: SettingsRepo) -> None:
        self._repo = repo

    async def hydrate(self) -> None:
        """Load persisted values on startup and mirror to ``settings``."""
        async with session_factory()() as session:
            kill = await self._repo.get(session, KEY_KILL_SWITCH)
            if isinstance(kill, bool):
                settings.llm_kill_switch = kill
            override = await self._repo.get(session, KEY_MODEL_OVERRIDE)
            if isinstance(override, str):
                settings.llm_model_override = override
        logger.info(
            "settings_service.hydrated",
            kill_switch=settings.llm_kill_switch,
            model_override=settings.llm_model_override,
        )

    async def get_all(self) -> dict[str, object]:
        async with session_factory()() as session:
            return await self._repo.get_all(session)

    async def set_kill_switch(self, enabled: bool) -> None:
        async with session_factory()() as session:
            await self._repo.set(session, KEY_KILL_SWITCH, enabled)
        settings.llm_kill_switch = enabled
        logger.info("settings_service.kill_switch_set", enabled=enabled)

    async def set_model_override(self, model: str) -> None:
        async with session_factory()() as session:
            await self._repo.set(session, KEY_MODEL_OVERRIDE, model)
        settings.llm_model_override = model
        logger.info("settings_service.model_override_set", model=model)
