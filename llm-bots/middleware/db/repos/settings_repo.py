"""Key-value settings repository (llm_settings)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import LlmSetting


class SettingsRepo:
    """CRUD for the llm_settings key-value table."""

    async def get(self, session: AsyncSession, key: str) -> Any | None:
        row = await session.get(LlmSetting, key)
        if row is None:
            return None
        try:
            return json.loads(row.value_json)
        except json.JSONDecodeError:
            return row.value_json

    async def get_all(self, session: AsyncSession) -> dict[str, Any]:
        result = await session.execute(select(LlmSetting))
        out: dict[str, Any] = {}
        for row in result.scalars():
            try:
                out[row.key_name] = json.loads(row.value_json)
            except json.JSONDecodeError:
                out[row.key_name] = row.value_json
        return out

    async def set(self, session: AsyncSession, key: str, value: Any) -> None:
        """Upsert a setting. ``value`` is JSON-serialised."""
        payload = json.dumps(value)
        stmt = mysql_insert(LlmSetting).values(
            key_name=key, value_json=payload
        )
        stmt = stmt.on_duplicate_key_update(value_json=payload)
        await session.execute(stmt)
        await session.commit()
