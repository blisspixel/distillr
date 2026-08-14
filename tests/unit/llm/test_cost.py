# pyright: strict
"""Property and unit tests for the cost registry.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.cost import (
    DEFAULT_MODEL,
    GEMINI_DEEP_RESEARCH_COST,
    PRICING,
    compute_cost,
    deep_research_query_cost,
    get_pricing,
    transcription_cost,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Models that use per-token pricing (have input/output keys)
_PER_TOKEN_MODELS: list[str] = [m for m, r in PRICING.items() if "input" in r and "output" in r]


# ---------------------------------------------------------------------------
# Property 4: Cost computation correctness
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    model=st.sampled_from(_PER_TOKEN_MODELS),
    input_tokens=st.integers(min_value=0, max_value=50_000_000),
    output_tokens=st.integers(min_value=0, max_value=50_000_000),
)
def test_cost_computation_correctness(model: str, input_tokens: int, output_tokens: int) -> None:
    """Feature: llm-router-model-upgrade, Property 4: Cost computation correctness

    For each model in PRICING with input/output rates, generate non-negative
    token counts and assert compute_cost equals
    (input * rate_in + output * rate_out) / 1_000_000.

    **Validates: Requirements 5.1**
    """
    rates = get_pricing(model)
    input_rate = rates["input"]
    output_rate = rates["output"]
    threshold = rates.get("long_context_min_input")
    if threshold is not None and input_tokens >= threshold:
        input_rate = rates["long_input"]
        output_rate = rates["long_output"]
    expected = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    assert compute_cost(model, input_tokens, output_tokens) == expected


# ---------------------------------------------------------------------------
# Unit tests — cost registry
# ---------------------------------------------------------------------------


def test_all_listed_models_return_correct_pricing() -> None:
    """Every model in PRICING is retrievable via get_pricing with exact match."""
    for model, expected_rates in PRICING.items():
        if model in {"claude-sonnet-5", "gemini-3.6-flash"}:
            rates = get_pricing(model)
            assert set(rates) == set(expected_rates)
            continue
        assert get_pricing(model) == expected_rates


def test_unknown_model_falls_back_to_default(caplog: Any) -> None:
    """Unknown model falls back to DEFAULT_MODEL pricing and logs a warning."""
    with caplog.at_level(logging.WARNING, logger="distill.llm.cost"):
        result = get_pricing("totally-unknown-model-xyz")
    assert result == PRICING[DEFAULT_MODEL]
    assert "totally-unknown-model-xyz" in caplog.text
    assert DEFAULT_MODEL in caplog.text


def test_deep_research_max_variant_not_shadowed_by_standard_alias() -> None:
    """A dated Max variant prices at the Max rate, not the cheaper standard
    'deep-research' alias (longest-prefix-wins + the 'deep-research-max' key)."""
    max_rate = get_pricing("deep-research-max-preview-09-2026")["per_query"]
    std_rate = get_pricing("deep-research-preview-04-2026")["per_query"]
    assert max_rate > std_rate


def test_per_query_pricing_gemini_deep_research() -> None:
    """gemini-deep-research uses per-query pricing, ignoring token counts."""
    cost = compute_cost("gemini-deep-research", 10_000, 5_000)
    assert cost == GEMINI_DEEP_RESEARCH_COST


@pytest.mark.parametrize(
    "model",
    [
        "gemini-deep-research",
        "deep-research",
        "deep-research-pro-preview-12-2025",
    ],
)
def test_deep_research_aliases_use_per_query_pricing(model: str) -> None:
    """All Deep Research aliases resolve to the provider-side per-query estimate."""
    assert compute_cost(model, 10_000, 5_000) == deep_research_query_cost()


def test_prefix_matching_for_versioned_model_names() -> None:
    """Versioned model names (e.g. 'grok-4.3-beta') match the base model."""
    result = get_pricing("grok-4.3-beta")
    assert result == PRICING["grok-4.3"]

    result2 = get_pricing("gemini-3.1-pro-preview-latest")
    assert result2 == PRICING["gemini-3.1-pro-preview"]


@pytest.mark.parametrize(
    "model,expected_input,expected_output",
    [
        ("grok-4.6", 2.00, 6.00),
        ("grok-4.5", 2.00, 6.00),
        ("grok-4.3", 1.25, 2.50),
        ("grok-4-1-fast-reasoning", 0.20, 0.50),
        ("grok-4.20-0309-non-reasoning", 1.25, 2.50),
        ("grok-4.20-0309-reasoning", 1.25, 2.50),
        ("grok-4.20", 1.25, 2.50),
        ("gemini-3.5-flash", 1.50, 9.00),
        ("gemini-3.5-flash-lite", 0.30, 2.50),
        ("gemini-3.1-pro-preview", 2.00, 12.00),
        ("gemini-3.1-pro", 2.00, 12.00),
        ("gemini-3.1-flash", 0.25, 1.50),
        ("claude-fable-5", 10.00, 50.00),
        ("claude-mythos-5", 10.00, 50.00),
        ("claude-opus-5", 5.00, 25.00),
        ("claude-sonnet-4", 3.00, 15.00),
        ("claude-haiku-4-5", 1.00, 5.00),
        ("claude-haiku-4", 0.80, 4.00),
        ("gpt-5.6-sol", 5.00, 30.00),
        ("gpt-5.6-terra", 2.00, 12.00),
        ("gpt-5.6-luna", 0.20, 1.20),
        ("gpt-4.1", 2.00, 8.00),
        ("gpt-4.1-mini", 0.40, 1.60),
    ],
)
def test_per_token_model_rates(model: str, expected_input: float, expected_output: float) -> None:
    """Each per-token model has the correct input and output rates."""
    rates = get_pricing(model)
    assert rates["input"] == expected_input
    assert rates["output"] == expected_output


@pytest.mark.parametrize(
    ("model", "threshold", "short_cost", "long_cost"),
    [
        ("grok-4.6", 200_000, 0.999998, 2.0),
        ("grok-4.3", 200_000, 0.49999875, 1.0),
        ("gemini-3.1-pro-preview", 200_001, 1.6, 2.600004),
        ("gpt-5.6-sol", 272_001, 4.36, 7.22001),
    ],
)
def test_long_context_pricing_starts_at_registered_boundary(
    model: str,
    threshold: int,
    short_cost: float,
    long_cost: float,
) -> None:
    """A single long prompt uses the provider's all-token long-context rate."""

    assert compute_cost(model, threshold - 1, 100_000) == pytest.approx(short_cost)
    assert compute_cost(model, threshold, 100_000) == pytest.approx(long_cost)


