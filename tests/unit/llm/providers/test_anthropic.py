# pyright: strict
"""Unit tests for AnthropicProvider."""

from __future__ import annotations

import asyncio
from typing import ClassVar

import httpx
import pytest

from distill.llm.providers.anthropic import (
    ANTHROPIC_API_VERSION,
    ANTHROPIC_MESSAGES_URL,
    AnthropicProvider,
)
from distill.llm.router import LLM_Response
from distill.llm.usage import usage_attempts_from_exception


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, object] | None = None,
        *,
        raise_error: Exception | None = None,
    ) -> None:
        self._payload = payload or {}
        self._raise_error = raise_error

    def raise_for_status(self) -> None:
        if self._raise_error is not None:
            raise self._raise_error

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeAsyncClient:
    responses: ClassVar[list[_FakeResponse | Exception]] = []
    posts: ClassVar[list[dict[str, object]]] = []
    timeouts: ClassVar[list[int]] = []

    def __init__(self, *, timeout: int) -> None:
        type(self).timeouts.append(timeout)

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> _FakeResponse:
        type(self).posts.append({"url": url, "headers": headers, "json": json})
        response = type(self).responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _install_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.posts = []
    _FakeAsyncClient.timeouts = []
    monkeypatch.setattr("distill.llm.providers.anthropic.httpx.AsyncClient", _FakeAsyncClient)


def _success_payload(
    *,
    text: str = "hello",
    model: str = "claude-sonnet-5",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": text}, {"type": "tool_use", "id": "ignored"}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "model": model,
    }


def test_successful_call_builds_messages_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _FakeAsyncClient.responses.append(_FakeResponse(_success_payload(text="response text")))
    provider = AnthropicProvider("test-key")

    result = asyncio.run(
        provider.call(
            "claude-sonnet-5",
            "hello",
            max_tokens=128_000,
            timeout=42,
            temperature=0.2,
        )
    )

    assert isinstance(result, LLM_Response)
    assert result.text == "response text"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.model == "claude-sonnet-5"
    assert _FakeAsyncClient.timeouts == [42]
    request = _FakeAsyncClient.posts[0]
    assert request["url"] == ANTHROPIC_MESSAGES_URL
    assert request["headers"] == {
        "x-api-key": "test-key",
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    assert request["json"] == {
        "model": "claude-sonnet-5",
        "max_tokens": 128_000,
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_non_sonnet5_models_keep_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _FakeAsyncClient.responses.append(_FakeResponse(_success_payload(model="claude-sonnet-4")))
    provider = AnthropicProvider("test-key")

    asyncio.run(provider.call("claude-sonnet-4", "hello", temperature=0.2))

    payload = _FakeAsyncClient.posts[0]["json"]
    assert isinstance(payload, dict)
    assert payload["temperature"] == 0.2


def test_reasoning_effort_uses_output_config_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _FakeAsyncClient.responses.append(_FakeResponse(_success_payload()))
    provider = AnthropicProvider("test-key")

    asyncio.run(provider.call("claude-sonnet-5", "hello", reasoning_effort="xhigh"))

    payload = _FakeAsyncClient.posts[0]["json"]
    assert isinstance(payload, dict)
    assert payload["output_config"] == {"effort": "xhigh"}
    assert "effort" not in payload
    assert "thinking" not in payload


def test_missing_usage_and_model_fall_back_conservatively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch)
    _FakeAsyncClient.responses.append(
        _FakeResponse(
            {
                "content": [{"type": "text", "text": "partial"}],
                "usage": {"input_tokens": True, "output_tokens": -5},
                "model": "",
            }
        )
    )
    provider = AnthropicProvider("test-key")

    result = asyncio.run(provider.call("claude-sonnet-5", "hello", max_tokens=64))

    assert result.text == "partial"
    assert result.input_tokens == 1029
    assert result.output_tokens == 64
    assert result.model == "claude-sonnet-5"
    assert result.usage_source == "conservative"


def test_retry_on_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    _FakeAsyncClient.responses.extend(
        [RuntimeError("transient"), _FakeResponse(_success_payload(text="ok"))]
    )
    provider = AnthropicProvider("test-key")

    with monkeypatch.context() as ctx:
        sleep_calls: list[int] = []
        ctx.setattr("distill.llm.providers.anthropic.time.sleep", sleep_calls.append)
        result = asyncio.run(provider.call("claude-sonnet-5", "hello", retries=2))

    assert result.text == "ok"
    assert [row.outcome for row in result.usage_attempts] == ["error", "success"]
    assert result.usage_attempts[0].usage_source == "conservative"
    assert result.usage_attempts[0].output_tokens == 8192
    assert result.usage_attempts[1].usage_source == "reported"
    assert sleep_calls == [5]
    assert len(_FakeAsyncClient.posts) == 2


def test_exhausted_retries_attach_every_conservative_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_client(monkeypatch)
    _FakeAsyncClient.responses.extend([RuntimeError("transient")] * 3)
    provider = AnthropicProvider("test-key")

    def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("distill.llm.providers.anthropic.time.sleep", no_sleep)
    with pytest.raises(RuntimeError, match="transient") as raised:
        asyncio.run(provider.call("claude-sonnet-5", "hello", retries=2, max_tokens=64))

    attempts = usage_attempts_from_exception(raised.value)
    assert len(attempts) == 3
    assert all(row.outcome == "error" for row in attempts)
    assert all(row.output_tokens == 64 for row in attempts)


def test_permanent_http_error_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_client(monkeypatch)
    request = httpx.Request("POST", ANTHROPIC_MESSAGES_URL)
    response = httpx.Response(401, request=request)
    error = httpx.HTTPStatusError("unauthorized", request=request, response=response)
    _FakeAsyncClient.responses.append(_FakeResponse(raise_error=error))
    provider = AnthropicProvider("test-key")

    with pytest.raises(httpx.HTTPStatusError, match="unauthorized"):
        asyncio.run(provider.call("claude-sonnet-5", "hello", retries=2))

    assert len(_FakeAsyncClient.posts) == 1
