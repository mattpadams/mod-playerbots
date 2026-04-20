"""Poll-based party roster discovery.

For each elevated bot, the rule-engine ``party,{guid}`` TCP query returns
the current party roster. Bots whose roster hash is identical are in the
same party.

Refresh cadence is keyed to events rather than ticks: any tick that saw
a ``ZONE_CHANGED`` or ``GROUP_INVITE`` forces an immediate refresh, else
we refresh every ``ROSTER_POLL_INTERVAL_SECONDS``.

The parsed roster is a list of ``PartyMember`` records. ``is_player`` is
true for every name not present in the elevated-bot registry — i.e. a
real human player sharing the party.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

import structlog

from core.bot_registry import BotRegistry
from core.game_client import BotSnapshot, GameClient
from party.models import PartyMember, PartyState

logger = structlog.get_logger()

ROSTER_POLL_INTERVAL_SECONDS = 15.0


@dataclass
class _PartyGroup:
    """Internal mutable accumulator for one party during a refresh."""
    party_id: str
    members: list[PartyMember] = field(default_factory=list)


class RosterTracker:
    """Discovers party groupings by polling per-bot party rosters.

    The tracker is stateful across ticks so it can answer
    ``get_party_state(guid)`` without re-querying mid-tick. Callers
    (``PartyCoordinator``) drive refreshes explicitly.
    """

    def __init__(self, game_client: GameClient, registry: BotRegistry) -> None:
        self._game = game_client
        self._registry = registry
        self._parties: dict[str, _PartyGroup] = {}   # party_id -> group
        self._guid_to_party: dict[int, str] = {}     # guid -> party_id
        self._last_refresh: float = 0.0

    async def refresh(
        self,
        snapshots: dict[int, BotSnapshot],
        force: bool = False,
    ) -> None:
        """Re-query party rosters for every bot in ``snapshots``.

        ``force=True`` bypasses the interval gate (used on zone change
        or group invite events).
        """
        now = time.monotonic()
        if not force and (now - self._last_refresh) < ROSTER_POLL_INTERVAL_SECONDS:
            return
        self._last_refresh = now

        new_parties: dict[str, _PartyGroup] = {}
        new_guid_to_party: dict[int, str] = {}

        for guid, snap in snapshots.items():
            try:
                raw = await self._game.query(guid, "party")
            except Exception as exc:
                logger.debug("roster.query_failed", guid=guid, error=str(exc))
                continue

            roster_members = self._parse_roster(raw, leader_guid=guid, snap=snap)
            if len(roster_members) <= 1:
                # Solo bot — no party
                continue

            pid = self._party_id(roster_members)
            if pid not in new_parties:
                new_parties[pid] = _PartyGroup(party_id=pid, members=roster_members)
            # Track which party each queried bot belongs to. We use the
            # first bot's parsing as authoritative for the party — all
            # members would parse to the same id.
            new_guid_to_party[guid] = pid

        self._parties = new_parties
        self._guid_to_party = new_guid_to_party

    def get_party_id(self, guid: int) -> str | None:
        return self._guid_to_party.get(guid)

    def get_members(self, guid: int) -> tuple[PartyMember, ...]:
        pid = self._guid_to_party.get(guid)
        if pid is None:
            return ()
        group = self._parties.get(pid)
        return tuple(group.members) if group else ()

    def build_state(self, guid: int) -> PartyState | None:
        """Return a ``PartyState`` for the bot, or None if solo.

        Shared quest progress is injected separately by
        ``PartyCoordinator.build_party_state``; this tracker only knows
        about membership.
        """
        pid = self._guid_to_party.get(guid)
        if pid is None:
            return None
        group = self._parties.get(pid)
        if not group:
            return None
        return PartyState(party_id=pid, members=tuple(group.members))

    # -- parsing --------------------------------------------------------------

    def _parse_roster(
        self,
        raw: str,
        leader_guid: int,
        snap: BotSnapshot,
    ) -> list[PartyMember]:
        """Parse the ``party`` TCP response into ``PartyMember`` records.

        Response format (mod-playerbots ``HandleRemoteCommand``):
        ``Name:Class:HpPct|Name:Class:HpPct`` — pipe-separated, three
        fields each. Empty string when the bot is solo.

        ``spec_role`` and ``level`` are not in the response; they stay
        at defaults unless injected from other queries (spec comes from
        ``values`` in a later layer).
        """
        members: list[PartyMember] = []
        if not raw:
            return members

        for tok in (t.strip() for t in raw.split("|")):
            if not tok:
                continue
            parts = tok.split(":")
            name = parts[0].strip()
            if not name:
                continue
            cls = parts[1].strip().lower() if len(parts) > 1 else ""
            try:
                hp = int(parts[2].rstrip("%")) if len(parts) > 2 else 100
            except ValueError:
                hp = 100

            guid = self._guid_for_name(name)
            is_player = guid is None

            members.append(
                PartyMember(
                    guid=guid or 0,
                    name=name,
                    cls=cls,
                    spec_role="dps",   # filled in by PartyCoordinator via spec query
                    level=0,            # same — filled in by a dedicated query
                    hp_pct=hp,
                    is_player=is_player,
                )
            )

        # Safety net: if the queried bot didn't appear in its own
        # roster (shouldn't happen, but groups can race), inject it.
        if not any(m.guid == leader_guid for m in members):
            profile = self._registry.get(leader_guid)
            members.insert(
                0,
                PartyMember(
                    guid=leader_guid,
                    name=profile.name if profile else str(leader_guid),
                    hp_pct=snap.hp_pct,
                ),
            )
        return members

    def _guid_for_name(self, name: str) -> int | None:
        for profile in self._registry.all_elevated():
            if profile.name.lower() == name.lower():
                return profile.guid
        return None

    def _party_id(self, members: list[PartyMember]) -> str:
        key = ",".join(sorted(m.name.lower() for m in members))
        return hashlib.sha1(key.encode()).hexdigest()[:12]
