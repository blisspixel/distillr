# pyright: basic
"""OpenRouter doctor checks remain spend-aware and route-specific."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from distill.config import DistillConfig
from distill.doctor.openrouter import validate_openrouter_key
from distill.llm.types import LLM_Response
from distill.llm.usage import LLMUsageAttempt, attach_usage_attempts
from distill.pipeline.costs import CostTracker


def _config(tmp_path, **overrides: object) -> DistillConfig:
    values: dict[str, object] = {
        "openrouter_api_key": "test-key",
        "distill_output_dir": tmp_path,
        "distill_cost_mode": "paid-ok",
        "_env_file": None,
    }
    values.update(overrides)
    return DistillConfig(**values)  # type: ignore[arg-type]


def test_missing_key_is_not_set(tmp_path) -> None:
    status, detail = validate_openrouter_key(
        _config(tmp_path, openrouter_api_key=""),
        CostTracker(),
    )

    assert (status, detail) == ("not_set", "")


def test_no_metered_blocks_before_key_metadata_contact(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "httpx.get",
        lambda *_args, **_kwargs: pytest.fail("blocked route must not contact OpenRouter"),
    )

    status, detail = validate_openrouter_key(
        _config(tmp_path, distill_cost_mode="no-metered"),
        CostTracker(),
    )

    assert status == "skipped"
    assert "Blocked provider: openrouter" in detail


def test_key_metadata_probe_accepts_key_without_inference(monkeypatch, tmp_path) -> None:
    class Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> object:
            return {"data": {"limit": 10.0, "limit_remaining": 9.75}}

    calls: list[tuple[str, dict[str, object]]] = []

    def get(url: str, **kwargs: object) -> Response:
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("httpx.get", get)

    result = validate_openrouter_key(_config(tmp_path), CostTracker())

    assert result == (
        "ok",
        "key accepted; $10.00 key spending limit, $9.75 remaining",
    )
    assert calls[0][0] == "https://openrouter.ai/api/v1/key"
    assert calls[0][1]["headers"] == {"Authorization": "Bearer test-key"}


def test_key_metadata_reports_missing_spending_limit(monkeypatch, tmp_path) -> None:
    class Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> object:
            return {"data": {"limit": None, "limit_remaining": None}}

    monkeypatch.setattr("httpx.get", lambda *_args, **_kwargs: Response())

    assert validate_openrouter_key(_config(tmp_path), CostTracker()) == (
        "ok",
        "key accepted; no key spending limit configured",
    )


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"data": None}, {"data": {"limit": "unknown"}}],
)
def test_key_metadata_handles_incomplete_payload(
    monkeypatch,
    tmp_path,
    payload: object,
) -> None:
    class Response:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> object:
            return payload

    monkeypatch.setattr("httpx.get", lambda *_args, **_kwargs: Response())

    assert validate_openrouter_key(_config(tmp_path), CostTracker()) == (
        "ok",
        "key accepted; select an exact model to probe inference",
    )


@pytest.mark.parametrize(("status_code", "expected"), [(401, "invalid"), (500, "unknown")])
def test_key_metadata_probe_classifies_errors(
    monkeypatch,
    tmp_path,
    status_code: int,
    expected: str,
) -> None:
    class ProbeError(RuntimeError):
        def __init__(self) -> None:
            self.response = SimpleNamespace(status_code=status_code)
            super().__init__("probe failed")

    class Response:
        @staticmethod
        def raise_for_status() -> None:
            raise ProbeError

    monkeypatch.setattr("httpx.get", lambda *_args, **_kwargs: Response())

    assert validate_openrouter_key(_config(tmp_path), CostTracker())[0] == expected


def test_selected_model_probe_records_provider_reported_cost(monkeypatch, tmp_path) -> None:
    attempt = LLMUsageAttempt(
        input_tokens=12,
        output_tokens=4,
        model="x-ai/grok-4.6",
        provider_name="openrouter",
        provider_type="cloud",
        usage_source="reported",
        outcome="success",
        billed_cost_usd=0.0002,
        upstream_provider="xai",
    )

    class Provider:
        def __init__(self, api_key: str, *, zdr: bool) -> None:
            assert api_key == "test-key"
            assert zdr is True

        @staticmethod
        async def call(*_args: object, **_kwargs: object) -> LLM_Response:
            return LLM_Response(
                text="ok",
                input_tokens=12,
                output_tokens=4,
                model="x-ai/grok-4.6",
                billed_cost_usd=0.0002,
                upstream_provider="xai",
                usage_attempts=(attempt,),
            )

    monkeypatch.setattr("distill.doctor.openrouter.OpenRouterProvider", Provider)
    tracker = CostTracker(budget=0.01)

    result = validate_openrouter_key(
        _config(tmp_path),
        tracker,
        model="x-ai/grok-4.6",
    )

    assert result == ("ok", "x-ai/grok-4.6")
    assert tracker.total_cost == 0.0002
    assert tracker.entries[0].upstream_provider == "xai"


def test_budgeted_unknown_model_refuses_before_provider_construction(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        "distill.doctor.openrouter.OpenRouterProvider",
        lambda *_args, **_kwargs: pytest.fail("unpriced route must not be constructed"),
    )

    status, detail = validate_openrouter_key(
        _config(tmp_path),
        CostTracker(budget=1.0),
        model="meta-llama/llama-3.3-70b-instruct",
    )

    assert status == "skipped"
    assert "no verified price" in detail


def test_model_probe_records_attached_failure_attempt(monkeypatch, tmp_path) -> None:
    error = RuntimeError("offline")
    attach_usage_attempts(
        error,
        (
            LLMUsageAttempt(
                input_tokens=100,
                output_tokens=1,
                model="x-ai/grok-4.6",
                provider_name="openrouter",
                provider_type="cloud",
                usage_source="conservative",
                outcome="error",
                error_type="RuntimeError",
            ),
        ),
    )

    class Provider:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        async def call(*_args: object, **_kwargs: object) -> LLM_Response:
            raise error

    monkeypatch.setattr("distill.doctor.openrouter.OpenRouterProvider", Provider)
    tracker = CostTracker()

    status, detail = validate_openrouter_key(
        _config(tmp_path),
        tracker,
        model="x-ai/grok-4.6",
    )

    assert status == "unknown"
    assert detail == "offline"
    assert len(tracker.entries) == 1
    assert tracker.entries[0].outcome == "error"


def test_model_probe_preserves_interrupt_and_records_conservative_usage(
    monkeypatch,
    tmp_path,
) -> None:
    class Provider:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        async def call(*_args: object, **_kwargs: object) -> LLM_Response:
            raise KeyboardInterrupt

    monkeypatch.setattr("distill.doctor.openrouter.OpenRouterProvider", Provider)
    tracker = CostTracker()

    with pytest.raises(KeyboardInterrupt):
        validate_openrouter_key(
            _config(tmp_path),
            tracker,
            model="x-ai/grok-4.6",
        )

    assert len(tracker.entries) == 1
    assert tracker.entries[0].error_type == "KeyboardInterrupt"
