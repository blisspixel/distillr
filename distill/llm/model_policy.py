# pyright: strict
"""Model capability policy helpers for provider routing."""

from __future__ import annotations

from datetime import UTC, date, datetime

XAI_MEDIA_GENERATION_MODEL_PREFIXES: tuple[str, ...] = (
    "grok-imagine-image",
    "grok-imagine-video",
)

RETIREMENT_DATE = "May 15, 2026"
RETIRED_MODELS: dict[str, str] = {
    "grok-4-1-fast-reasoning": "grok-4.6",
    "grok-4-1-fast-non-reasoning": "grok-4.20-0309-non-reasoning",
    "grok-4-fast-reasoning": "grok-4.6",
    "grok-4-fast-non-reasoning": "grok-4.20-0309-non-reasoning",
    "grok-4-0709": "grok-4.6",
    "grok-code-fast-1": "grok-4.6",
    "grok-3": "grok-4.6",
    "grok-imagine-image-pro": "grok-imagine-image",
}


def scheduled_model_refusal(model: str, *, today: date | None = None) -> str:
    """Gate published shutdown dates without rewriting historical receipts."""
    normalized = model.strip().lower()
    if normalized == "deep-research-pro-preview-12-2025" and (
        today or datetime.now(UTC).date()
    ) >= date(2026, 10, 23):
        return (
            f"Model '{model}' reached its published earliest shutdown date, 2026-10-23. "
            "Use deep-research-preview-04-2026 for the research workflow, or "
            "gemini-3.8-flash for text analysis. Historical receipts remain readable."
        )
    return ""


def is_xai_media_generation_model(model: str) -> bool:
    """Return true for xAI models that belong to media generation APIs."""
    normalized = model.strip().lower()
    return normalized.startswith(XAI_MEDIA_GENERATION_MODEL_PREFIXES)


def xai_media_generation_refusal(model: str) -> str:
    """Explain why a media model cannot be used through Distill's text route."""
    return (
        f"Model '{model}' is an xAI media generation model, not a Distill text "
        "analysis model. Distill does not call xAI image or video generation APIs; "
        "configure an xAI text model such as grok-4.6 for these workloads."
    )