def test_sonnet5_standard_pricing_after_intro_period(monkeypatch: pytest.MonkeyPatch) -> None:
    import distill.llm.cost as cost_mod

    monkeypatch.setattr(cost_mod, "_pricing_reference_date", lambda: date(2026, 9, 1))

    rates = get_pricing("claude-sonnet-5")
    assert rates["input"] == 3.00
    assert rates["output"] == 15.00
    assert compute_cost("claude-sonnet-5", 1_000_000, 1_000_000) == 18.0


def test_sonnet5_intro_pricing_before_cutover(monkeypatch: pytest.MonkeyPatch) -> None:
    import distill.llm.cost as cost_mod

    monkeypatch.setattr(cost_mod, "_pricing_reference_date", lambda: date(2026, 8, 13))

    rates = get_pricing("claude-sonnet-5")
    assert rates["input"] == 2.00
    assert rates["output"] == 10.00
    assert compute_cost("claude-sonnet-5", 1_000_000, 1_000_000) == 12.0


def test_gemini36_launch_pricing_before_cutover(monkeypatch: pytest.MonkeyPatch) -> None:
    import distill.llm.cost as cost_mod

    monkeypatch.setattr(cost_mod, "_pricing_reference_date", lambda: date(2026, 8, 13))

    rates = get_pricing("gemini-3.6-flash")
    assert rates["input"] == 0.75
    assert rates["output"] == 3.75
    assert compute_cost("gemini-3.6-flash", 1_000_000, 1_000_000) == 4.5


def test_gemini36_standard_pricing_after_cutover(monkeypatch: pytest.MonkeyPatch) -> None:
    import distill.llm.cost as cost_mod

    monkeypatch.setattr(cost_mod, "_pricing_reference_date", lambda: date(2027, 1, 1))

    rates = get_pricing("gemini-3.6-flash")
    assert rates["input"] == 1.50
    assert rates["output"] == 7.50
    assert compute_cost("gemini-3.6-flash", 1_000_000, 1_000_000) == 9.0


def test_deep_research_query_cost_model_aware() -> None:
    from distill.llm.cost import deep_research_query_cost

    assert deep_research_query_cost("deep-research-preview-04-2026") == 2.50
    assert deep_research_query_cost("deep-research-max-preview-04-2026") == 5.00
    assert deep_research_query_cost() == 2.50  # default standard estimate


def test_transcription_cost() -> None:
    assert transcription_cost("xai-grok-stt", 3600.0) == 0.10
    assert round(transcription_cost("whisper-1", 1800.0), 4) == 0.18
    assert transcription_cost("local", 3600.0) == 0.0
    assert transcription_cost("unknown-provider", 3600.0) == 0.0


@pytest.mark.parametrize(
    "duration",
    [True, -1.0, float("nan"), float("inf"), 10**400],
)
def test_transcription_cost_rejects_invalid_duration(duration: object) -> None:
    with pytest.raises(ValueError, match="transcription duration"):
        transcription_cost("whisper-1", duration)


@pytest.mark.parametrize(
    ("model", "expected_input", "expected_output"),
    [
        ("claude-opus-5", 5.00, 25.00),
        ("claude-opus-4-8", 5.00, 25.00),
        ("claude-opus-4-7", 5.00, 25.00),
        ("claude-opus-4-6", 5.00, 25.00),
    ],
)
def test_opus_tier_is_priced(model: str, expected_input: float, expected_output: float) -> None:
    """Opus must price at its own rate, not fall back to the default model."""
    rates = get_pricing(model)
    assert rates["input"] == expected_input
    assert rates["output"] == expected_output


@pytest.mark.parametrize(
    "model",
    ["Claude-Opus-4-8", "CLAUDE-OPUS-4-8", "  claude-opus-4-8  ", "Gemini-3.6-Flash"],
)
def test_pricing_lookup_is_case_and_whitespace_insensitive(model: str) -> None:
    """A differently-cased model id must not silently fall back to DEFAULT_MODEL.

    Routing case-folds when resolving a provider, so a model id can reach pricing
    in any case. Falling through to the default under-reported Opus spend by 8x,
    which is the dangerous direction for the ledger, budget caps, and projections.
    """
    assert get_pricing(model) == get_pricing(model.strip().lower())
    assert get_pricing(model) != get_pricing(DEFAULT_MODEL) or model.strip().lower().startswith(
        DEFAULT_MODEL
    )
