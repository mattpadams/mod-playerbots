"""On-demand combat context enrichment.

The supervisor's poll loop produces a light ``BotSnapshot`` every tick.
For combat events the LLM also needs a richer "situation" picture —
party composition, enemy attacker count, etc. Fetching that for every
bot every tick is wasteful (extra TCP queries × N bots × every 3s).

``CombatContextBuilder.build(guid, snapshot)`` is awaited only when an
event's ``EventPolicy.needs_combat_context`` is True (currently
``COMBAT_START`` and ``HEALTH_CRITICAL``).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog

from combat.models import PartyMember
from combat.snapshot_queries import parse_party, parse_values_attackers
from core.game_client import BotSnapshot, GameClient
from game.events import AddsSpawnedEvent, GameEvent

logger = structlog.get_logger()

# Minimum jump in attackers to count as an "adds wave". Below this the
# change is noise (a new target flick or a party member entering
# combat first) rather than a distinct add spawn.
ADDS_MIN_DELTA = 2


@dataclass
class CombatContext:
    """Rich situational data attached to combat-triggering LLM calls."""

    party_members: list[PartyMember] = field(default_factory=list)
    attacker_count: int = 0  # enemies in combat with the party
    my_attacker_count: int = 0  # enemies targeting this bot specifically
    balance_pct: int = 100  # party-vs-attackers balance (100 = even)

    @property
    def is_raid(self) -> bool:
        return len(self.party_members) > 5

    def to_prompt_section(self) -> str:
        """Format as a [COMBAT SITUATION] block for the LLM context.

        Returns empty string when there is nothing useful to add — the
        prompt builder will skip the section entirely.
        """
        if not self.party_members and self.attacker_count == 0:
            return ""

        lines = ["[COMBAT SITUATION]"]
        if self.party_members:
            lines.append(f"Party ({'raid' if self.is_raid else 'group'}):")
            for m in self.party_members:
                status = "DEAD" if not m.is_alive else f"{m.hp_pct}% hp"
                cls = f" ({m.cls})" if m.cls else ""
                lines.append(f"- {m.name}{cls} — {status}")
        if self.attacker_count:
            lines.append(f"Enemies in combat: {self.attacker_count}")
        if self.my_attacker_count:
            lines.append(f"Enemies targeting me: {self.my_attacker_count}")
        if self.balance_pct < 100:
            lines.append(
                f"Party-vs-enemy balance: {self.balance_pct}% "
                "(below 100 = outmatched)"
            )
        return "\n".join(lines)


class CombatContextBuilder:
    """Fetches combat enrichment data from the game server.

    Constructed once per supervisor and shared across all agents.
    Both queries fail-safe: any error returns an empty context, never
    raises into the agent loop.
    """

    def __init__(self, game_client: GameClient) -> None:
        self._game = game_client
        # Per-bot last-known attacker count. Populated by build() and
        # used to detect adds-spawn jumps between consecutive builds.
        self._last_attacker_count: dict[int, int] = {}
        # Events detected during build() (one entry per guid that saw a
        # big enough attacker jump). Drained by the supervisor.
        self._pending_events: dict[int, list[GameEvent]] = {}

    def pop_events(self, guid: int) -> list[GameEvent]:
        """Drain and return events detected for ``guid`` since last call."""
        return self._pending_events.pop(guid, [])

    async def build(self, guid: int, snapshot: BotSnapshot) -> CombatContext:
        # Fire both queries concurrently, tolerate failure of either.
        party_raw, values_raw = await asyncio.gather(
            self._game.query(guid, "party"),
            self._game.query(guid, "values"),
            return_exceptions=True,
        )

        ctx = CombatContext()

        if isinstance(party_raw, str) and party_raw:
            try:
                ctx.party_members = parse_party(party_raw)
            except Exception as exc:
                logger.warning(
                    "combat_context.party_parse_failed",
                    bot_guid=guid,
                    error=str(exc),
                )

        if isinstance(values_raw, str) and values_raw:
            try:
                attackers, my_attackers, balance = parse_values_attackers(values_raw)
                ctx.attacker_count = attackers
                ctx.my_attacker_count = my_attackers
                ctx.balance_pct = balance
                # Adds detection — only meaningful when we have a prior
                # sample from this bot's combat context. A fresh entry
                # (first build after combat starts) seeds the counter
                # without firing; subsequent jumps of >=ADDS_MIN_DELTA
                # queue an event for the supervisor to route.
                prev = self._last_attacker_count.get(guid)
                self._last_attacker_count[guid] = attackers
                if prev is not None and attackers - prev >= ADDS_MIN_DELTA:
                    # bot_name is populated by the supervisor when it
                    # drains pending events — it has the profile handle.
                    self._pending_events.setdefault(guid, []).append(
                        AddsSpawnedEvent(
                            bot_guid=guid,
                            new_attacker_count=attackers,
                            previous_attacker_count=prev,
                            delta=attackers - prev,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "combat_context.values_parse_failed",
                    bot_guid=guid,
                    error=str(exc),
                )

        return ctx
