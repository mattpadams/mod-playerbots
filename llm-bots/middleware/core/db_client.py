"""Minimal async MySQL client for middleware DB reads.

Used by the M7 proximity scanner to enumerate online human characters
and known bot GUIDs. Kept intentionally small — no ORM, no migrations,
no connection pool beyond what ``aiomysql`` gives us for free.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # aiomysql is a runtime-only dep
    import aiomysql

from core.config import settings

logger = structlog.get_logger()


@dataclass(frozen=True)
class HumanCharacter:
    """Online, non-bot character position as returned by the characters DB."""

    guid: int
    name: str
    map_id: int
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class CharacterMeta:
    """Name/level/online snapshot used by the party logoff checker."""

    guid: int
    name: str
    level: int
    online: bool


class DbClient:
    """Thin aiomysql wrapper with a lazy pool per database."""

    def __init__(self) -> None:
        self._pools: dict[str, object] = {}
        self._pool_lock = asyncio.Lock()

    async def _pool(self, db: str):
        import aiomysql  # lazy — keeps tests importable without the dep

        pool = self._pools.get(db)
        if pool is not None:
            return pool
        async with self._pool_lock:
            # Re-check under the lock; another task may have won the race.
            pool = self._pools.get(db)
            if pool is not None:
                return pool
            pool = await aiomysql.create_pool(
                host=settings.db_host,
                port=settings.db_port,
                user=settings.db_user,
                password=settings.db_pass,
                db=db,
                minsize=1,
                maxsize=4,
                autocommit=True,
            )
            self._pools[db] = pool
            return pool

    async def close(self) -> None:
        for pool in self._pools.values():
            pool.close()
            await pool.wait_closed()
        self._pools.clear()

    async def fetch_bot_guids(self) -> set[int]:
        """Return every known bot character GUID from ``acore_playerbots``.

        mod-playerbots tracks every bot it has ever created in its own
        database — the ``playerbots_random_bots`` table stores bot GUIDs
        alongside the account id that owns them. If the table is absent
        (fresh install, no random bots generated), we return an empty
        set and the scanner will treat every online character as human.
        """
        pool = await self._pool(settings.db_playerbots)
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT DISTINCT bot FROM playerbots_random_bots"
                    )
                    rows = await cur.fetchall()
                    return {int(r[0]) for r in rows}
        except Exception as exc:
            logger.warning("db_client.fetch_bot_guids_failed", error=str(exc))
            return set()

    async def fetch_online_humans(
        self, bot_guids: set[int]
    ) -> list[HumanCharacter]:
        """Return positions of every online character not in ``bot_guids``.

        The ``characters`` table has everyone — bots too — so we filter
        client-side against the known bot GUID set rather than doing a
        huge NOT IN clause at the DB.
        """
        pool = await self._pool(settings.db_characters)
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT guid, name, map, position_x, position_y, position_z "
                        "FROM characters WHERE online = 1"
                    )
                    rows = await cur.fetchall()
        except Exception as exc:
            logger.warning("db_client.fetch_online_failed", error=str(exc))
            return []
        humans: list[HumanCharacter] = []
        for guid, name, map_id, x, y, z in rows:
            guid = int(guid)
            if guid in bot_guids:
                continue
            humans.append(
                HumanCharacter(
                    guid=guid,
                    name=str(name),
                    map_id=int(map_id),
                    x=float(x),
                    y=float(y),
                    z=float(z),
                )
            )
        return humans

    async def fetch_character_meta(
        self, guids: set[int]
    ) -> dict[int, CharacterMeta]:
        """Return ``{guid: CharacterMeta}`` for every requested character.

        Characters not found are simply absent from the result. The query
        uses a generated IN (...) list because the guid set is bounded
        (one player + their 39 bots, per invocation). Raises on DB
        error so callers can distinguish "no rows" from "couldn't ask".
        """
        if not guids:
            return {}
        placeholders = ",".join(["%s"] * len(guids))
        pool = await self._pool(settings.db_characters)
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT guid, name, level, online FROM characters "
                    f"WHERE guid IN ({placeholders})",
                    tuple(guids),
                )
                rows = await cur.fetchall()
        out: dict[int, CharacterMeta] = {}
        for guid, name, level, online in rows:
            out[int(guid)] = CharacterMeta(
                guid=int(guid),
                name=str(name),
                level=int(level),
                online=bool(online),
            )
        return out
