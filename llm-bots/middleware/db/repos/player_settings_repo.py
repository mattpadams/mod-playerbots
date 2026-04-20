"""Per-player runtime toggles (player_settings)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PlayerSettings


class PlayerSettingsRepo:
    """CRUD for the per-player bots/llm on-off flags."""

    async def get(
        self, session: AsyncSession, player_guid: int
    ) -> PlayerSettings | None:
        return await session.get(PlayerSettings, player_guid)

    async def list_all(self, session: AsyncSession) -> list[PlayerSettings]:
        result = await session.execute(
            select(PlayerSettings).order_by(PlayerSettings.player_guid)
        )
        return list(result.scalars())

    async def upsert(
        self,
        session: AsyncSession,
        player_guid: int,
        bots_enabled: bool,
        llm_enabled: bool,
    ) -> PlayerSettings:
        stmt = mysql_insert(PlayerSettings).values(
            player_guid=player_guid,
            bots_enabled=bots_enabled,
            llm_enabled=llm_enabled,
        )
        stmt = stmt.on_duplicate_key_update(
            bots_enabled=bots_enabled,
            llm_enabled=llm_enabled,
        )
        await session.execute(stmt)
        await session.commit()
        row = await self.get(session, player_guid)
        if row is None:
            raise RuntimeError(
                f"player_settings row missing after upsert for {player_guid}"
            )
        return row

    async def set_bots_enabled(
        self, session: AsyncSession, player_guid: int, enabled: bool
    ) -> PlayerSettings:
        existing = await self.get(session, player_guid)
        llm = existing.llm_enabled if existing else True
        return await self.upsert(session, player_guid, enabled, llm)

    async def set_llm_enabled(
        self, session: AsyncSession, player_guid: int, enabled: bool
    ) -> PlayerSettings:
        existing = await self.get(session, player_guid)
        bots = existing.bots_enabled if existing else True
        return await self.upsert(session, player_guid, bots, enabled)
