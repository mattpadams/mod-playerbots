"""Shared quest progress tracking.

Each tick, ``SharedQuestTracker.update(snapshots)`` queries the
``quests`` TCP command on every partied bot, parses the quest log into
per-bot objective counts, and emits ``PartyQuestProgressEvent`` for
every collection item delta — every pickup, not just milestones. Low
drop rates make each item genuinely noteworthy.

Requires a mod-playerbots ``quests`` remote command that returns lines
of the form::

    questId:questName:itemName:current:required

One line per collection-style objective. The C++ implementation lives
in ``PlayerbotAI::HandleRemoteCommand("quests")``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

import structlog

from core.game_client import BotSnapshot, GameClient
from game.events import PartyQuestProgressEvent
from party.models import QuestProgress, PartyMember

logger = structlog.get_logger()


@dataclass(frozen=True)
class _Objective:
    """One parsed line from the ``quests`` query."""
    quest_id: int
    quest_name: str
    item_name: str
    current: int
    required: int

    @property
    def key(self) -> tuple[int, str]:
        return (self.quest_id, self.item_name)


@dataclass
class SharedQuestTracker:
    """Per-party collection quest state.

    State is keyed by ``party_id`` so switching parties doesn't carry
    stale progress. One instance of the tracker serves all parties.
    """

    _per_bot: dict[int, dict[tuple[int, str], _Objective]] = field(
        default_factory=dict
    )

    async def update(
        self,
        game_client: GameClient,
        snapshots: dict[int, BotSnapshot],
        *,
        partied_guids: set[int] | None = None,
        name_lookup: Callable[[int], str] | None = None,
    ) -> list[PartyQuestProgressEvent]:
        """Refresh per-bot objectives and return the delta events.

        ``partied_guids`` restricts tracking to bots currently in a
        party. Solo bots never trigger party-chat broadcasts, so there
        is no value in querying or diffing their quest logs.

        ``name_lookup`` resolves guid -> character name so emitted
        events are fully populated at construction.
        """
        events: list[PartyQuestProgressEvent] = []
        name_fn = name_lookup or (lambda g: "")

        for guid, snap in snapshots.items():
            if partied_guids is not None and guid not in partied_guids:
                # Solo bot — drop any stale tracking state and skip.
                self._per_bot.pop(guid, None)
                continue
            try:
                raw = await game_client.query(guid, "quests")
            except Exception as exc:
                logger.debug("quest_tracker.query_failed", guid=guid, error=str(exc))
                continue

            new_objectives = _parse(raw)
            prev = self._per_bot.get(guid, {})
            bot_name = name_fn(guid)

            for key, obj in new_objectives.items():
                old = prev.get(key)
                # Fire only on count increase; decreases happen on
                # quest turn-in and aren't worth a chat line.
                if old is None or obj.current > old.current:
                    events.append(
                        PartyQuestProgressEvent(
                            bot_guid=guid,
                            bot_name=bot_name,
                            quest_name=obj.quest_name,
                            item_name=obj.item_name,
                            picker_guid=guid,
                            picker_name=bot_name,
                            new_count=obj.current,
                            required=obj.required,
                        )
                    )

            self._per_bot[guid] = new_objectives

        return events

    def tracked_guids(self) -> set[int]:
        """Set of bot guids currently being tracked (public, for coordinator)."""
        return set(self._per_bot.keys())

    def forget(self, guids: Iterable[int]) -> None:
        """Drop tracking state for bots no longer being observed."""
        for guid in guids:
            self._per_bot.pop(guid, None)

    def shared_progress(
        self,
        members: Iterable[PartyMember],
    ) -> tuple[QuestProgress, ...]:
        """Build a tuple of ``QuestProgress`` across the given members.

        Any collection objective any party member has in their log is
        included — this gives the LLM full visibility into what the
        party is pursuing, even if only one member has the quest so
        far (they should be looking to share it).
        """
        # Gather all (quest_id, item_name) keys that appear for any member
        all_keys: set[tuple[int, str]] = set()
        for m in members:
            for key in self._per_bot.get(m.guid, {}).keys():
                all_keys.add(key)

        shared: list[QuestProgress] = []
        for key in all_keys:
            per_member: dict[int, tuple[int, int]] = {}
            quest_name = ""
            item_name = ""
            for m in members:
                obj = self._per_bot.get(m.guid, {}).get(key)
                if obj is None:
                    continue
                per_member[m.guid] = (obj.current, obj.required)
                quest_name = obj.quest_name
                item_name = obj.item_name
            if len(per_member) >= 1:
                shared.append(
                    QuestProgress(
                        quest_id=key[0],
                        quest_name=quest_name,
                        item_name=item_name,
                        per_member=per_member,
                    )
                )
        return tuple(shared)


def _parse(raw: str) -> dict[tuple[int, str], _Objective]:
    """Parse ``quests`` response into a dict keyed by (quest_id, item_name).

    Response format (newline-separated; ``\\n`` is the record separator
    inside a single TCP response line — mod-playerbots may use a literal
    ``;`` separator instead to stay single-line; accept both)::

        questId:questName:itemName:current:required
    """
    result: dict[tuple[int, str], _Objective] = {}
    if not raw:
        return result

    # Accept either newline or semicolon between records.
    records = [r.strip() for r in raw.replace("\n", ";").split(";") if r.strip()]
    for rec in records:
        parts = rec.split(":")
        if len(parts) < 5:
            continue
        try:
            quest_id = int(parts[0])
            current = int(parts[3])
            required = int(parts[4])
        except ValueError:
            continue
        quest_name = parts[1].strip()
        item_name = parts[2].strip()
        if not item_name:
            continue
        obj = _Objective(
            quest_id=quest_id,
            quest_name=quest_name,
            item_name=item_name,
            current=current,
            required=required,
        )
        result[obj.key] = obj
    return result
