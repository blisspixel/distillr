# pyright: strict
"""Property and unit tests for the router dispatch module.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm import router as router_module
from distill.llm.router import (
    WORKLOAD_TAGS,
    ConfigurationError,
    LLM_Response,
    RouterConfig,
    call,
    get_provider,
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


def _clear_provider_cache() -> None:
    cache = cast(dict[str, Any], vars(router_module)["_provider_cache"])
    assert isinstance(cache, dict)
    cache.clear()


def _provider_cache_size() -> int:
    cache = cast(dict[str, Any], vars(router_module)["_provider_cache"])
    assert isinstance(cache, dict)
    return len(cache)


@pytest.fixture(autouse=True)
def isolate_provider_cache() -> Iterator[None]:
    _clear_provider_cache()
    yield
    _clear_provider_cache()


# ---------------------------------------------------------------------------
# Property 5: Telemetry record emission completeness
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
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
        assert result.provider_name == "xai"
        assert result.provider_type == "cloud"

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


def test_call_succeeds_inside_running_event_loop() -> None:
    """Regression: ``call`` must work when invoked from an already-running event
    loop (the async MCP server path drives sync pipeline code that calls the
    router). The old nested-loop fallback always raised; ``run_coroutine_sync``
    offloads the provider coroutine to a dedicated thread instead.
    """
    import asyncio

    config = _make_config()
    mock_prov = _mock_provider(text="from-loop")

    async def _driver() -> LLM_Response:
        return call(config, "analysis", "prompt")

    with patch("distill.llm.router._get_provider", return_value=mock_prov):
        result = asyncio.run(_driver())

    assert result.text == "from-loop"
    assert result.provider_name == "xai"


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


def test_xai_media_model_refused_before_provider_call() -> None:
    """xAI media generation models are never sent through the chat route."""
    config = _make_config(model="grok-imagine-image")

    with (
        patch("distill.llm.router._get_provider") as get_provider,
        pytest.raises(ConfigurationError, match="media generation model"),
    ):
        call(config, "analysis", "test prompt")

    get_provider.assert_not_called()


def test_no_metered_blocks_api_billed_route_before_key_validation() -> None:
    """Cost policy fails closed before a cloud route can spend or ask for keys."""
    config = RouterConfig(provider="xai", xai_api_key="test-key", cost_mode="no-metered")

    with pytest.raises(ConfigurationError) as exc_info:
        call(config, "analysis", "test prompt")
    message = str(exc_info.value)
    assert "Blocked provider: xai" in message
    assert "Workload: analysis" in message
    assert "Cost class: metered-api" in message
    assert "paid-ok" in message


def test_no_metered_allows_local_route() -> None:
    """Local inference is allowed by topology under no-metered policy."""
    config = RouterConfig(provider="ollama", cost_mode="no-metered")
    mock_prov = _mock_provider(model="qwen3.5:27b")

    with patch("distill.llm.router._get_provider", return_value=mock_prov):
        result = call(config, "analysis", "test prompt")

    assert result.provider_name == "ollama"
    assert result.provider_type == "local"


def test_no_metered_blocks_unproven_agent_route() -> None:
    """Deferred agent routes need adapter proof before no-metered routing."""
    config = RouterConfig(provider="agent", cost_mode="no-metered")

    with pytest.raises(ConfigurationError) as exc_info:
        call(config, "analysis", "test prompt")
    message = str(exc_info.value)
    assert "Blocked provider: agent" in message
    assert "Cost class: unknown" in message
    assert "unknown billing" in message


def test_no_metered_reports_plan_quota_proof_for_reserved_cli_route() -> None:
    """Reserved CLI route names explain the proof needed before provider validation."""
    config = RouterConfig(provider="codex", cost_mode="no-metered")

    with pytest.raises(ConfigurationError) as exc_info:
        call(config, "analysis", "test prompt")
    message = str(exc_info.value)
    assert "Blocked provider: codex" in message
    assert "Cost class: included-plan" in message
    assert "Required proof: adapter doctor" in message


def test_unknown_provider_raises_configuration_error() -> None:
    """Unknown provider name raises ConfigurationError."""
    config = RouterConfig(provider="nonexistent", xai_api_key="key")

    with pytest.raises(ConfigurationError, match="nonexistent"):
        call(config, "analysis", "test prompt")


@pytest.mark.parametrize("provider", ["openai"])
def test_unimplemented_providers_fail_validation(provider: str) -> None:
    """Reserved provider names fail early instead of raising at first LLM call."""
    config = RouterConfig(
        provider=provider,
        anthropic_api_key="test-anthropic",
        openai_api_key="test-openai",
    )

    with pytest.raises(ConfigurationError, match="not implemented"):
        call(config, "analysis", "test prompt")


def test_anthropic_provider_routes_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic is a live metered route when an API key is explicitly configured."""
    monkeypatch.delenv("DISTILL_ANALYSIS_REASONING_EFFORT", raising=False)
    config = RouterConfig(
        provider="anthropic",
        anthropic_api_key="test-anthropic",
        model="claude-sonnet-5",
    )
    mock_prov = _mock_provider(model="claude-sonnet-5")

    with patch("distill.llm.router._get_provider", return_value=mock_prov):
        result = call(config, "analysis", "test prompt")

    assert result.provider_name == "anthropic"
    assert result.provider_type == "cloud"
    assert result.model == "claude-sonnet-5"
    assert mock_prov.call.call_args.kwargs["reasoning_effort"] is None


