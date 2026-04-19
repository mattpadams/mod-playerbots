"""LLM provider factory.

Select a provider via the ``LLM_PROVIDER`` environment variable
(default: ``claude``).  Override the model with ``LLM_MODEL``.
"""
from __future__ import annotations

import os

from providers.base import LLMProvider

_PROVIDER_DEFAULTS: dict[str, str] = {
    "claude": "claude-sonnet-4-6",
}


def get_default_model(provider_name: str | None = None) -> str:
    """Return the model to use, respecting ``LLM_MODEL`` env override."""
    explicit = os.environ.get("LLM_MODEL")
    if explicit:
        return explicit
    name = provider_name or os.environ.get("LLM_PROVIDER", "claude")
    return _PROVIDER_DEFAULTS.get(name, "claude-sonnet-4-6")


def get_provider() -> LLMProvider:
    name = os.environ.get("LLM_PROVIDER", "claude").lower()

    if name == "claude":
        from providers.claude import ClaudeProvider
        return ClaudeProvider()

    raise ValueError(
        f"Unknown LLM provider: {name!r}. "
        f"Supported: {', '.join(_PROVIDER_DEFAULTS)}"
    )
