"""Loads personality profiles from YAML files and database overrides."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()

_PROFILES_DIR = Path(__file__).parent / "profiles"

# Cache loaded profiles in memory
_cache: dict[str, dict] = {}

# DB-sourced overrides pushed in by ``admin.personality_service`` on
# startup and after every upsert/delete. When a name is present here,
# the returned dict is merged on top of the on-disk YAML.
_db_overrides: dict[str, dict] = {}


def set_db_override(name: str, data: dict | None) -> None:
    """Install or clear the DB override for ``name`` and bust the cache."""
    if data is None:
        _db_overrides.pop(name, None)
    else:
        _db_overrides[name] = data
    _cache.pop(name, None)


def clear_db_overrides() -> None:
    _db_overrides.clear()
    _cache.clear()


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_profile(personality_name: str) -> dict:
    """Load a personality profile by name.

    Falls back to ``base.yaml`` if the named profile doesn't exist.
    Profiles are cached after first load.
    """
    if personality_name in _cache:
        return _cache[personality_name]

    profile_path = _PROFILES_DIR / f"{personality_name}.yaml"
    base_path = _PROFILES_DIR / "base.yaml"

    base = _load_yaml(base_path) if base_path.exists() else {}

    if profile_path.exists() and profile_path != base_path:
        override = _load_yaml(profile_path)
        merged = {**base, **override}
    elif personality_name in _db_overrides:
        # DB-only profile (no YAML on disk yet) — built straight off base.
        merged = {**base}
    else:
        merged = base
        if personality_name != "base" and personality_name != "default":
            logger.warning(
                "personality.not_found_using_base", personality=personality_name
            )

    db_override = _db_overrides.get(personality_name)
    if db_override:
        merged = {**merged, **db_override}

    _cache[personality_name] = merged
    return merged


def reload_profile(personality_name: str) -> dict:
    """Force-reload a profile (for hot-swap via admin API)."""
    _cache.pop(personality_name, None)
    return load_profile(personality_name)


def list_profiles() -> list[str]:
    """List all available personality profile names (YAML + DB overrides)."""
    names = {p.stem for p in _PROFILES_DIR.glob("*.yaml")}
    names.update(_db_overrides.keys())
    return sorted(names)
