# pyright: strict
"""Deterministic policy for OpenRouter model identifiers."""

from __future__ import annotations

import re

_CONCRETE_MODEL_RE = re.compile(r"[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*")
_MOVING_ALIAS_SUFFIXES = ("-latest",)


def validate_openrouter_model_id(model: str) -> str:
    """Return one concrete OpenRouter model slug or raise ``ValueError``.

    Distill records and evaluates a stable model identity. OpenRouter router
    models, moving aliases, and endpoint variants can change the selected model
    or billing semantics between calls, so the first adapter deliberately
    requires an exact ``author/model`` slug.
    """

    if model != model.strip() or not model:
        raise ValueError("OpenRouter requires an exact model slug in author/model form.")
    normalized = model.lower()
    if model != normalized or _CONCRETE_MODEL_RE.fullmatch(model) is None:
        raise ValueError(
            "OpenRouter requires a lowercase concrete model slug in author/model form."
        )
    if normalized.startswith("openrouter/"):
        raise ValueError("OpenRouter router models are not calibrated Distill routes.")
    if normalized.endswith(_MOVING_ALIAS_SUFFIXES):
        raise ValueError("OpenRouter moving model aliases are not calibrated Distill routes.")
    from distill.llm.model_policy import is_xai_media_generation_model, xai_media_generation_refusal

    if is_xai_media_generation_model(underlying_model_id(normalized)):
        raise ValueError(xai_media_generation_refusal(model))
    return model


def underlying_model_id(model: str) -> str:
    """Map known OpenRouter author slugs to Distill's direct model ids."""

    normalized = model.strip().lower()
    if "/" not in normalized:
        return normalized
    author, slug = normalized.split("/", 1)
    if author in {"anthropic", "google", "openai", "x-ai"}:
        return slug
    return normalized
