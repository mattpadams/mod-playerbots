"""TCP client for the PlayerbotCommandServer.

Protocol: send ``command,guid\\n``, receive response line.
The server lives inside the worldserver process on the configured port.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from core.config import settings

logger = structlog.get_logger()

# Connection pool. Sized for the worst case during combat:
#   6 light queries per bot in get_bot_state (state, position, hp, target,
#   strategy, action) + 2 heavy queries on combat events (party, values).
# 16 leaves headroom when several bots enter combat in the same tick.
_POOL_SIZE = 16
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 5.0


@dataclass
class BotSnapshot:
    """Parsed result of querying all state fields for one bot."""

    guid: int
    state: str = "unknown"
    position_x: float = 0.0
    position_y: float = 0.0
    position_z: float = 0.0
    map_id: int = 0
    orientation: float = 0.0
    zone: str = ""
    # ``area`` is the inner sub-zone name (GetAreaId → area_name).
    # For multi-wing instances (Dire Maul, Scarlet Monastery, etc.)
    # it discriminates which wing the bot is in; falls back to the
    # zone name when the server doesn't populate it.
    area: str = ""
    level: int = 0
    hp_pct: int = 100
    # ``None`` for classes without a mana bar (warrior, rogue, death knight).
    # ``int`` percentage otherwise. State-differ uses this for MANA_CRITICAL.
    mana_pct: int | None = None
    target_hp_pct: int | None = None
    target_name: str = ""
    strategy: str = ""
    last_action: str = ""
    values: str = ""
    travel: str = ""


class _Connection:
    """A single persistent TCP connection to PlayerbotCommandServer."""

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(settings.ws_host, settings.ws_cmd_port),
            timeout=_CONNECT_TIMEOUT,
        )

    async def query(self, text: str) -> str:
        async with self._lock:
            if self._writer is None or self._writer.is_closing():
                await self.connect()
            assert self._writer is not None and self._reader is not None
            self._writer.write((text + "\n").encode())
            await self._writer.drain()
            line = await asyncio.wait_for(
                self._reader.readline(), timeout=_READ_TIMEOUT
            )
            return line.decode().strip()

    async def close(self) -> None:
        if self._writer and not self._writer.is_closing():
            self._writer.close()
            await self._writer.wait_closed()
        self._writer = None
        self._reader = None


class GameClient:
    """Connection pool wrapping the PlayerbotCommandServer TCP protocol."""

    def __init__(self) -> None:
        self._connections: list[_Connection] = [_Connection() for _ in range(_POOL_SIZE)]
        self._index = 0

    def _next(self) -> _Connection:
        conn = self._connections[self._index % len(self._connections)]
        self._index += 1
        return conn

    async def query(self, guid: int, command: str) -> str:
        """Send a read-only query and return the response string."""
        msg = f"{command},{guid}"
        try:
            return await self._next().query(msg)
        except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as exc:
            logger.warning("game_client.query_failed", guid=guid, command=command, error=str(exc))
            return ""

    async def send_command(self, guid: int, command: str) -> str:
        """Send a write command (prefixed with ``do ``) through the TCP server."""
        msg = f"do {command},{guid}"
        try:
            return await self._next().query(msg)
        except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as exc:
            logger.warning(
                "game_client.send_failed", guid=guid, command=command, error=str(exc)
            )
            return ""

    async def get_bot_state(self, guid: int) -> BotSnapshot:
        """Query all state fields for a bot and return a structured snapshot.

        Each query uses a separate connection from the pool so they
        run truly concurrently under asyncio.gather.
        """
        snap = BotSnapshot(guid=guid)

        # Pre-assign connections to avoid lock contention under gather
        conns = [self._next() for _ in range(9)]

        async def _q(conn: _Connection, cmd: str) -> str:
            try:
                return await conn.query(f"{cmd},{guid}")
            except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError):
                return ""

        (
            state_raw,
            pos_raw,
            hp_raw,
            target_raw,
            strategy_raw,
            action_raw,
            mana_raw,
            level_raw,
            area_raw,
        ) = await asyncio.gather(
            _q(conns[0], "state"),
            _q(conns[1], "position"),
            _q(conns[2], "hp"),
            _q(conns[3], "target"),
            _q(conns[4], "strategy"),
            _q(conns[5], "action"),
            _q(conns[6], "mana"),
            _q(conns[7], "level"),
            _q(conns[8], "area"),
        )

        snap.state = state_raw or "unknown"
        snap.last_action = action_raw
        snap.strategy = strategy_raw
        snap.target_name = target_raw

        # mana: "NN%" or "n/a" for mana-less classes
        if mana_raw and mana_raw != "n/a":
            try:
                snap.mana_pct = int(mana_raw.strip().rstrip("%"))
            except ValueError:
                pass

        # level: integer. Absent on older builds without the "level" cmd.
        if level_raw:
            try:
                snap.level = int(level_raw.strip())
            except ValueError:
                pass

        # area: sub-zone name. Absent on older builds without the cmd.
        if area_raw:
            snap.area = area_raw.strip()

        # position: "x y z mapId orientation |ZoneName|"
        if pos_raw:
            parts = pos_raw.split()
            try:
                snap.position_x = float(parts[0])
                snap.position_y = float(parts[1])
                snap.position_z = float(parts[2])
                snap.map_id = int(parts[3])
                snap.orientation = float(parts[4])
            except (IndexError, ValueError):
                pass
            if "|" in pos_raw:
                snap.zone = pos_raw.split("|")[1]

        # hp: "87%" or "87% / 45%"
        if hp_raw:
            hp_parts = hp_raw.split("/")
            try:
                snap.hp_pct = int(hp_parts[0].strip().rstrip("%"))
            except ValueError:
                pass
            if len(hp_parts) > 1:
                try:
                    snap.target_hp_pct = int(hp_parts[1].strip().rstrip("%"))
                except ValueError:
                    pass

        return snap

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()