def test_anthropic_missing_key_raises_configuration_error() -> None:
    config = RouterConfig(provider="anthropic", anthropic_api_key="")

    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        call(config, "analysis", "test prompt")


def test_anthropic_sonnet5_configured_effort_is_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISTILL_ANALYSIS_REASONING_EFFORT", "xhigh")
    config = RouterConfig(
        provider="anthropic",
        anthropic_api_key="test-anthropic",
        model="claude-sonnet-5",
    )
    mock_prov = _mock_provider(model="claude-sonnet-5")

    with patch("distill.llm.router._get_provider", return_value=mock_prov):
        call(config, "analysis", "test prompt")

    assert mock_prov.call.call_args.kwargs["reasoning_effort"] == "xhigh"


def test_anthropic_invalid_effort_is_not_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISTILL_ANALYSIS_REASONING_EFFORT", "extreme")
    config = RouterConfig(
        provider="anthropic",
        anthropic_api_key="test-anthropic",
        model="claude-sonnet-5",
    )
    mock_prov = _mock_provider(model="claude-sonnet-5")

    with patch("distill.llm.router._get_provider", return_value=mock_prov):
        call(config, "analysis", "test prompt")

    assert mock_prov.call.call_args.kwargs["reasoning_effort"] is None


def test_router_config_defaults_ops_dir_to_library(monkeypatch: Any, tmp_path: Path) -> None:
    """Bare RouterConfig keeps agent task files under library/.distill, not cwd."""
    cwd = tmp_path / "cwd"
    library = tmp_path / "library"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("DISTILL_OPS_DIR", raising=False)
    monkeypatch.setenv("DISTILL_OUTPUT_DIR", str(library))

    config = RouterConfig(provider="agent")

    assert config.ops_dir == str(library / ".distill")
    assert Path(config.ops_dir).is_absolute()
    assert Path(config.ops_dir) != cwd


