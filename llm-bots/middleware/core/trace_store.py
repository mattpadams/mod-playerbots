"""SQLite-backed durable trace log for the observability dashboard.

Every completed ``AgentTrace`` is persisted here so the dashboard can
show history across middleware restarts and paginate beyond the
in-memory ring buffer.  Writes happen via ``asyncio.to_thread`` so they
never block the supervisor's event loop.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT    NOT NULL,
    bot_guid      INTEGER NOT NULL,
    bot_name      TEXT    NOT NULL,
    event_type    TEXT    NOT NULL,
    model         TEXT    NOT NULL,
    tokens_in     INTEGER NOT NULL DEFAULT 0,
    tokens_out    INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL    NOT NULL DEFAULT 0.0,
    latency_ms    REAL    NOT NULL DEFAULT 0.0,
    tool_calls    TEXT    NOT NULL DEFAULT '[]',
    preview       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_traces_bot_ts  ON traces (bot_guid, id DESC);
CREATE INDEX IF NOT EXISTS idx_traces_id_desc ON traces (id DESC);
"""


@dataclass
class TraceRow:
    id: int
    ts: str
    bot_guid: int
    bot_name: str
    event_type: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    tool_calls: list[str]
    preview: str


class TraceStore:
    """Thin async wrapper around a single-file SQLite DB."""

    def __init__(self, path: str | Path = "data/traces.db") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    async def insert(
        self,
        *,
        bot_guid: int,
        bot_name: str,
        event_type: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        latency_ms: float,
        tool_calls: list[str],
        preview: str,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()

        def _write() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO traces (ts, bot_guid, bot_name, event_type, "
                    "model, tokens_in, tokens_out, cost_usd, latency_ms, "
                    "tool_calls, preview) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ts, bot_guid, bot_name, event_type, model,
                        tokens_in, tokens_out, cost_usd, latency_ms,
                        json.dumps(tool_calls), preview,
                    ),
                )
            finally:
                conn.close()

        try:
            await asyncio.to_thread(_write)
        except sqlite3.Error as exc:
            logger.warning("trace_store.write_failed", error=str(exc))

    async def recent(
        self,
        *,
        bot_guid: int | None = None,
        limit: int = 100,
        before_id: int | None = None,
    ) -> list[TraceRow]:
        def _read() -> list[TraceRow]:
            sql = "SELECT * FROM traces WHERE 1=1"
            args: list[object] = []
            if bot_guid is not None:
                sql += " AND bot_guid = ?"
                args.append(bot_guid)
            if before_id is not None:
                sql += " AND id < ?"
                args.append(before_id)
            sql += " ORDER BY id DESC LIMIT ?"
            args.append(limit)
            conn = self._connect()
            try:
                rows = conn.execute(sql, args).fetchall()
            finally:
                conn.close()
            return [
                TraceRow(
                    id=r["id"],
                    ts=r["ts"],
                    bot_guid=r["bot_guid"],
                    bot_name=r["bot_name"],
                    event_type=r["event_type"],
                    model=r["model"],
                    tokens_in=r["tokens_in"],
                    tokens_out=r["tokens_out"],
                    cost_usd=r["cost_usd"],
                    latency_ms=r["latency_ms"],
                    tool_calls=json.loads(r["tool_calls"] or "[]"),
                    preview=r["preview"],
                )
                for r in rows
            ]

        return await asyncio.to_thread(_read)


def trace_row_to_dict(row: TraceRow) -> dict:
    return asdict(row)
