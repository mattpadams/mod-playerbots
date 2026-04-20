"""Zero-dependency migration runner for acore_llmbots.

Reads sorted ``*.sql`` files from ``db/migrations/`` and applies any
that haven't been recorded in ``schema_migrations``. Idempotent: safe to
call every startup.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings
from db.engine import build_url, init_engine

logger = structlog.get_logger()

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_SCHEMA_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "filename VARCHAR(100) NOT NULL PRIMARY KEY, "
    "applied_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
)


async def _ensure_database() -> None:
    """Connect without a database and issue CREATE DATABASE IF NOT EXISTS."""
    server_engine = create_async_engine(
        build_url(include_db=False), isolation_level="AUTOCOMMIT"
    )
    try:
        async with server_engine.connect() as conn:
            await conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{settings.db_llmbots}` "
                    "DEFAULT CHARACTER SET utf8mb4"
                )
            )
    finally:
        await server_engine.dispose()


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into individual statements.

    Naïve splitter: strips SQL line comments (``-- ...``) and splits on
    ``;``. Adequate for DDL-only migrations; do not embed ``;`` inside
    string literals without revisiting this.
    """
    cleaned_lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


async def run() -> None:
    """Bootstrap the database and apply any new migrations."""
    await _ensure_database()
    engine = await init_engine()

    async with engine.begin() as conn:
        await conn.execute(text(_SCHEMA_TABLE_DDL))

    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT filename FROM schema_migrations"))
        applied = {row[0] for row in result}

    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    new_files = [p for p in files if p.name not in applied]

    if not new_files:
        logger.info("db.migration.up_to_date", applied_count=len(applied))
        return

    for path in new_files:
        logger.info("db.migration.applying", filename=path.name)
        statements = _split_statements(path.read_text(encoding="utf-8"))
        async with engine.begin() as conn:
            for stmt in statements:
                await conn.execute(text(stmt))
            await conn.execute(
                text("INSERT INTO schema_migrations (filename) VALUES (:f)"),
                {"f": path.name},
            )
        logger.info(
            "db.migration.applied",
            filename=path.name,
            statements=len(statements),
        )
