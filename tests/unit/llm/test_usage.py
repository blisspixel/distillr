# pyright: strict
"""Unit tests for immutable provider-attempt usage evidence."""

from __future__ import annotations

import pytest

from distill.llm.usage import (
    LLMUsageAttempt,
    attach_usage_attempts,
    emit_usage_attempt,
    usage_attempts_from_exception,
)


def _attempt(*, attempt_id: str = "") -> LLMUsageAttempt:
    return LLMUsageAttempt(
        input_tokens=10,
        output_tokens=20,
        model="model",
        provider_name="provider",
        provider_type="cloud",
        usage_source="reported",
        outcome="success",
        attempt_id=attempt_id,
    )


def test_attempt_identity_is_stable_once_assigned() -> None:
    existing = _attempt(attempt_id="stable")
    assert existing.with_identity() is existing

    identified = _attempt().with_identity()
    assert identified.attempt_id
    assert identified != _attempt()


def test_exception_attempt_reader_rejects_malformed_metadata() -> None:
    exc = RuntimeError("failed")
    exc.__dict__["_distill_usage_attempts"] = [_attempt()]
    assert usage_attempts_from_exception(exc) == ()

    exc.__dict__["_distill_usage_attempts"] = (object(),)
    assert usage_attempts_from_exception(exc) == ()


def test_attach_converts_attempt_lists_to_immutable_tuples() -> None:
    exc = RuntimeError("failed")
    attempt = _attempt().with_identity()
    attach_usage_attempts(exc, [attempt])
    assert usage_attempts_from_exception(exc) == (attempt,)


def test_sink_failure_retains_the_attempt_that_triggered_it() -> None:
    class SinkStop(Exception):
        pass

    attempts: list[LLMUsageAttempt] = []

    def stop(_attempt: LLMUsageAttempt) -> None:
        raise SinkStop

    with pytest.raises(SinkStop) as raised:
        emit_usage_attempt(attempts, _attempt(), stop)

    attached = usage_attempts_from_exception(raised.value)
    assert attached == tuple(attempts)
    assert attached[0].attempt_id
