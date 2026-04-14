"""Loads personality profiles from YAML files and database overrides."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()

_PROFILES_DIR = Path(__file__).parent / "profiles"

# Cache loaded profiles in memory
_cache: dict[str, dict] = {}


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
        # Merge: override wins, base fills gaps
        merged = {**base, **override}
    else:
        merged = base
        if personality_name != "base" and personality_name != "default":
            logger.warning(
                "personality.not_found_using_base", personality=personality_name
            )

    _cache[personality_name] = merged
    return merged


def reload_profile(personality_name: str) -> dict:
    """Force-reload a profile (for hot-swap via admin API)."""
    _cache.pop(personality_name, None)
    return load_profile(personality_name)


def list_profiles() -> list[str]:
    """List all available personality profile names."""
    return [p.stem for p in _PROFILES_DIR.glob("*.yaml")]
