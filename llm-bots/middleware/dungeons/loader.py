"""Loads dungeon knowledge from ``personality/dungeons/*.yaml``.

Heroic YAMLs declare ``overlay_of: <base_key>`` and only override the
fields that differ on heroic. The loader deep-merges the overlay onto
the base so consumers always see a complete ``Dungeon``.

Lookup is keyed by ``(map_id, difficulty)`` with an optional sub-zone
qualifier. Multi-wing maps (Dire Maul, the Hold wings, etc.) specify
``sub_zone`` — until we have a TCP command that reports the sub-wing,
those entries are loaded but never match at runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
import yaml

from dungeons.models import Boss, BossPhase, Difficulty, Dungeon

logger = structlog.get_logger()

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "personality" / "dungeons"


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _merge_phases(base: list[dict], overlay: list[dict]) -> list[dict]:
    """Overlay per-phase fields onto base phases matched by phase name.

    Boss/phase shape itself is fixed by the base file; overlays only
    edit per-phase text and mechanics. Phases present only in the
    overlay are ignored (heroic must not add phases).
    """
    by_name = {p.get("name"): dict(p) for p in base}
    for op in overlay:
        name = op.get("name")
        if name and name in by_name:
            by_name[name] = {**by_name[name], **op}
    # Preserve base order
    return [by_name[p.get("name")] for p in base if p.get("name") in by_name]


def _merge_bosses(base: list[dict], overlay: list[dict]) -> list[dict]:
    by_name = {b.get("name"): dict(b) for b in base}
    for ob in overlay:
        name = ob.get("name")
        if not name or name not in by_name:
            continue
        merged = {**by_name[name], **{k: v for k, v in ob.items() if k != "phases"}}
        if "phases" in ob:
            merged["phases"] = _merge_phases(
                by_name[name].get("phases", []), ob.get("phases", [])
            )
        by_name[name] = merged
    return [by_name[b.get("name")] for b in base if b.get("name") in by_name]


def _merge(base: dict, overlay: dict) -> dict:
    """Deep-merge the overlay fields we actually care about onto base."""
    merged = {**base, **{k: v for k, v in overlay.items() if k != "bosses"}}
    if "bosses" in overlay:
        merged["bosses"] = _merge_bosses(base.get("bosses", []), overlay["bosses"])
    return merged


def _build_dungeon(data: dict) -> Dungeon:
    bosses = [
        Boss(
            name=b.get("name", ""),
            order=b.get("order", 0),
            aliases=list(b.get("aliases") or []),
            phases=[
                BossPhase(
                    name=p.get("name", ""),
                    hp_threshold=p.get("hp_threshold"),
                    description=p.get("description", ""),
                    tank=p.get("tank", ""),
                    healer=p.get("healer", ""),
                    dps=p.get("dps", ""),
                    mechanics=list(p.get("mechanics") or []),
                )
                for p in (b.get("phases") or [])
            ],
        )
        for b in (data.get("bosses") or [])
    ]
    return Dungeon(
        key=data.get("key", ""),
        name=data.get("name", ""),
        map_id=int(data.get("map_id", 0)),
        sub_zone=data.get("sub_zone"),
        expansion=data.get("expansion", "wotlk"),
        difficulty=Difficulty(data.get("difficulty", "normal")),
        strategy_key=data.get("strategy_key"),
        cpp_coverage=data.get("cpp_coverage", "none"),
        min_level=int(data.get("min_level", 0) or 0),
        max_level=int(data.get("max_level", 0) or 0),
        leader_role=data.get("leader_role", "tank"),
        general_notes=data.get("general_notes", ""),
        bosses=bosses,
    )


class DungeonRegistry:
    """In-memory index of dungeon YAMLs.

    Primary lookup: ``(map_id, difficulty, sub_zone)``. Sub-zone is
    optional — entries with ``sub_zone: None`` are the default for
    single-wing dungeons.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[int, Difficulty, Optional[str]], Dungeon] = {}
        self._all: list[Dungeon] = []

    def load_dir(self, directory: Path = _DEFAULT_DIR) -> int:
        if not directory.exists():
            logger.warning("dungeons.loader.dir_missing", path=str(directory))
            return 0

        # Two passes: base dungeons first, then overlays so we can merge.
        raw_by_key: dict[str, dict] = {}
        overlays: list[dict] = []
        for path in sorted(directory.glob("*.yaml")):
            try:
                data = _load_yaml(path)
            except Exception as exc:
                logger.warning(
                    "dungeons.loader.yaml_error", path=str(path), error=str(exc)
                )
                continue
            if not data or "key" not in data:
                continue
            if data.get("overlay_of"):
                overlays.append(data)
            else:
                raw_by_key[data["key"]] = data

        for overlay in overlays:
            base_key = overlay["overlay_of"]
            base = raw_by_key.get(base_key)
            if base is None:
                logger.warning(
                    "dungeons.loader.overlay_missing_base",
                    overlay=overlay.get("key"),
                    base=base_key,
                )
                continue
            merged = _merge(base, overlay)
            try:
                dungeon = _build_dungeon(merged)
            except Exception as exc:
                logger.warning(
                    "dungeons.loader.build_failed",
                    key=overlay.get("key"),
                    error=str(exc),
                )
                continue
            self._register(dungeon)

        for raw in raw_by_key.values():
            try:
                dungeon = _build_dungeon(raw)
            except Exception as exc:
                logger.warning(
                    "dungeons.loader.build_failed",
                    key=raw.get("key"),
                    error=str(exc),
                )
                continue
            self._register(dungeon)

        logger.info("dungeons.loader.loaded", count=len(self._all))
        return len(self._all)

    def _register(self, dungeon: Dungeon) -> None:
        key = (dungeon.map_id, dungeon.difficulty, dungeon.sub_zone)
        self._by_key[key] = dungeon
        self._all.append(dungeon)

    def all(self) -> list[Dungeon]:
        return list(self._all)

    def lookup(
        self,
        map_id: int,
        difficulty: Difficulty = Difficulty.NORMAL,
        sub_zone: Optional[str] = None,
    ) -> Optional[Dungeon]:
        """Exact match first, then fall back to sub_zone=None default."""
        exact = self._by_key.get((map_id, difficulty, sub_zone))
        if exact is not None:
            return exact
        if sub_zone is not None:
            return self._by_key.get((map_id, difficulty, None))
        return None


_shared_registry: Optional[DungeonRegistry] = None


def get_registry() -> DungeonRegistry:
    """Return a process-wide registry, loading on first use."""
    global _shared_registry
    if _shared_registry is None:
        reg = DungeonRegistry()
        reg.load_dir()
        _shared_registry = reg
    return _shared_registry


def reset_registry() -> None:
    """Test hook — force the next ``get_registry`` call to reload."""
    global _shared_registry
    _shared_registry = None
