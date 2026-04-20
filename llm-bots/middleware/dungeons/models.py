"""Typed models for dungeon knowledge YAMLs."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Difficulty(str, Enum):
    NORMAL = "normal"
    HEROIC = "heroic"


class DungeonRole(str, Enum):
    TANK = "tank"
    HEALER = "healer"
    DPS = "dps"


class BossPhase(BaseModel):
    name: str = ""
    hp_threshold: Optional[float] = None
    description: str = ""
    tank: str = ""
    healer: str = ""
    dps: str = ""
    mechanics: list[str] = Field(default_factory=list)


class Boss(BaseModel):
    name: str
    order: int = 0
    aliases: list[str] = Field(default_factory=list)
    phases: list[BossPhase] = Field(default_factory=list)

    def role_instructions(self, role: DungeonRole, phase_index: int = 0) -> str:
        """Instructions for the given role at the given phase index.

        Falls back to phase 0 if the index is out of range. Empty string
        when the phase doesn't have text for that role.
        """
        if not self.phases:
            return ""
        idx = phase_index if 0 <= phase_index < len(self.phases) else 0
        p = self.phases[idx]
        return {
            DungeonRole.TANK: p.tank,
            DungeonRole.HEALER: p.healer,
            DungeonRole.DPS: p.dps,
        }[role]

    def phase_for_hp(self, target_hp_pct: Optional[float]) -> int:
        """Resolve which phase the boss is in given current HP.

        Phase 0 has ``hp_threshold: None`` and is the initial phase.
        Subsequent phases trigger when HP crosses below their threshold.
        Returns the highest index whose threshold has been crossed.
        """
        if target_hp_pct is None or not self.phases:
            return 0
        idx = 0
        for i, phase in enumerate(self.phases):
            if phase.hp_threshold is None:
                continue
            if target_hp_pct <= phase.hp_threshold:
                idx = max(idx, i)
        return idx


class Dungeon(BaseModel):
    key: str
    name: str
    map_id: int
    sub_zone: Optional[str] = None
    expansion: str = "wotlk"
    difficulty: Difficulty = Difficulty.NORMAL
    strategy_key: Optional[str] = None
    cpp_coverage: str = "none"
    min_level: int = 0
    max_level: int = 0
    leader_role: DungeonRole = DungeonRole.TANK
    general_notes: str = ""
    bosses: list[Boss] = Field(default_factory=list)

    def find_boss(self, target_name: str) -> Optional[Boss]:
        """Match an encounter by target name against boss name or aliases."""
        if not target_name:
            return None
        needle = target_name.strip().lower()
        for boss in self.bosses:
            if boss.name.lower() == needle:
                return boss
            if any(a.lower() == needle for a in boss.aliases):
                return boss
        return None

    def boss_order(self) -> list[str]:
        return [b.name for b in sorted(self.bosses, key=lambda b: b.order)]
