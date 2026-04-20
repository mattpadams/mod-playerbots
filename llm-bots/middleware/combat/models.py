"""Shared data models used by combat context and its query parsers.

Extracted to a dedicated module so that ``combat/context.py`` and
``combat/snapshot_queries.py`` can both import from here without the
circular dependency that existed when ``PartyMember`` lived in
``context.py``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PartyMember:
    """One member of the bot's party as reported by the C++ ``party`` query."""

    name: str
    cls: str = ""
    hp_pct: int = 100

    @property
    def is_alive(self) -> bool:
        return self.hp_pct > 0
