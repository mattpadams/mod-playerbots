"""Async SQLAlchemy engine + session factory for acore_llmbots."""

from __future__ import annotations

from typing import AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings

logger = structlog.get_logger()


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def build_url(include_db: bool = True) -> str:
    base = (
        f"mysql+aiomysql://{settings.db_user}:{settings.db_pass}"
        f"@{settings.db_host}:{settings.db_port}"
    )
    return f"{base}/{settings.db_llmbots}" if include_db else f"{base}/"


async def init_engine() -> AsyncEngine:
    """Create the engine lazily on first call."""
    global _engine, _sessionmaker
    if _engine is not None:
        return _engine
    _engine = create_async_engine(
        build_url(include_db=True),
        echo=False,
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=4,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    logger.info("db.engine_ready", database=settings.db_llmbots)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("DB engine not initialized — call init_engine() first")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — yields a fresh session per request."""
    if _sessionmaker is None:
        raise RuntimeError("DB engine not initialized")
    async with _sessionmaker() as session:
        yield session


async def close_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _sessionmaker = None
