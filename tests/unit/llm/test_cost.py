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
    expected = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    assert compute_cost(model, input_tokens, output_tokens) == expected


# ---------------------------------------------------------------------------
# Unit tests — cost registry
# ---------------------------------------------------------------------------


def test_all_listed_models_return_correct_pricing() -> None:
    """Every model in PRICING is retrievable via get_pricing with exact match."""
    for model, expected_rates in PRICING.items():
        if model == "claude-sonnet-5":
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

    result2 = get_pricing("gemini-3.1-pro-latest")
    assert result2 == PRICING["gemini-3.1-pro"]


@pytest.mark.parametrize(
    "model,expected_input,expected_output",
    [
        ("grok-4.3", 1.25, 2.50),
        ("grok-4-1-fast-reasoning", 0.20, 0.50),
        ("grok-4.20-0309-reasoning", 2.00, 6.00),
        ("grok-4.20", 2.00, 6.00),
        ("gemini-3.1-pro", 2.00, 12.00),
        ("gemini-3.1-flash", 0.25, 1.50),
        ("claude-sonnet-5", 2.00, 10.00),
        ("claude-sonnet-4", 3.00, 15.00),
        ("claude-haiku-4", 0.80, 4.00),
        ("gpt-4.1", 2.00, 8.00),
        ("gpt-4.1-mini", 0.40, 1.60),
    ],
)
def test_per_token_model_rates(model: str, expected_input: float, expected_output: float) -> None:
    """Each per-token model has the correct input and output rates."""
    rates = get_pricing(model)
    assert rates["input"] == expected_input
    assert rates["output"] == expected_output


def test_sonnet5_standard_pricing_after_intro_period(monkeypatch: pytest.MonkeyPatch) -> None:
    import distill.llm.cost as cost_mod

    monkeypatch.setattr(cost_mod, "_pricing_reference_date", lambda: date(2026, 9, 1))

    rates = get_pricing("claude-sonnet-5")
    assert rates["input"] == 3.00
    assert rates["output"] == 15.00
    assert compute_cost("claude-sonnet-5", 1_000_000, 1_000_000) == 18.0


def test_deep_research_query_cost_model_aware() -> None:
    from distill.llm.cost import deep_research_query_cost

    assert deep_research_query_cost("deep-research-preview-04-2026") == 2.50
    assert deep_research_query_cost("deep-research-max-preview-04-2026") == 5.00
    assert deep_research_query_cost() == 2.50  # default standard estimate


def test_transcription_cost() -> None:
    from distill.llm.cost import transcription_cost

    assert transcription_cost("xai-grok-stt", 3600.0) == 0.10
    assert round(transcription_cost("whisper-1", 1800.0), 4) == 0.18
    assert transcription_cost("local", 3600.0) == 0.0
    assert transcription_cost("unknown-provider", 3600.0) == 0.0
