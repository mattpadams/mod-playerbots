"""Parsers for combat-context TCP queries.

These read the responses from the C++ ``PlayerbotCommandServer``:

  ``values,{guid}`` — already exists, returns ``{key=val}|{key=val}|...``
                       dump of all AiObjectContext values.
  ``party,{guid}``  — added in M3 (mod-playerbots), returns one line
                       per member: ``Name:Class:HpPct``, pipe-delimited
                       for compactness or newline-delimited.

Both parsers fail-safe: malformed input returns sensible defaults.
"""
from __future__ import annotations

import re

from combat.models import PartyMember

_VALUE_PATTERN = re.compile(r"\{([^=}]+)=([^}]*)\}")


def parse_values_attackers(raw: str) -> tuple[int, int, int]:
    """Extract ``(attacker_count, my_attacker_count, balance_pct)`` from
    a ``values,guid`` TCP response.

    Looks for the keys produced by mod-playerbots'
    ``AttackerCountValues`` (see C++ ``AttackerCountValues.cpp``):
      - ``attackers count`` — total attackers within sight
      - ``my attackers count`` — enemies attacking the bot directly
      - ``balance percentage`` — party-vs-attackers balance

    Returns ``(0, 0, 100)`` on parse failure or when a key is absent
    (the corresponding AI value is lazy-created — absent during
    non-combat ticks).
    """
    pairs = {k.strip(): v for k, v in _VALUE_PATTERN.findall(raw)}

    def _get_int(key: str, default: int) -> int:
        v = pairs.get(key, "")
        # Normal path: the value is a decimal string like "3".
        try:
            return int(v.strip())
        except (ValueError, TypeError):
            pass
        # Defensive fallback: older mod-playerbots builds had a uint8
        # formatter that emitted the raw byte instead of a decimal
        # (fixed upstream, but older builds in the wild still do this).
        # If the payload is a single byte, interpret it as an integer.
        if len(v) == 1:
            return ord(v)
        return default

    # Upstream mod-playerbots uses both singular and plural forms for the
    # "my attacker(s) count" value depending on the code path. Accept
    # either so the parser works regardless of which branch created it.
    my_attacker_count = (
        _get_int("my attackers count", -1)
        if "my attackers count" in pairs
        else _get_int("my attacker count", 0)
    )

    return (
        _get_int("attackers count", 0),
        max(my_attacker_count, 0),
        _get_int("balance percentage", 100),
    )


def parse_party(raw: str) -> list[PartyMember]:
    """Parse a ``party,guid`` TCP response into a list of ``PartyMember``.

    Expected format (one per line OR pipe-delimited):
        ``Name:Class:HpPct``

    Examples:
        ``Elariel:Priest:92`` (full)
        ``Shadowstep:Rogue:78`` (full)
        ``Frostweave::95`` (class missing, still parsed)

    Empty lines, malformed records, and entries with non-int HP are
    silently skipped — a partial party list is more useful than a
    failure.
    """
    members: list[PartyMember] = []
    # Accept both newline and pipe delimiters for flexibility.
    records = re.split(r"[\n|]+", raw.strip())
    for record in records:
        record = record.strip()
        if not record:
            continue
        parts = record.split(":")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        if not name:
            continue
        cls = parts[1].strip()
        try:
            hp_pct = int(parts[2].strip()) if len(parts) > 2 else 100
        except ValueError:
            hp_pct = 100
        members.append(PartyMember(name=name, cls=cls, hp_pct=hp_pct))
    return members
