"""Resolve a bot's dungeon role from personality profile + class/spec.

An explicit ``dungeon_role`` in the personality YAML wins. Otherwise
fall back to a ``(class, spec)`` heuristic — specs that historically
tank or heal are classified accordingly, everything else is DPS.
"""

from __future__ import annotations

from dungeons.models import DungeonRole

_TANK_SPECS: set[tuple[str, str]] = {
    ("warrior", "protection"),
    ("paladin", "protection"),
    ("druid", "feral"),      # bear form (feral-tank)
    ("druid", "guardian"),   # modern naming, harmless to accept
    ("deathknight", "blood"),
    ("death knight", "blood"),
    ("dk", "blood"),
}

_HEALER_SPECS: set[tuple[str, str]] = {
    ("priest", "holy"),
    ("priest", "discipline"),
    ("paladin", "holy"),
    ("druid", "restoration"),
    ("shaman", "restoration"),
}


def _normalise(value: str) -> str:
    return (value or "").strip().lower()


def infer_role(profile: dict) -> DungeonRole:
    """Resolve role from a loaded personality dict.

    Order: explicit ``dungeon_role`` → class/spec lookup → DPS default.
    """
    explicit = profile.get("dungeon_role")
    if explicit:
        try:
            return DungeonRole(_normalise(str(explicit)))
        except ValueError:
            pass

    cls = _normalise(profile.get("class", ""))
    spec = _normalise(profile.get("spec", ""))
    key = (cls, spec)
    if key in _TANK_SPECS:
        return DungeonRole.TANK
    if key in _HEALER_SPECS:
        return DungeonRole.HEALER
    return DungeonRole.DPS
