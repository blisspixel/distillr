# pyright: strict
"""Provider cache-key helpers that avoid storing raw credentials."""

from __future__ import annotations

import hashlib


def provider_cache_key(
    provider_name: str,
    *,
    ops_dir: str,
    xai_api_key: str,
    gemini_api_key: str,
    anthropic_api_key: str,
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
    }
    secret = secrets.get(provider_name)
    if secret is None:
        return provider_name
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16] if secret else "none"
    return f"{provider_name}:{digest}"
