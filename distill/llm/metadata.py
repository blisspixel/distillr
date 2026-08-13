# pyright: strict
"""Provider metadata — context window resolution and provider classification.

Provides ProviderMetadata for the pipeline to make chunking decisions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from distill.llm._parsing import parse_ascii_uint

__all__ = [
    "LOCAL_CALL_TIMEOUT_MAX",
    "LOCAL_PROVIDERS",
    "ProviderMetadata",
    "local_call_timeout",
    "resolve_metadata",
    "resolve_metadata_for_router",
    "resolve_metadata_sync",
]

# Known cloud context windows (documented values, in tokens)
CLOUD_CONTEXT_WINDOWS: dict[str, int] = {
    "grok-4.5": 500_000,
    "grok-4.3": 1_000_000,
    "grok-4.20-non-reasoning": 131_072,
    "grok-4.20-0309-reasoning": 131_072,
    "grok-4.20": 131_072,
    "gemini-3.6-flash": 1_000_000,
    "gemini-3.5-flash": 1_000_000,
    "gemini-3.5-flash-lite": 1_000_000,
    "gemini-3.1-pro": 1_000_000,
    "gemini-3.1-flash": 1_000_000,
    "claude-fable-5": 1_000_000,
    "claude-mythos-5": 1_000_000,
    "claude-opus-5": 1_000_000,
    # Recent Opus 4 releases are also 1M-context. Without these entries an Opus
    # route falls back to DEFAULT_CONTEXT_WINDOW (4096) and over-chunks input.
    "claude-opus-4-8": 1_000_000,
    "claude-opus-4-7": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "claude-sonnet-5": 1_000_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-haiku-4": 200_000,
    "gpt-5.6-sol": 1_050_000,
    "gpt-5.6-terra": 1_050_000,
    "gpt-5.6-luna": 1_050_000,
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 128_000,
}

LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "lmstudio"})

# Default when cloud model is unknown
DEFAULT_CONTEXT_WINDOW: int = 4096

# Conservative local fallback when Ollama/LM Studio is configured but unreachable.
# Modern local models commonly expose 32k+; prefer multipass only when needed.
LOCAL_FALLBACK_CONTEXT_WINDOW: int = 32_768

# Idle (stall) timeout floor for a single local-provider call, in seconds. The
# Ollama provider streams its response and applies this as a per-read timeout, so
# it fires only when generation stalls (no new tokens for this long) rather than
# capping a legitimately slow-but-progressing analysis. It is well above the
# cloud-tuned default because a busy local GPU can pause tens of seconds between
# tokens, and prompt prefill on a large paper produces no tokens for a while.
LOCAL_CALL_TIMEOUT_FLOOR: int = 600
LOCAL_CALL_TIMEOUT_MAX: int = 86_400


def local_call_timeout(default: int) -> int:
    """Idle/stall timeout (seconds) for a local-provider call.

    Returns the larger of ``default`` and :data:`LOCAL_CALL_TIMEOUT_FLOOR`, unless
    ``DISTILL_LOCAL_TIMEOUT`` is set to a positive integer, which overrides both.
    Under streaming (the Ollama provider) this bounds inter-token idle time, not
    total generation time, so a slow analysis completes as long as it keeps
    producing tokens; a genuinely stalled call fails after one idle window.
    """
    raw = os.environ.get("DISTILL_LOCAL_TIMEOUT", "").strip()
    configured = parse_ascii_uint(raw)
    if configured is not None and 0 < configured <= LOCAL_CALL_TIMEOUT_MAX:
        return configured
    return min(max(default, LOCAL_CALL_TIMEOUT_FLOOR), LOCAL_CALL_TIMEOUT_MAX)


@dataclass(frozen=True)
class ProviderMetadata:
    """Metadata about a provider+model combination."""

    context_window: int  # max tokens
    provider_type: str  # "local" or "cloud"
    provider_name: str  # "ollama", "lmstudio", "xai", etc.


def resolve_metadata_for_router(
    config: Any,
    workload_tag: str = "site",
) -> ProviderMetadata:
    """Resolve metadata for a router config and workload tag."""
    provider_name, model_id = config.resolve(workload_tag)
    provider: Any = None
    try:
        from distill.llm.router import get_provider

        provider = get_provider(provider_name, config)
    except Exception:
        provider = None
    return resolve_metadata_sync(provider_name, model_id, provider=provider)


def resolve_metadata_sync(
    provider_name: str,
    model: str,
    *,
    provider: Any = None,
) -> ProviderMetadata:
    """Sync metadata resolution for pipeline code that cannot await.

    Cloud lookups are synchronous. Local providers query ``get_context_window``
    through a portable sync bridge when a provider instance is available.
    """
    from distill.llm.async_compat import run_coroutine_sync

    provider_type = "local" if provider_name in LOCAL_PROVIDERS else "cloud"

    if provider_name in LOCAL_PROVIDERS and provider is not None:
        if hasattr(provider, "get_context_window"):
            try:
                context_window = run_coroutine_sync(provider.get_context_window(model))
            except (ConnectionError, OSError, Exception):
                context_window = LOCAL_FALLBACK_CONTEXT_WINDOW
        else:
            context_window = LOCAL_FALLBACK_CONTEXT_WINDOW
    elif provider_name in LOCAL_PROVIDERS:
        context_window = LOCAL_FALLBACK_CONTEXT_WINDOW
    else:
        context_window = _resolve_cloud_context_window(model)

    return ProviderMetadata(
        context_window=context_window,
        provider_type=provider_type,
        provider_name=provider_name,
    )


async def resolve_metadata(
    provider_name: str,
    model: str,
    provider: Any = None,
) -> ProviderMetadata:
    """Resolve metadata for a provider+model combination.

    For local providers, queries the provider for context window (cached).
    For cloud providers, looks up from the known table.
    """
    provider_type = "local" if provider_name in LOCAL_PROVIDERS else "cloud"

    if provider_name in LOCAL_PROVIDERS and provider is not None:
        if hasattr(provider, "get_context_window"):
            try:
                context_window = await provider.get_context_window(model)
            except (ConnectionError, OSError, Exception):
                context_window = LOCAL_FALLBACK_CONTEXT_WINDOW
        else:
            context_window = LOCAL_FALLBACK_CONTEXT_WINDOW
    elif provider_name in LOCAL_PROVIDERS:
        context_window = LOCAL_FALLBACK_CONTEXT_WINDOW
    else:
        context_window = _resolve_cloud_context_window(model)

    return ProviderMetadata(
        context_window=context_window,
        provider_type=provider_type,
        provider_name=provider_name,
    )


def _resolve_cloud_context_window(model: str) -> int:
    """Look up context window for a cloud model. Supports prefix matching."""
    # Catalog keys are lowercase; normalize so a differently-cased model id does
    # not silently fall back to the smaller default window and over-chunk input.
    normalized = model.strip().lower()
    if normalized in CLOUD_CONTEXT_WINDOWS:
        return CLOUD_CONTEXT_WINDOWS[normalized]
    # Prefix match, longest key first so a broad alias cannot shadow a more
    # specific one (``gpt-4.1`` at 1M would otherwise swallow ``gpt-4.1-mini``
    # at 128k and size chunks to a window the model does not have). This mirrors
    # the ordering ``get_pricing`` already relies on.
    for key in sorted(CLOUD_CONTEXT_WINDOWS, key=len, reverse=True):
        if normalized.startswith(key):
            return CLOUD_CONTEXT_WINDOWS[key]
    return DEFAULT_CONTEXT_WINDOW
