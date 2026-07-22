# pyright: strict
"""Tests for the provider catalog used by CLI routing UX."""

from __future__ import annotations

import pytest

from distill.llm.provider_catalog import (
    default_model_for_provider,
    infer_cloud_provider_for_model,
    known_models_for_provider,
    normalize_provider_name,
    price_summary,
    validate_provider_route,
)


def test_normalize_provider_aliases() -> None:
    assert normalize_provider_name("Google") == "gemini"
    assert normalize_provider_name("grok") == "xai"
    assert normalize_provider_name("claude") == "anthropic"


def test_normalize_provider_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        normalize_provider_name("azure")


def test_default_models() -> None:
    assert default_model_for_provider("xai") == "grok-4.3"
    assert default_model_for_provider("gemini") == "gemini-3.6-flash"
    assert default_model_for_provider("anthropic") == "claude-sonnet-5"
    assert default_model_for_provider("ollama") == ""


def test_gemini_catalog_includes_new_flash_models() -> None:
    models = known_models_for_provider("gemini")
    assert models[0] == "gemini-3.6-flash"
    assert "gemini-3.5-flash-lite" in models
    assert "gemini-3.5-flash" in models
    assert "deep-research" not in models


def test_infer_cloud_provider_for_model() -> None:
    assert infer_cloud_provider_for_model("gemini-3.6-flash") == "gemini"
    assert infer_cloud_provider_for_model("grok-4.3") == "xai"
    assert infer_cloud_provider_for_model("claude-sonnet-5") == "anthropic"
    assert infer_cloud_provider_for_model("qwen3.5:27b") == ""


def test_validate_provider_route_rejects_cross_family() -> None:
    with pytest.raises(ValueError, match="belongs to provider"):
        validate_provider_route("xai", "gemini-3.6-flash")


def test_validate_provider_route_accepts_matching_pair() -> None:
    assert validate_provider_route("gemini", "gemini-3.5-flash-lite") == (
        "gemini",
        "gemini-3.5-flash-lite",
    )


def test_price_summary_for_catalog_models() -> None:
    assert "1.50" in price_summary("gemini-3.6-flash")
    assert "7.50" in price_summary("gemini-3.6-flash")
    assert "0.30" in price_summary("gemini-3.5-flash-lite")
