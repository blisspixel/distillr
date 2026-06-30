# pyright: strict
"""Provider metadata — context window resolution and provider classification.

Provides ProviderMetadata for the pipeline to make chunking decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "LOCAL_PROVIDERS",
    "ProviderMetadata",
    "resolve_metadata",
    "resolve_metadata_for_router",
    "resolve_metadata_sync",
]

# Known cloud context windows (documented values, in tokens)
CLOUD_CONTEXT_WINDOWS: dict[str, int] = {
    "grok-4.3": 1_000_000,
    "grok-4.20-non-reasoning": 131_072,
    "grok-4.20-0309-reasoning": 131_072,
    "grok-4.20": 131_072,
    "gemini-3.5-flash": 1_000_000,
    "gemini-3.1-pro": 1_000_000,
    "gemini-3.1-flash": 1_000_000,
    "claude-sonnet-5": 1_000_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 128_000,
}

LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "lmstudio"})

# Default when cloud model is unknown
DEFAULT_CONTEXT_WINDOW: int = 4096

# Conservative local fallback when Ollama/LM Studio is configured but unreachable.
# Modern local models commonly expose 32k+; prefer multipass only when needed.
LOCAL_FALLBACK_CONTEXT_WINDOW: int = 32_768


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
    if model in CLOUD_CONTEXT_WINDOWS:
        return CLOUD_CONTEXT_WINDOWS[model]
    # Prefix match
    for key, window in CLOUD_CONTEXT_WINDOWS.items():
        if model.startswith(key):
            return window
    return DEFAULT_CONTEXT_WINDOW