def test_router_config_defaults_ops_dir_to_repo_library(monkeypatch: Any, tmp_path: Path) -> None:
    """Without an output override, ops_dir defaults to the repo library path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DISTILL_OPS_DIR", raising=False)
    monkeypatch.delenv("DISTILL_OUTPUT_DIR", raising=False)

    config = RouterConfig(provider="agent")

    expected = Path(router_module.__file__).resolve().parent.parent.parent / "library" / ".distill"
    assert Path(config.ops_dir) == expected


def test_router_config_relative_output_dir_becomes_absolute(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Relative DISTILL_OUTPUT_DIR values resolve under the current directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DISTILL_OPS_DIR", raising=False)
    monkeypatch.setenv("DISTILL_OUTPUT_DIR", "library")

    config = RouterConfig(provider="agent")

    assert config.ops_dir == str(tmp_path / "library" / ".distill")


def test_retired_model_resolution_warns_and_replaces(caplog: Any) -> None:
    """Retired model ids are replaced before provider dispatch."""
    config = _make_config(fast_model="grok-3")

    with caplog.at_level(logging.WARNING, logger="distill.llm.router"):
        provider_name, model_id = config.resolve("analysis")

    assert provider_name == "xai"
    assert model_id == "grok-4.3"
    assert "grok-3" in caplog.text
    assert "grok-4.3" in caplog.text


@pytest.mark.parametrize(
    ("provider_name", "patch_target", "expected_arg"),
    [
        ("xai", "distill.llm.providers.grok.GrokProvider", "xai-key"),
        ("gemini", "distill.llm.providers.gemini.GeminiProvider", "gemini-key"),
        ("anthropic", "distill.llm.providers.anthropic.AnthropicProvider", "anthropic-key"),
    ],
)
def test_get_provider_constructs_keyed_providers(
    provider_name: str, patch_target: str, expected_arg: str, tmp_path: Path
) -> None:
    """Provider factory passes configured API keys to cloud provider classes."""
    provider_instance = object()
    config = RouterConfig(
        provider=provider_name,
        xai_api_key="xai-key",
        gemini_api_key="gemini-key",
        anthropic_api_key="anthropic-key",
        ops_dir=str(tmp_path / "ops"),
    )

    with patch(patch_target, return_value=provider_instance) as provider_cls:
        provider = get_provider(provider_name, config)

    assert provider is provider_instance
    provider_cls.assert_called_once_with(expected_arg)


@pytest.mark.parametrize(
    ("provider_name", "patch_target", "key_field"),
    [
        ("xai", "distill.llm.providers.grok.GrokProvider", "xai_api_key"),
        ("gemini", "distill.llm.providers.gemini.GeminiProvider", "gemini_api_key"),
        (
            "anthropic",
            "distill.llm.providers.anthropic.AnthropicProvider",
            "anthropic_api_key",
        ),
    ],
)
def test_get_provider_uses_distinct_cloud_cache_entries_by_api_key(
    provider_name: str, patch_target: str, key_field: str, tmp_path: Path
) -> None:
    """Cloud provider cache entries do not cross credential boundaries."""
    first_provider = object()
    second_provider = object()
    common_config: dict[str, str] = {
        "provider": provider_name,
        "xai_api_key": "unused-xai-key",
        "gemini_api_key": "unused-gemini-key",
        "anthropic_api_key": "unused-anthropic-key",
        "ops_dir": str(tmp_path / "ops"),
    }
    first_config = RouterConfig(**{**common_config, key_field: "first-key"})  # type: ignore[arg-type]
    second_config = RouterConfig(**{**common_config, key_field: "second-key"})  # type: ignore[arg-type]

    with patch(
        patch_target,
        side_effect=[first_provider, second_provider],
    ) as cls:
        first = get_provider(provider_name, first_config)
        second = get_provider(provider_name, second_config)

    assert first is first_provider
    assert second is second_provider
    assert first is not second
    assert cls.call_count == 2
    assert [call_info.args[0] for call_info in cls.call_args_list] == [
        "first-key",
        "second-key",
    ]


def test_get_provider_constructs_agent_with_ops_dir(tmp_path: Path) -> None:
    """Agent provider construction is keyed by the configured ops directory."""
    provider_instance = object()
    ops_dir = tmp_path / "ops"
    config = RouterConfig(provider="agent", ops_dir=str(ops_dir))

    with patch("distill.llm.providers.agent.AgentProvider", return_value=provider_instance) as cls:
        provider = get_provider("agent", config)

    assert provider is provider_instance
    cls.assert_called_once_with(str(ops_dir))


def test_get_provider_reuses_cached_agent_for_same_ops_dir(tmp_path: Path) -> None:
    """Provider factory cache keys agent instances by provider and ops directory."""
    provider_instance = object()
    ops_dir = tmp_path / "ops"
    config = RouterConfig(provider="agent", ops_dir=str(ops_dir))

    with patch("distill.llm.providers.agent.AgentProvider", return_value=provider_instance) as cls:
        first = get_provider("agent", config)
        second = get_provider("agent", config)

    assert first is provider_instance
    assert second is provider_instance
    cls.assert_called_once_with(str(ops_dir))


def test_get_provider_uses_distinct_agent_cache_entries_by_ops_dir(tmp_path: Path) -> None:
    """Agent provider cache entries do not cross ops directory boundaries."""
    first_provider = object()
    second_provider = object()
    first_config = RouterConfig(provider="agent", ops_dir=str(tmp_path / "ops-a"))
    second_config = RouterConfig(provider="agent", ops_dir=str(tmp_path / "ops-b"))

    with patch(
        "distill.llm.providers.agent.AgentProvider",
        side_effect=[first_provider, second_provider],
    ) as cls:
        first = get_provider("agent", first_config)
        second = get_provider("agent", second_config)

    assert first is first_provider
    assert second is second_provider
    assert first is not second
    assert cls.call_count == 2
    assert [call_info.args[0] for call_info in cls.call_args_list] == [
        str(tmp_path / "ops-a"),
        str(tmp_path / "ops-b"),
    ]


@pytest.mark.parametrize(
    ("provider_name", "patch_target"),
    [
        ("ollama", "distill.llm.providers.ollama.OllamaProvider"),
        ("lmstudio", "distill.llm.providers.lmstudio.LMStudioProvider"),
    ],
)
def test_get_provider_constructs_local_providers(
    provider_name: str, patch_target: str, tmp_path: Path
) -> None:
    """Local provider construction does not require API key arguments."""
    provider_instance = object()
    config = RouterConfig(provider=provider_name, ops_dir=str(tmp_path / "ops"))

    with patch(patch_target, return_value=provider_instance) as provider_cls:
        provider = get_provider(provider_name, config)

    assert provider is provider_instance
    provider_cls.assert_called_once_with()


def test_get_provider_openai_branch_is_explicitly_unimplemented(tmp_path: Path) -> None:
    """The factory keeps the reserved OpenAI provider fail-closed."""
    config = RouterConfig(provider="openai", openai_api_key="test-key", ops_dir=str(tmp_path))

    with pytest.raises(ConfigurationError, match="not implemented"):
        get_provider("openai", config)


def test_get_provider_unknown_branch_lists_valid_providers(tmp_path: Path) -> None:
    """The provider factory reports valid providers for unknown names."""
    config = RouterConfig(provider="xai", xai_api_key="test-key", ops_dir=str(tmp_path))

    with pytest.raises(ConfigurationError) as exc_info:
        get_provider("unknown", config)

    assert "Valid providers" in str(exc_info.value)
    assert "xai" in str(exc_info.value)


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


def test_local_telemetry_records_tokens_per_second() -> None:
    """Successful local calls record local provider throughput."""
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = str(Path(tmp) / "ops")
        config = RouterConfig(provider="ollama", ops_dir=ops_dir)
        provider_call_result = object()
        mock_prov = Mock()
        mock_prov.call.return_value = provider_call_result
        response = LLM_Response(
            text="ok",
            input_tokens=10,
            output_tokens=25,
            model="qwen3.5:27b",
        )

        with (
            patch("distill.llm.router._get_provider", return_value=mock_prov),
            patch("distill.llm.router.run_coroutine_sync", return_value=response) as runner,
            patch("distill.llm.router.time.monotonic", side_effect=[100.0, 102.0]),
        ):
            call(config, "analysis", "test prompt")

        runner.assert_called_once_with(provider_call_result)
        records = top_n_by_tokens(ops_dir, n=1)
        assert len(records) == 1
        assert records[0].provider_type == "local"
        assert records[0].tokens_per_second == 12.5


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
    """Verify the provider cache is accessible for test isolation."""
    _clear_provider_cache()
    assert _provider_cache_size() == 0
