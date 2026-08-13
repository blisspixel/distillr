# pyright: strict
"""Property and unit tests for the Grok 4.3 migration.

Covers:
- Property 14: No defaults reference retired models
- Property 13: Retired model fallback with deprecation warning
- Property 15: Retired models retain cost table entries
- Property 16: Doctor output identifies retired models with required details
- Property 17: Per-workload reasoning effort override
- Unit tests for deprecation warning and fallback logic
- Unit tests for reasoning effort defaults and cost invariance
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.config import DistillConfig
from distill.doctor.checks import check_retired_models
from distill.llm.cost import PRICING, compute_cost, get_pricing
from distill.llm.reasoning import resolve_xai_reasoning_effort
from distill.llm.router import (
    RETIRED_MODELS,
    RETIREMENT_DATE,
    WORKLOAD_TAGS,
    RouterConfig,
)

# =============================================================================
# Property 14: No default model references a retired model
# =============================================================================


@settings(max_examples=100)
@given(workload_tag=st.sampled_from(sorted(WORKLOAD_TAGS)))
def test_no_defaults_reference_retired_models(workload_tag: str) -> None:
    """Property 14: No default model references a retired model.

    For all workload tags, verify default resolution does not return a retired model.

    **Validates: Requirements 14.1, 16.7**
    """
    config = RouterConfig()
    _, model_id = config.resolve(workload_tag)
    assert model_id not in RETIRED_MODELS, (
        f"Default resolution for workload '{workload_tag}' returned retired model '{model_id}'"
    )


# =============================================================================
# Property 13: Retired model fallback with deprecation warning
# =============================================================================


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(retired_model=st.sampled_from(sorted(RETIRED_MODELS.keys())))
def test_retired_model_fallback_with_warning(
    retired_model: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Property 13: Retired model fallback with deprecation warning.

    For any retired model configured, verify router resolves to replacement
    and emits a warning.

    **Validates: Requirements 12.3, 12.6**
    """
    caplog.clear()
    config = RouterConfig(fast_model=retired_model)
    with caplog.at_level(logging.WARNING, logger="distill.llm.router"):
        _, model_id = config.resolve("analysis")

    expected_replacement = RETIRED_MODELS[retired_model]
    assert model_id == expected_replacement, (
        f"Expected replacement '{expected_replacement}' for retired model "
        f"'{retired_model}', got '{model_id}'"
    )
    assert any("retired" in record.message.lower() for record in caplog.records), (
        f"Expected deprecation warning for retired model '{retired_model}'"
    )


# =============================================================================
# Property 15: Retired models retain cost table entries
# =============================================================================


@settings(max_examples=100)
@given(retired_model=st.sampled_from(sorted(RETIRED_MODELS.keys())))
def test_retired_models_retain_cost_entries(retired_model: str) -> None:
    """Property 15: Retired models retain cost table entries.

    For any model in RETIRED_MODELS, verify cost table has pricing entry
    that is an exact match (not a fallback to default).

    **Validates: Requirements 13.3**
    """
    pricing = get_pricing(retired_model)
    # Verify it's an exact match in PRICING (not a fallback)
    assert retired_model in PRICING, (
        f"Retired model '{retired_model}' should have an exact entry in PRICING"
    )
    # Verify it has either input/output keys or per_query key
    has_token_pricing = "input" in pricing and "output" in pricing
    has_query_pricing = "per_query" in pricing
    assert has_token_pricing or has_query_pricing, (
        f"Pricing for '{retired_model}' must have 'input'/'output' or 'per_query' keys, "
        f"got: {pricing}"
    )


# =============================================================================
# Property 16: Doctor output identifies retired models with required details
# =============================================================================


@settings(max_examples=100)
@given(retired_model=st.sampled_from(sorted(RETIRED_MODELS.keys())))
def test_doctor_output_for_retired_models(retired_model: str) -> None:
    """Property 16: Doctor output identifies retired models with required details.

    For any retired model configured, verify warning contains model name,
    date, and replacement.

    **Validates: Requirements 14.2, 14.3**
    """
    # Configure a DistillConfig with the retired model in xai_fast_model
    config = DistillConfig(
        xai_api_key="test-key",
        xai_fast_model=retired_model,
    )
    warnings = check_retired_models(config)

    # Should have at least one warning about this model
    matching_warnings = [w for w in warnings if retired_model in w]
    assert len(matching_warnings) > 0, (
        f"Expected warning for retired model '{retired_model}' in doctor output"
    )

    warning_text = matching_warnings[0]
    # Verify warning contains model name
    assert retired_model in warning_text, f"Warning should contain model name '{retired_model}'"
    # Verify warning contains retirement date
    assert RETIREMENT_DATE in warning_text, (
        f"Warning should contain retirement date '{RETIREMENT_DATE}'"
    )
    # Verify warning contains replacement
    replacement = RETIRED_MODELS[retired_model]
    assert replacement in warning_text, f"Warning should contain replacement '{replacement}'"


