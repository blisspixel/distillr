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
    pricing_audit_for_provider,
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
    assert default_model_for_provider("xai") == "grok-4.6"
    assert default_model_for_provider("gemini") == "gemini-3.7-flash"
    assert default_model_for_provider("anthropic") == "claude-sonnet-5"
    assert default_model_for_provider("ollama") == ""


def test_gemini_catalog_includes_new_flash_models() -> None:
    models = known_models_for_provider("gemini")
    assert models[0] == "gemini-3.7-flash"
    assert "gemini-3.6-flash" in models
    assert "gemini-3.5-flash-lite" in models
    assert "gemini-3.5-flash" in models
    assert "gemini-3.1-pro-preview" in models
    assert "gemini-3.1-pro" not in models
    assert "deep-research" not in models


def test_current_xai_and_anthropic_models_are_catalogued() -> None:
    xai_models = known_models_for_provider("xai")
    anthropic_models = known_models_for_provider("anthropic")

    assert xai_models[0] == "grok-4.6"
    assert "grok-4.5" in xai_models
    assert "grok-4.3" in xai_models
    assert "grok-4.20-0309-non-reasoning" in xai_models
    assert "grok-4.20-non-reasoning" not in xai_models
    assert "claude-fable-5" in anthropic_models
    assert "claude-opus-5" in anthropic_models
    assert "claude-sonnet-5" in anthropic_models


def test_infer_cloud_provider_for_model() -> None:
    assert infer_cloud_provider_for_model("gemini-3.7-flash") == "gemini"
    assert infer_cloud_provider_for_model("gemini-3.6-flash") == "gemini"
    assert infer_cloud_provider_for_model("grok-4.6") == "xai"
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
    from distill.llm.cost import get_pricing

    rates = get_pricing("gemini-3.6-flash")
    summary = price_summary("gemini-3.6-flash")
    assert f"{rates['input']:.2f}" in summary
    assert f"{rates['output']:.2f}" in summary
    assert "0.30" in price_summary("gemini-3.5-flash-lite")
    assert "200,000+" in price_summary("grok-4.6")
    assert "$4.00/$12.00" in price_summary("grok-4.6")


@pytest.mark.parametrize("provider", ["xai", "gemini", "anthropic"])
def test_routable_cloud_catalogs_have_auditable_pricing_sources(provider: str) -> None:
    audit = pricing_audit_for_provider(provider)
    assert audit["verified_on"] == "2026-08-13"
    assert audit["source"].startswith("https://")


def test_local_and_host_routes_do_not_claim_vendor_pricing_sources() -> None:
    assert pricing_audit_for_provider("ollama") == {}
    assert pricing_audit_for_provider("lmstudio") == {}
    assert pricing_audit_for_provider("agent") == {}
