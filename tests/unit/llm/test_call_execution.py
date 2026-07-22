# pyright: strict
"""Tests for provider-attempt normalization at the router execution boundary."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import distill.llm.call_execution as call_execution
from distill.llm.call_execution import CallOptions, execute_call
from distill.llm.router import RouterConfig
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    attach_usage_attempts,
    emit_usage_attempt,
    usage_attempts_from_exception,
)
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.usage_records import TokenUsage


def _attempt(*, outcome: str, attempt_id: str = "") -> LLMUsageAttempt:
    return LLMUsageAttempt(
        input_tokens=10,
        output_tokens=20,
        model="grok-4.3",
        provider_name="",
        provider_type="",
        usage_source="conservative" if outcome == "error" else "reported",
        outcome="error" if outcome == "error" else "success",
        error_type="RuntimeError" if outcome == "error" else "",
        attempt_id=attempt_id,
    )


class _Provider:
    def __init__(self, result: LLM_Response | Exception) -> None:
        self.result = result
        self.calls = 0

    async def call(self, _model: str, _prompt: str, **_kwargs: object) -> LLM_Response:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _EndpointProvider(_Provider):
    def __init__(self, result: LLM_Response | Exception, base_url: str) -> None:
        super().__init__(result)
        self._base_url = base_url


class _CapturingEndpointProvider(_EndpointProvider):
    def __init__(self, result: LLM_Response, base_url: str) -> None:
        super().__init__(result, base_url)
        self.kwargs: dict[str, object] = {}

    async def call(self, _model: str, _prompt: str, **kwargs: object) -> LLM_Response:
        self.kwargs = kwargs
        return self.result  # type: ignore[return-value]


class _EmittingSuccessProvider(_Provider):
    async def call(self, model: str, _prompt: str, **kwargs: object) -> LLM_Response:
        self.calls += 1
        sink = kwargs.get("usage_sink")
        assert callable(sink)
        attempts: list[LLMUsageAttempt] = []
        emit_usage_attempt(
            attempts,
            LLMUsageAttempt(
                input_tokens=100,
                output_tokens=100,
                model=model,
                provider_name="xai",
                provider_type="cloud",
                usage_source="reported",
                outcome="success",
                attempt_id="provider-success",
            ),
            sink,
        )
        raise AssertionError("a fail-closed accounting sink should interrupt the provider")


def _options(
    provider: _Provider,
    sink: list[LLMUsageAttempt],
) -> CallOptions:
    config = RouterConfig(xai_api_key="key", ops_dir="")

    def get_provider(_name: str) -> Any:
        return provider

    return CallOptions(
        config=config,
        workload_tag="analysis",
        prompt="prompt",
        max_tokens=64,
        timeout=30,
        retries=0,
        temperature=None,
        call_type="analysis",
        ops_dir="",
        run_id="run",
        usage_sink=sink.append,
        usage_batch_sink=lambda attempts: sink.extend(attempts),
        provider_getter=get_provider,
    )


def test_provider_type_requires_loopback_for_local_cost_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert call_execution._provider_type("ollama") == "local"

    monkeypatch.setenv("OLLAMA_BASE_URL", "https://hosted.example/v1")
    assert call_execution._provider_type("ollama") == "unknown"


def test_execution_uses_constructed_provider_endpoint_for_usage_and_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    provider = _EndpointProvider(
        LLM_Response(
            text="ok",
            input_tokens=10,
            output_tokens=20,
            model="grok-4.3",
        ),
        "https://hosted.example/v1",
    )
    emitted: list[LLMUsageAttempt] = []
    telemetry: dict[str, object] = {}
    monkeypatch.setattr(
        call_execution,
        "_emit_telemetry",
        lambda **kwargs: telemetry.update(kwargs),
    )

    result = execute_call(_options(provider, emitted), "ollama", "grok-4.3")

    assert result.provider_type == "unknown"
    assert result.usage_attempts[0].provider_type == "unknown"
    assert TokenUsage.from_response(result).expanded()[0].no_metered_cost is False
    assert TokenUsage.from_response(result).expanded()[0].external_cost_unavailable is True
    assert telemetry["provider_type"] == "unknown"


def test_remote_local_adapter_receives_per_attempt_usage_sink() -> None:
    provider = _CapturingEndpointProvider(
        LLM_Response(
            text="ok",
            input_tokens=10,
            output_tokens=20,
            model="hosted-model",
        ),
        "https://hosted.example/v1",
    )
    emitted: list[LLMUsageAttempt] = []
    options = _options(provider, emitted)

    execute_call(options, "lmstudio", "hosted-model")

    assert provider.kwargs["usage_sink"] is options.usage_sink


def test_provider_supplied_success_attempt_is_normalized_and_emitted() -> None:
    supplied = replace(
        _attempt(outcome="success", attempt_id="provider-attempt"),
        provider_name="ollama",
        provider_type="local",
    )
    response = LLM_Response(
        text="ok",
        input_tokens=10,
        output_tokens=20,
        model="grok-4.3",
        usage_attempts=(supplied,),
    )
    emitted: list[LLMUsageAttempt] = []

    result = execute_call(_options(_Provider(response), emitted), "xai", "grok-4.3")

    assert emitted == list(result.usage_attempts)
    assert result.usage_attempts[0].provider_name == "xai"
    assert result.usage_attempts[0].provider_type == "cloud"
    assert TokenUsage.from_response(result).expanded()[0].no_metered_cost is False


def test_agent_host_identity_and_unknown_billing_survive_execution_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = replace(
        _attempt(outcome="success", attempt_id="host-attempt"),
        model="gpt-host",
        provider_name="codex",
        provider_type="host-managed",
        usage_source="host-reported",
    )
    response = LLM_Response(
        text="ok",
        input_tokens=10,
        output_tokens=20,
        model="gpt-host",
        provider_name="codex",
        provider_type="host-managed",
        usage_source="host-reported",
        usage_attempts=(supplied,),
    )
    telemetry: dict[str, object] = {}
    monkeypatch.setattr(
        call_execution,
        "_emit_telemetry",
        lambda **kwargs: telemetry.update(kwargs),
    )
    emitted: list[LLMUsageAttempt] = []

    result = execute_call(_options(_Provider(response), emitted), "agent", "agent")

    assert result.provider_name == "codex"
    assert result.provider_type == "host-managed"
    assert result.usage_attempts == (supplied,)
    assert emitted == [supplied]
    assert TokenUsage.from_response(result).expanded()[0].no_metered_cost is False
    assert telemetry["provider_name"] == "codex"
    assert telemetry["provider_type"] == "host-managed"
    assert telemetry["tokens_per_second"] == 0


def test_attached_error_attempts_receive_distinct_ids_without_derived_duplicates() -> None:
    exc = RuntimeError("failed")
    attach_usage_attempts(
        exc,
        [
            replace(_attempt(outcome="error"), provider_name="ollama", provider_type="local"),
            _attempt(outcome="error"),
        ],
    )
    emitted: list[LLMUsageAttempt] = []

    with pytest.raises(RuntimeError, match="failed") as raised:
        execute_call(_options(_Provider(exc), emitted), "xai", "grok-4.3")

    attached = usage_attempts_from_exception(raised.value)
    assert emitted == list(attached)
    assert len(attached) == 2
    assert len({row.attempt_id for row in attached}) == 2
    assert {row.provider_name for row in attached} == {"xai"}
    assert {row.provider_type for row in attached} == {"cloud"}


def test_existing_attempts_need_no_sink() -> None:
    supplied = _attempt(outcome="success", attempt_id="provider-attempt")
    response = LLM_Response(
        text="ok",
        input_tokens=10,
        output_tokens=20,
        model="grok-4.3",
        usage_attempts=(supplied,),
    )
    provider = _Provider(response)
    options = replace(
        _options(provider, []),
        usage_sink=None,
        usage_batch_sink=None,
    )

    result = execute_call(options, "xai", "grok-4.3")

    assert provider.calls == 1
    assert result.usage_attempts[0].attempt_id == "provider-attempt"


def test_post_response_accounting_failure_is_not_reemitted_or_rerouted() -> None:
    attempts = (
        _attempt(outcome="success", attempt_id="attempt-1"),
        _attempt(outcome="success", attempt_id="attempt-2"),
    )
    response = LLM_Response(
        text="paid success",
        input_tokens=20,
        output_tokens=40,
        model="grok-4.3",
        usage_attempts=attempts,
    )
    provider = _Provider(response)
    emitted: list[str] = []

    def failing_sink(attempt: LLMUsageAttempt) -> None:
        emitted.append(attempt.attempt_id)
        raise RuntimeError("usage ledger unavailable")

    options = replace(
        _options(provider, []),
        usage_sink=failing_sink,
        usage_batch_sink=None,
    )

    with pytest.raises(RuntimeError, match="usage ledger unavailable") as raised:
        execute_call(options, "xai", "grok-4.3")

    assert provider.calls == 1
    assert emitted == ["attempt-1", "attempt-2"]
    attached = usage_attempts_from_exception(raised.value)
    assert [attempt.attempt_id for attempt in attached] == ["attempt-1", "attempt-2"]
    assert {attempt.provider_name for attempt in attached} == {"xai"}
    assert {attempt.provider_type for attempt in attached} == {"cloud"}


def test_provider_side_success_accounting_failure_records_success_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _EmittingSuccessProvider(RuntimeError("unused"))
    tracker = CostTracker(budget=0.000001)
    telemetry: dict[str, object] = {}
    options = replace(
        _options(provider, []),
        usage_sink=tracker.record_attempt,
        usage_batch_sink=None,
    )
    monkeypatch.setattr(
        call_execution,
        "_emit_telemetry",
        lambda **kwargs: telemetry.update(kwargs),
    )

    with pytest.raises(BudgetExceededError):
        execute_call(options, "xai", "grok-4.3")

    assert provider.calls == 1
    assert len(tracker.entries) == 1
    assert tracker.entries[0].outcome == "success"
    assert telemetry["outcome"] == "success"
    assert telemetry["error_type"] == ""
    assert telemetry["input_tokens"] == 100
    assert telemetry["output_tokens"] == 100


def test_route_telemetry_falls_back_to_response_usage_without_attempt_rows(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        call_execution,
        "_emit_telemetry",
        lambda **kwargs: captured.update(kwargs),
    )
    response = LLM_Response(
        text="ok",
        input_tokens=7,
        output_tokens=9,
        model="grok-4.3",
    )

    call_execution._record_route(
        _options(_Provider(response), []),
        "xai",
        "grok-4.3",
        response,
        "success",
        "",
        1.0,
        (),
    )

    assert captured["input_tokens"] == 7
    assert captured["output_tokens"] == 9
    assert captured["usage_source"] == "unavailable"


@pytest.mark.parametrize(
    ("provider_name", "usage_source", "has_tokens"),
    [
        ("xai", "conservative", True),
        ("ollama", "unavailable", False),
    ],
)
def test_unreported_provider_failures_get_route_appropriate_usage(
    provider_name: str,
    usage_source: str,
    has_tokens: bool,
) -> None:
    provider = _Provider(RuntimeError("provider failed"))
    emitted: list[LLMUsageAttempt] = []

    with pytest.raises(RuntimeError, match="provider failed") as raised:
        execute_call(_options(provider, emitted), provider_name, "model")

    attempts = usage_attempts_from_exception(raised.value)
    assert provider.calls == 1
    assert len(attempts) == 1
    assert attempts[0].usage_source == usage_source
    assert (attempts[0].input_tokens > 0) is has_tokens
    assert (attempts[0].output_tokens > 0) is has_tokens


def test_agent_accounting_rejection_precedes_pending_task_visibility(tmp_path: Path) -> None:
    from distill.llm.providers.agent import AgentProvider

    ops_dir = tmp_path / "ops"
    provider = AgentProvider(str(ops_dir))
    tracker = CostTracker(budget=0.000001)

    options = replace(
        _options(_Provider(RuntimeError("unused")), []),
        ops_dir=str(ops_dir),
        usage_sink=tracker.record_attempt,
        usage_batch_sink=None,
        provider_getter=lambda _name: provider,
    )

    with pytest.raises(BudgetExceededError):
        execute_call(options, "agent", "agent")

    assert list((ops_dir / "tasks" / "pending").glob("*.json")) == []
    assert len(tracker.entries) == 1
    assert tracker.entries[0].provider_name == "agent"


def test_success_without_provider_attempts_derives_and_emits_usage() -> None:
    response = LLM_Response(
        text="ok",
        input_tokens=7,
        output_tokens=9,
        model="reported-model",
        usage_source="reported",
    )
    provider = _Provider(response)
    emitted: list[LLMUsageAttempt] = []

    result = execute_call(_options(provider, emitted), "xai", "requested-model")

    assert provider.calls == 1
    assert len(result.usage_attempts) == 1
    assert result.usage_attempts[0].model == "reported-model"
    assert result.usage_attempts[0].input_tokens == 7
    assert result.usage_attempts[0].output_tokens == 9
    assert emitted == list(result.usage_attempts)


def test_batch_accounting_failure_is_not_retried() -> None:
    attempt = _attempt(outcome="success", attempt_id="attempt-1")
    provider = _Provider(
        LLM_Response(
            text="paid success",
            input_tokens=10,
            output_tokens=20,
            model="grok-4.3",
            usage_attempts=(attempt,),
        )
    )
    batches: list[tuple[LLMUsageAttempt, ...]] = []

    def failing_batch_sink(rows: tuple[LLMUsageAttempt, ...]) -> None:
        batches.append(rows)
        raise RuntimeError("batch ledger unavailable")

    options = replace(
        _options(provider, []),
        usage_sink=None,
        usage_batch_sink=failing_batch_sink,
    )

    with pytest.raises(RuntimeError, match="batch ledger unavailable"):
        execute_call(options, "xai", "grok-4.3")

    assert provider.calls == 1
    assert len(batches) == 1
    assert batches[0][0].attempt_id == "attempt-1"


def test_nonempty_ops_dir_writes_route_telemetry(monkeypatch) -> None:
    captured: list[tuple[str, object]] = []
    monkeypatch.setattr(
        "distill.llm.telemetry.write_record",
        lambda ops_dir, record: captured.append((ops_dir, record)),
    )

    call_execution._emit_telemetry(
        ops_dir="ops",
        model="model",
        workload_tag="analysis",
        input_tokens=1,
        output_tokens=2,
        elapsed_seconds=0.5,
        outcome="success",
        error_type="",
        call_type="analysis",
        run_id="run",
        provider_type="cloud",
        provider_name="xai",
        tokens_per_second=0.0,
        usage_source="reported",
    )

    assert len(captured) == 1
    assert captured[0][0] == "ops"
    assert captured[0][1].provider_name == "xai"


def test_fallback_success_accounting_failure_surfaces_without_masking_or_replay() -> None:
    class CreditError(RuntimeError):
        status_code = 403

    primary = _Provider(CreditError("used all available credits"))
    fallback_attempt = replace(
        _attempt(outcome="success", attempt_id="fallback-success"),
        model="local-model",
    )
    fallback = _Provider(
        LLM_Response(
            text="paid fallback success",
            input_tokens=10,
            output_tokens=20,
            model="local-model",
            usage_attempts=(fallback_attempt,),
        )
    )
    emitted: list[tuple[str, str]] = []

    def accounting_sink(attempt: LLMUsageAttempt) -> None:
        emitted.append((attempt.provider_name, attempt.outcome))
        if attempt.outcome == "success":
            raise RuntimeError("fallback usage ledger unavailable")

    config = RouterConfig(
        xai_api_key="key",
        ops_dir="",
        fallback_provider="ollama",
        fallback_model="local-model",
    )
    options = replace(
        _options(primary, []),
        config=config,
        usage_sink=accounting_sink,
        usage_batch_sink=None,
        provider_getter=lambda name: primary if name == "xai" else fallback,
    )

    with pytest.raises(RuntimeError, match="fallback usage ledger unavailable") as raised:
        execute_call(options, "xai", "grok-4.3")

    assert primary.calls == 1
    assert fallback.calls == 1
    assert emitted == [("xai", "error"), ("ollama", "success")]
    evidence = usage_attempts_from_exception(raised.value)
    assert [(attempt.provider_name, attempt.outcome) for attempt in evidence] == [
        ("xai", "error"),
        ("ollama", "success"),
    ]
