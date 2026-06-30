# pyright: strict
"""Model capability policy helpers for provider routing."""

from __future__ import annotations

XAI_MEDIA_GENERATION_MODEL_PREFIXES: tuple[str, ...] = (
    "grok-imagine-image",
    "grok-imagine-video",
)

RETIREMENT_DATE = "May 15, 2026"
RETIRED_MODELS: dict[str, str] = {
    "grok-4-1-fast-reasoning": "grok-4.3",
    "grok-4-1-fast-non-reasoning": "grok-4.20-non-reasoning",
    "grok-4-fast-reasoning": "grok-4.3",
    "grok-4-fast-non-reasoning": "grok-4.20-non-reasoning",
    "grok-4-0709": "grok-4.3",
    "grok-code-fast-1": "grok-4.3",
    "grok-3": "grok-4.3",
    "grok-imagine-image-pro": "grok-imagine-image",
}


def is_xai_media_generation_model(model: str) -> bool:
    """Return true for xAI models that belong to media generation APIs."""
    normalized = model.strip().lower()
    return normalized.startswith(XAI_MEDIA_GENERATION_MODEL_PREFIXES)


def xai_media_generation_refusal(model: str) -> str:
    """Explain why a media model cannot be used through Distill's text route."""
    return (
        f"Model '{model}' is an xAI media generation model, not a Distill text "
        "analysis model. Distill does not call xAI image or video generation APIs; "
        "configure an xAI text model such as grok-4.3 for these workloads."
    )
