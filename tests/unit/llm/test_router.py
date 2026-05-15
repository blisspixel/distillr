# pyright: strict
"""Property and unit tests for the router dispatch module.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.router import (
    WORKLOAD_TAGS,
    ConfigurationError,
    LLM_Response,
    RouterConfig,
    _provider_cache,
    call,
)
from distill.llm.telemetry import top_n_by_tokens

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KNOWN_TAGS: list[str] = sorted(WORKLOAD_TAGS)


def _make_config(ops_dir: str = "", **overrides: str) -> RouterConfig:
    """Build a RouterConfig with a fake xai key and optional overrides."""
    defaults: dict[str, str] = {"xai_api_key": "test-key-123"}
    defaults.update(overrides)
    return RouterConfig(ops_dir=ops_dir, **defaults)  # type: ignore[arg-type]


def _mock_provider(
    text: str = "response",
    input_tokens: int = 100,
    output_tokens: int = 50,
    model: str = "grok-4.3",
) -> AsyncMock:
    """Create a mock provider whose call() returns a predictable LLM_Response."""
    mock = AsyncMock()
    mock.call.return_value = LLM_Response(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )
    return mock


# ---------------------------------------------------------------------------
# Property 5: Telemetry record emission completeness
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    workload_tag=st.sampled_from(_KNOWN_TAGS),
    input_tokens=st.integers(min_value=0, max_value=1_000_000),
    output_tokens=st.integers(min_value=0, max_value=1_000_000),
    model=st.sampled_from(["grok-4.3", "gemini-3.1-pro", "claude-sonnet-4"]),
)
def test_telemetry_emission_completeness(
    workload_tag: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
) -> None:
    """Feature: llm-router-model-upgrade, Property 5: Telemetry emission completeness

    For any successful LLM call through the Router with a mocked provider,
    the emitted Telemetry_Record has correct model, workload_tag, token counts,
    positive elapsed_seconds, and outcome="success".

    **Validates: Requirements 6.1**
    """
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = str(Path(tmp) / "ops")
        config = _make_config(ops_dir=ops_dir)
        mock_prov = _mock_provider(
            text="ok",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )

        with patch("distill.llm.router._get_provider", return_value=mock_prov):
            result = call(config, workload_tag, "test prompt")

        assert result.model == model

        records = top_n_by_tokens(ops_dir, n=1)
        assert len(records) == 1
        rec = records[0]

        assert rec.model == model
        assert rec.workload_tag == workload_tag
        assert rec.input_tokens == input_tokens
        assert rec.output_tokens == output_tokens
        assert rec.elapsed_seconds >= 0
        assert rec.outcome == "success"


# ---------------------------------------------------------------------------
# Unit tests — router dispatch
# ---------------------------------------------------------------------------


def test_known_workload_resolves_correctly() -> None:
    """Known workload tags resolve and dispatch correctly with mocked provider."""
    config = _make_config()
    mock_prov = _mock_provider()

    with patch("distill.llm.router._get_provider", return_value=mock_prov):
        result = call(config, "analysis", "test prompt")

    assert result.text == "response"
    assert result.input_tokens == 100
    mock_prov.call.assert_called_once()


def test_unknown_workload_tag_logs_warning(caplog: Any) -> None:
    """Unknown workload tag falls back with a warning logged."""
    config = _make_config()
    mock_prov = _mock_provider()

    with (
        patch("distill.llm.router._get_provider", return_value=mock_prov),
        caplog.at_level(logging.WARNING, logger="distill.llm.router"),
    ):
        result = call(config, "nonexistent_tag", "test prompt")

    assert result.text == "response"
    assert "nonexistent_tag" in caplog.text


def test_missing_api_key_raises_configuration_error() -> None:
    """Missing API key raises ConfigurationError with descriptive message."""
    config = RouterConfig(provider="xai", xai_api_key="")

    with pytest.raises(ConfigurationError, match="XAI_API_KEY"):
        call(config, "analysis", "test prompt")


def test_unknown_provider_raises_configuration_error() -> None:
    """Unknown provider name raises ConfigurationError."""
    config = RouterConfig(provider="nonexistent", xai_api_key="key")

    with pytest.raises(ConfigurationError, match="nonexistent"):
        call(config, "analysis", "test prompt")


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_unimplemented_providers_fail_validation(provider: str) -> None:
    """Reserved provider names fail early instead of raising at first LLM call."""
    config = RouterConfig(
        provider=provider,
        anthropic_api_key="test-anthropic",
        openai_api_key="test-openai",
    )

    with pytest.raises(ConfigurationError, match="not implemented"):
        call(config, "analysis", "test prompt")


def test_router_config_defaults_ops_dir_to_library(monkeypatch: Any, tmp_path: Path) -> None:
    """Bare RouterConfig keeps agent task files under library/.distill, not cwd."""
    cwd = tmp_path / "cwd"
    library = tmp_path / "library"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("DISTILL_OUTPUT_DIR", str(library))

    config = RouterConfig(provider="agent")

    assert config.ops_dir == str(library / ".distill")
    assert Path(config.ops_dir).is_absolute()
    assert Path(config.ops_dir) != cwd


def test_telemetry_emitted_on_success() -> None:
    """Telemetry record is emitted on successful call."""
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = str(Path(tmp) / "ops")
        config = _make_config(ops_dir=ops_dir)
        mock_prov = _mock_provider()

        with patch("distill.llm.router._get_provider", return_value=mock_prov):
            call(config, "analysis", "test prompt")

        records = top_n_by_tokens(ops_dir, n=10)
        assert len(records) == 1
        assert records[0].outcome == "success"
        assert records[0].workload_tag == "analysis"


def test_telemetry_emitted_on_error() -> None:
    """Telemetry record is emitted with outcome='error' when provider fails."""
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = str(Path(tmp) / "ops")
        config = _make_config(ops_dir=ops_dir)
        mock_prov = AsyncMock()
        mock_prov.call.side_effect = RuntimeError("API down")

        with (
            patch("distill.llm.router._get_provider", return_value=mock_prov),
            pytest.raises(RuntimeError, match="API down"),
        ):
            call(config, "analysis", "test prompt")

        records = top_n_by_tokens(ops_dir, n=10)
        assert len(records) == 1
        assert records[0].outcome == "error"
        assert records[0].error_type == "RuntimeError"


def test_call_type_and_run_id_passed_to_telemetry() -> None:
    """call_type and run_id are passed through to the telemetry record."""
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = str(Path(tmp) / "ops")
        config = _make_config(ops_dir=ops_dir)
        mock_prov = _mock_provider()

        with patch("distill.llm.router._get_provider", return_value=mock_prov):
            call(
                config,
                "analysis",
                "test prompt",
                call_type="pass1",
                run_id="abc123",
            )

        records = top_n_by_tokens(ops_dir, n=10)
        assert len(records) == 1
        assert records[0].call_type == "pass1"
        assert records[0].run_id == "abc123"


def test_provider_cache_cleared_between_tests() -> None:
    """Verify _provider_cache is accessible for test isolation."""
    # Just verify the cache dict exists and is clearable
    _provider_cache.clear()
    assert len(_provider_cache) == 0
