# pyright: strict
"""Provider cache-key helpers that avoid storing raw credentials."""

from __future__ import annotations

import hashlib
from typing import Any


def build_openrouter(api_key: str, *, zdr: bool) -> Any:
    """Construct the optional provider without extending the router factory."""

    from distill.llm.providers.openrouter import OpenRouterProvider

    return OpenRouterProvider(api_key, zdr=zdr)


def provider_cache_key(
    provider_name: str,
    *,
    ops_dir: str,
    xai_api_key: str,
    gemini_api_key: str,
    anthropic_api_key: str,
    openrouter_api_key: str = "",
    openrouter_zdr: bool = True,
    local_endpoint: str = "",
) -> str:
    """Return a provider cache key without embedding raw credentials."""
    if provider_name == "agent":
        return f"{provider_name}:{ops_dir}"
    if provider_name in {"ollama", "lmstudio"}:
        digest = hashlib.sha256(local_endpoint.encode("utf-8")).hexdigest()[:16]
        return f"{provider_name}:{digest}"
    secrets = {
        "xai": xai_api_key,
        "gemini": gemini_api_key,
        "anthropic": anthropic_api_key,
        "openrouter": openrouter_api_key,
    }
    secret = secrets.get(provider_name)
    if secret is None:
        return provider_name
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16] if secret else "none"
    suffix = f":zdr={str(openrouter_zdr).lower()}" if provider_name == "openrouter" else ""
    return f"{provider_name}:{digest}{suffix}"
