"""Shared model→provider inference for the eval package.

Lives in its own module so both ``judge`` and ``harness`` can use it without a
circular import (harness imports judge).
"""

from __future__ import annotations

__all__ = ["LOCAL_PROVIDERS", "is_local", "provider_for_model"]

LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "lmstudio"})


def provider_for_model(model: str) -> str:
    """Infer the provider from a model id (anything unrecognized is treated local)."""
    m = model.lower()
    if m.startswith("grok"):
        return "xai"
    if m.startswith(("gemini", "deep-research")):
        return "gemini"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3")):
        return "openai"
    return "ollama"


def is_local(model: str) -> bool:
    return provider_for_model(model) in LOCAL_PROVIDERS
