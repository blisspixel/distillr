"""Tests for distill.llm.errors: provider-error classification + messages."""

from __future__ import annotations

import pytest

from distill.llm.errors import describe_provider_error, is_credit_or_auth_error


class _StatusError(Exception):
    """Mimic an SDK error carrying an HTTP status_code (openai shape)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_credit_exhaustion_403_is_described():
    exc = _StatusError("Your team has used all available credits", 403)
    msg = describe_provider_error(exc)
    assert msg is not None
    assert "credits exhausted" in msg.lower()
    assert "DISTILL_FALLBACK_PROVIDER" in msg


def test_credit_marker_without_status():
    exc = Exception("You have exceeded your current quota")
    assert describe_provider_error(exc) is not None
    assert is_credit_or_auth_error(exc)


def test_auth_401_is_described():
    exc = _StatusError("invalid api key", 401)
    msg = describe_provider_error(exc)
    assert msg is not None
    assert "authentication failed" in msg.lower()


def test_rate_limit_429_is_described():
    exc = _StatusError("rate limited", 429)
    msg = describe_provider_error(exc)
    assert msg is not None
    assert "429" in msg


def test_permanent_404_is_described_as_model_or_endpoint_error():
    msg = describe_provider_error(_StatusError("not found", 404))

    assert msg is not None
    assert "model or endpoint not found" in msg


def test_unknown_error_returns_none():
    assert describe_provider_error(ValueError("totally unrelated bug")) is None


def test_is_credit_or_auth_error_classification():
    assert is_credit_or_auth_error(_StatusError("x", 403))
    assert is_credit_or_auth_error(_StatusError("x", 402))
    assert is_credit_or_auth_error(_StatusError("x", 401))
    assert not is_credit_or_auth_error(_StatusError("x", 500))
    assert not is_credit_or_auth_error(ValueError("unrelated"))


@pytest.mark.parametrize("status", [402, 403])
def test_payment_statuses_describe_credit(status):
    assert "credits" in describe_provider_error(_StatusError("nope", status)).lower()
