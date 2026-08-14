# pyright: strict
"""Known analysis providers and selectable model catalog for CLI routing.

The pricing table remains the cost source of truth. This module projects a
human-facing catalog of routes Distill can configure for analysis work.
"""

from __future__ import annotations

from distill.llm.cost import (
    PRICING,
    PRICING_SOURCE_URLS,
    PRICING_VERIFIED_ON,
    get_pricing,
)
from distill.llm.model_policy import RETIRED_MODELS, is_xai_media_generation_model

_CLOUD_MODEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("grok-", "xai"),
    ("gemini-", "gemini"),
    ("deep-research", "gemini"),
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
)

__all__ = [
    "DEFAULT_MODEL_FOR_PROVIDER",
    "PROVIDER_HELP",
    "ROUTABLE_PROVIDERS",
    "default_model_for_provider",
    "infer_cloud_provider_for_model",
    "known_models_for_provider",
    "normalize_provider_name",
    "price_summary",
    "pricing_audit_for_provider",
    "validate_provider_route",
]

ROUTABLE_PROVIDERS: tuple[str, ...] = (
    "xai",
    "gemini",
    "anthropic",
    "ollama",
    "lmstudio",
    "agent",
)

PROVIDER_HELP: dict[str, str] = {
    "xai": "xAI Grok cloud API (default)",
    "gemini": "Google Gemini cloud API",
    "anthropic": "Anthropic Claude API (metered opt-in)",
    "ollama": "Local Ollama server (loopback)",
    "lmstudio": "Local LM Studio server (loopback)",
    "agent": "Deferred host-session worker (host-managed billing)",
}

DEFAULT_MODEL_FOR_PROVIDER: dict[str, str] = {
    "xai": "grok-4.6",
    "gemini": "gemini-3.7-flash",
    "anthropic": "claude-sonnet-5",
}

_PROVIDER_MODEL_PREFIXES: dict[str, tuple[str, ...]] = {
    "xai": ("grok-",),
    "gemini": ("gemini-",),
    "anthropic": ("claude-",),
}

_CATALOG_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "deep-research",
    "gemini-deep-research",
    "gpt-",
)

_CATALOG_EXCLUDED_IDS: frozenset[str] = frozenset(
    {
        # Compatibility-only alias. Google's current public model id includes
        # the preview suffix, so do not offer the shorter historical spelling.
        "gemini-3.1-pro",
        # Compatibility-only spelling retained for older Distill configs. The
        # current xAI slug includes the dated 0309 segment.
        "grok-4.20-non-reasoning",
    }
)


def normalize_provider_name(provider: str) -> str:
    """Return a normalized routable provider id or raise ``ValueError``."""
    name = provider.strip().lower()
    aliases = {
        "google": "gemini",
        "grok": "xai",
        "claude": "anthropic",
    }
    name = aliases.get(name, name)
    if name not in ROUTABLE_PROVIDERS:
        valid = ", ".join(ROUTABLE_PROVIDERS)
        raise ValueError(f"Unknown provider '{provider}'. Choose: {valid}.")
    return name


def default_model_for_provider(provider: str) -> str:
    """Default analysis model for a cloud provider, or empty for local/agent."""
    return DEFAULT_MODEL_FOR_PROVIDER.get(normalize_provider_name(provider), "")


def _cloud_provider_for_model(model: str) -> str:
    normalized = model.strip().casefold()
    for prefix, provider in _CLOUD_MODEL_PREFIXES:
        if normalized.startswith(prefix):
            return provider
    return ""


def infer_cloud_provider_for_model(model: str) -> str:
    """Infer xai/gemini/anthropic from a known cloud model id; else empty."""
    expected = _cloud_provider_for_model(model)
    if expected in {"xai", "gemini", "anthropic"}:
        return expected
    return ""


def known_models_for_provider(provider: str) -> list[str]:
    """Return catalog model ids for *provider* (cloud registry only)."""
    name = normalize_provider_name(provider)
    prefixes = _PROVIDER_MODEL_PREFIXES.get(name)
    if not prefixes:
        return []

    models: list[str] = []
    for model_id in PRICING:
        if model_id in _CATALOG_EXCLUDED_IDS:
            continue
        if model_id in RETIRED_MODELS:
            continue
        if is_xai_media_generation_model(model_id):
            continue
        if any(model_id.startswith(prefix) for prefix in _CATALOG_EXCLUDED_PREFIXES):
            continue
        if not model_id.startswith(prefixes):
            continue
        models.append(model_id)

    preferred = default_model_for_provider(name)
    models.sort(key=lambda item: (0 if item == preferred else 1, item))
    return models


def price_summary(model: str) -> str:
    """Short human price string for a catalog model."""
    rates = get_pricing(model)
    if "per_query" in rates:
        return f"~${rates['per_query']:.2f}/query"
    input_rate = rates.get("input", 0.0)
    output_rate = rates.get("output", 0.0)
    summary = f"${input_rate:.2f}/${output_rate:.2f} per 1M"
    threshold = rates.get("long_context_min_input")
    if threshold is None:
        return summary
    long_input = rates.get("long_input", input_rate)
    long_output = rates.get("long_output", output_rate)
    return f"{summary}; ${long_input:.2f}/${long_output:.2f} at {int(threshold):,}+ prompt tokens"


def pricing_audit_for_provider(provider: str) -> dict[str, str]:
    """Return the registry review date and authoritative source for a provider."""

    name = normalize_provider_name(provider)
    source = PRICING_SOURCE_URLS.get(name, "")
    if not source:
        return {}
    return {"verified_on": PRICING_VERIFIED_ON, "source": source}


def validate_provider_route(provider: str, model: str) -> tuple[str, str]:
    """Normalize and validate a provider+model pair for configuration."""
    name = normalize_provider_name(provider)
    model_id = model.strip()
    if not model_id:
        raise ValueError("Model id is required.")
    if model_id != model_id.strip() or len(model_id) > 512:
        raise ValueError("The configured model identifier is invalid.")
    if any(ord(character) < 32 or ord(character) == 127 for character in model_id):
        raise ValueError("The configured model identifier is invalid.")

    if is_xai_media_generation_model(model_id):
        from distill.llm.model_policy import xai_media_generation_refusal

        raise ValueError(xai_media_generation_refusal(model_id))

    expected = _cloud_provider_for_model(model_id)
    if expected == "openai":
        raise ValueError(
            "Provider 'openai' is not implemented yet. "
            "Use xai, gemini, anthropic, agent, ollama, or lmstudio."
        )
    if name in {"xai", "gemini", "anthropic"} and expected and expected != name:
        raise ValueError(f"Model '{model_id}' belongs to provider '{expected}', not '{name}'.")
    return name, model_id