# =============================================================================
# Property 17: Per-workload reasoning effort override
# =============================================================================


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    workload_tag=st.sampled_from(sorted(WORKLOAD_TAGS)),
    effort=st.sampled_from(["low", "medium", "high"]),
)
def test_per_workload_reasoning_effort_override(
    workload_tag: str, effort: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Property 17: Per-workload reasoning effort override.

    For any workload and valid effort value set via env var, verify resolved
    effort matches.

    **Validates: Requirements 15.1, 15.2**
    """
    env_key = f"DISTILL_{workload_tag.upper()}_REASONING_EFFORT"
    monkeypatch.setenv(env_key, effort)

    config = RouterConfig()
    result = resolve_xai_reasoning_effort(config, workload_tag)
    assert result == effort, (
        f"Expected reasoning effort '{effort}' for workload '{workload_tag}', got '{result}'"
    )


# =============================================================================
# Unit tests: deprecation warning and fallback logic (Task 16.13)
# =============================================================================


class TestDeprecationWarningAndFallback:
    """Unit tests for deprecation warning and fallback logic."""

    def test_each_retired_model_triggers_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Configuring each retired model triggers a warning log."""
        for retired_model in RETIRED_MODELS:
            caplog.clear()
            config = RouterConfig(fast_model=retired_model)
            with caplog.at_level(logging.WARNING, logger="distill.llm.router"):
                config.resolve("analysis")
            assert any("retired" in r.message.lower() for r in caplog.records), (
                f"No deprecation warning for retired model '{retired_model}'"
            )

    def test_fallback_returns_correct_replacement(self) -> None:
        """Fallback returns the correct replacement for each retired model."""
        for retired_model, expected_replacement in RETIRED_MODELS.items():
            config = RouterConfig(fast_model=retired_model)
            _, model_id = config.resolve("analysis")
            assert model_id == expected_replacement, (
                f"Expected '{expected_replacement}' for '{retired_model}', got '{model_id}'"
            )

    def test_non_retired_models_pass_through(self) -> None:
        """Non-retired models pass through unchanged."""
        non_retired = [
            "grok-4.3",
            "grok-4.20-0309-non-reasoning",
            "grok-imagine-image",
        ]
        for model in non_retired:
            config = RouterConfig(fast_model=model)
            _, model_id = config.resolve("analysis")
            assert model_id == model, (
                f"Non-retired model '{model}' should pass through unchanged, got '{model_id}'"
            )


# =============================================================================
# Unit tests: reasoning effort defaults and cost invariance (Task 16.14)
# =============================================================================


class TestReasoningEffortDefaultsAndCostInvariance:
    """Unit tests for reasoning effort defaults and cost invariance."""

    def test_premium_workloads_default_to_high(self) -> None:
        """Premium workloads (site, report) default to 'high' reasoning effort."""
        config = RouterConfig()
        with patch.dict(os.environ, {}, clear=False):
            # Remove any existing env vars that might interfere
            for tag in ("site", "report"):
                env_key = f"DISTILL_{tag.upper()}_REASONING_EFFORT"
                os.environ.pop(env_key, None)

            for tag in ("site", "report"):
                result = resolve_xai_reasoning_effort(config, tag)
                assert result == "high", (
                    f"Premium workload '{tag}' should default to 'high', got '{result}'"
                )

    def test_fast_tier_workloads_default_to_medium(self) -> None:
        """Fast-tier workloads (analysis, rerank, synthesis) default to 'medium'."""
        config = RouterConfig()
        with patch.dict(os.environ, {}, clear=False):
            for tag in ("analysis", "rerank", "synthesis"):
                env_key = f"DISTILL_{tag.upper()}_REASONING_EFFORT"
                os.environ.pop(env_key, None)

            for tag in ("analysis", "rerank", "synthesis"):
                result = resolve_xai_reasoning_effort(config, tag)
                assert result == "medium", (
                    f"Fast-tier workload '{tag}' should default to 'medium', got '{result}'"
                )

    def test_invalid_env_var_values_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid env var values are ignored (default applies)."""
        config = RouterConfig()
        invalid_values = ["invalid", "EXTREME", "none", "1", ""]
        for invalid in invalid_values:
            monkeypatch.setenv("DISTILL_ANALYSIS_REASONING_EFFORT", invalid)
            result = resolve_xai_reasoning_effort(config, "analysis")
            assert result == "medium", (
                f"Invalid value '{invalid}' should be ignored, expected 'medium', got '{result}'"
            )

    def test_cost_computation_independent_of_reasoning_effort(self) -> None:
        """Cost computation is identical regardless of reasoning effort.

        compute_cost doesn't take effort as a parameter, so cost is purely
        based on model and token counts.
        """
        model = "grok-4.3"
        input_tokens = 1000
        output_tokens = 500

        cost = compute_cost(model, input_tokens, output_tokens)

        # Verify cost is the same value regardless of what reasoning effort
        # would be configured — compute_cost has no effort parameter
        expected = (input_tokens * 1.25 + output_tokens * 2.50) / 1_000_000
        assert cost == pytest.approx(expected), f"Cost should be {expected}, got {cost}"

        # Verify calling multiple times gives same result (no hidden state)
        cost2 = compute_cost(model, input_tokens, output_tokens)
        assert cost == cost2, "Cost computation should be deterministic"
