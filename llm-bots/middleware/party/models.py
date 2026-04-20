"""Immutable dataclasses exposed to the rest of the middleware.

``PartyState`` is rendered straight into the LLM prompt via
``to_prompt_section()``; supervisor and BotAgent never reach into
coordinator internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Role ranking for gear-tiebreak. Lower = higher priority.
# Real players always outrank bots; within bots: Tank > Healer > DPS.
ROLE_RANK_PLAYER = 0
ROLE_RANK_BOT_TANK = 1
ROLE_RANK_BOT_HEALER = 2
ROLE_RANK_BOT_DPS = 3


@dataclass(frozen=True)
class PartyMember:
    guid: int
    name: str
    cls: str = ""               # e.g. "priest"
    spec_role: str = "dps"      # "tank" | "healer" | "dps"
    level: int = 0
    hp_pct: int = 100
    is_player: bool = False

    @property
    def role_rank(self) -> int:
        if self.is_player:
            return ROLE_RANK_PLAYER
        if self.spec_role == "tank":
            return ROLE_RANK_BOT_TANK
        if self.spec_role == "healer":
            return ROLE_RANK_BOT_HEALER
        return ROLE_RANK_BOT_DPS


@dataclass(frozen=True)
class QuestProgress:
    """A shared collection-style quest objective across the party.

    ``per_member`` maps guid -> (current, required). Required is the
    objective count each member must reach (WoW quest-item objectives
    are per-character, not party-shared, but we track them together so
    the LLM can decide who needs help).
    """
    quest_id: int
    quest_name: str
    item_name: str
    per_member: dict[int, tuple[int, int]] = field(default_factory=dict)

    def member_current(self, guid: int) -> int:
        return self.per_member.get(guid, (0, 0))[0]

    def member_required(self, guid: int) -> int:
        return self.per_member.get(guid, (0, 0))[1]

    def is_complete_for(self, guid: int) -> bool:
        cur, req = self.per_member.get(guid, (0, 0))
        return req > 0 and cur >= req

    def surplus_for(self, guid: int) -> int:
        """How many extras this member has beyond their requirement."""
        cur, req = self.per_member.get(guid, (0, 0))
        return max(0, cur - req)


@dataclass(frozen=True)
class RollCandidate:
    """Single candidate considered for a gear / loot-roll arbitration."""
    guid: int
    name: str
    score_delta: float          # >0 means upgrade over currently equipped
    level: int
    role_rank: int              # see ROLE_RANK_* constants
    is_player: bool = False


@dataclass(frozen=True)
class PartyState:
    """What a single bot sees about its party this tick.

    One ``PartyState`` instance is built per party and reused across all
    members — values are read-only so sharing is safe.
    """
    party_id: str                              # stable hash of member guid set
    members: tuple[PartyMember, ...] = ()
    shared_quests: tuple[QuestProgress, ...] = ()

    @property
    def is_partied(self) -> bool:
        return len(self.members) > 1

    def member(self, guid: int) -> PartyMember | None:
        for m in self.members:
            if m.guid == guid:
                return m
        return None

    def to_prompt_section(self) -> str:
        """Render the ``[PARTY STATE]`` block for the LLM prompt.

        Kept compact: one line per member, one line per shared quest
        objective with per-member progress tuples.
        """
        if not self.is_partied:
            return ""

        member_lines = []
        for m in self.members:
            tag = "player" if m.is_player else f"bot-{m.spec_role}"
            member_lines.append(
                f"- {m.name} ({m.cls or '?'} L{m.level}, {tag}, {m.hp_pct}% HP)"
            )

        quest_lines: list[str] = []
        for q in self.shared_quests:
            progress = ", ".join(
                f"{self._short_name(guid)}={cur}/{req}"
                for guid, (cur, req) in q.per_member.items()
            )
            quest_lines.append(f"- {q.item_name} ({q.quest_name}): {progress}")

        parts = ["[PARTY STATE]", "Members:", *member_lines]
        if quest_lines:
            parts.extend(["Shared collection objectives:", *quest_lines])
        return "\n".join(parts)

    def _short_name(self, guid: int) -> str:
        m = self.member(guid)
        return m.name if m else str(guid)
