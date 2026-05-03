# pyright: strict
"""Property and unit tests for the cost registry.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.cost import DEFAULT_MODEL, PRICING, compute_cost, get_pricing

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
    rates = PRICING[model]
    expected = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    assert compute_cost(model, input_tokens, output_tokens) == expected


# ---------------------------------------------------------------------------
# Unit tests — cost registry
# ---------------------------------------------------------------------------


def test_all_listed_models_return_correct_pricing() -> None:
    """Every model in PRICING is retrievable via get_pricing with exact match."""
    for model, expected_rates in PRICING.items():
        assert get_pricing(model) is expected_rates


def test_unknown_model_falls_back_to_default(caplog: Any) -> None:
    """Unknown model falls back to DEFAULT_MODEL pricing and logs a warning."""
    with caplog.at_level(logging.WARNING, logger="distill.llm.cost"):
        result = get_pricing("totally-unknown-model-xyz")
    assert result == PRICING[DEFAULT_MODEL]
    assert "totally-unknown-model-xyz" in caplog.text
    assert DEFAULT_MODEL in caplog.text


def test_per_query_pricing_gemini_deep_research() -> None:
    """gemini-deep-research uses per-query pricing, ignoring token counts."""
    cost = compute_cost("gemini-deep-research", 10_000, 5_000)
    assert cost == 2.50


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
