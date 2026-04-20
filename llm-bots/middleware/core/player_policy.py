"""Process-wide policy cache exposing per-bot runtime toggles.

The party logoff checker refreshes this cache on every scheduled tick so
``BotAgent.handle_event`` can answer "may I call the LLM for this bot?"
synchronously without hitting MySQL on the critical path.

Two flags are tracked per bot:

  * ``llm_disabled`` — the human owner flipped ``llm_enabled`` off on
    their ``player_settings`` row (or bots are globally disabled for
    them).  Used to suppress LLM calls; the classic playerbot AI keeps
    running.
  * ``bot_disabled`` — the owner flipped ``bots_enabled`` off.  The
    party logoff checker will force those bots offline; agents also
    skip invocation while the flag is set.
"""

from __future__ import annotations

import threading

_llm_disabled_bots: set[int] = set()
_bot_disabled_bots: set[int] = set()
_lock = threading.Lock()


def is_llm_disabled(bot_guid: int) -> bool:
    with _lock:
        return bot_guid in _llm_disabled_bots


def is_bot_disabled(bot_guid: int) -> bool:
    with _lock:
        return bot_guid in _bot_disabled_bots


def update(
    *,
    llm_disabled: set[int],
    bot_disabled: set[int],
) -> None:
    with _lock:
        _llm_disabled_bots.clear()
        _llm_disabled_bots.update(llm_disabled)
        _bot_disabled_bots.clear()
        _bot_disabled_bots.update(bot_disabled)


def snapshot() -> dict[str, set[int]]:
    """Return a shallow copy of the current cache — used by tests."""
    with _lock:
        return {
            "llm_disabled": set(_llm_disabled_bots),
            "bot_disabled": set(_bot_disabled_bots),
        }
