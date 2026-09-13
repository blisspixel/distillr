# pyright: strict
"""Local inference admission must inspect the daemon, not trust a model name."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from distill.llm.cost_policy import CostPolicyError
from distill.llm.providers import _ollama_show
from distill.llm.providers._ollama_metadata import parse_context_window
from distill.llm.providers._ollama_show import ShowProbe
from distill.llm.providers.ollama import OllamaProvider
from distill.llm.usage import usage_attempts_from_exception

_STATUS = {"cloud": {"disabled": True, "source": "env"}}
_LOCAL = {
    "details": {"format": "gguf"},
    "model_info": {"general.architecture": "llama", "llama.context_length": 8192},
    "capabilities": ["completion", "thinking"],
}
_CHAT = {
    "model": "alias",
    "message": {"content": "answer"},
    "done": True,
    "prompt_eval_count": 1,
    "eval_count": 1,
}


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[..., httpx.AsyncClient]:
    client_type = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return client_type(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def _reply(request: httpx.Request, value: object) -> httpx.Response:
    return httpx.Response(200, json=value, request=request)


@pytest.mark.parametrize("name", ["ordinary-alias", "gpt-oss:120b-cloud"])
@pytest.mark.parametrize(
    "status",
    [
        None,
        [],
        {},
        {"cloud": None},
        {"cloud": {}},
        {"cloud": {"disabled": False, "source": "env"}},
        {"cloud": {"disabled": 1, "source": "env"}},
        {"cloud": {"disabled": "true", "source": "env"}},
        {"cloud": {"disabled": True}},
        {"cloud": {"disabled": True, "source": None}},
        {"cloud": {"disabled": True, "source": ""}},
        {"cloud": {"disabled": True, "source": "x" * 65}},
        {"cloud": {"disabled": True, "source": "env", "new": True}},
        {"cloud": {"disabled": True, "source": "env"}, "new": True},
    ],
)
def test_unproved_daemon_refuses_before_model_or_prompt(name: str, status: object) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _reply(request, status)

    provider = OllamaProvider()
    with patch("httpx.AsyncClient", _transport(handler)), pytest.raises(CostPolicyError) as caught:
        asyncio.run(provider.call(name, "private source", retries=3))
    assert [request.url.path for request in requests if request.url.path != "/api/ps"] == [
        "/api/status"
    ]
    assert all(b"private source" not in request.content for request in requests)
    assert "restart Ollama" in str(caught.value)
    attempts = usage_attempts_from_exception(caught.value)
    assert len(attempts) == 1
    assert attempts[0].provider_type == "unknown"
    assert attempts[0].input_tokens == attempts[0].output_tokens == 0


@pytest.mark.parametrize(
    "model_data",
    [
        None,
        [],
        {},
        {"details": [], "model_info": {}},
        {"details": {"format": "gguf"}, "model_info": {}},
        {"details": {"format": "unknown"}, "model_info": _LOCAL["model_info"]},
        {"details": {"format": "gguf"}, "model_info": {"general.architecture": ""}},
        {"details": {"format": "gguf"}, "model_info": {"general.architecture": 1}},
        {**_LOCAL, "remote_host": "https://ollama.com"},
        {**_LOCAL, "remote_model": "upstream-model"},
        {**_LOCAL, "remote_host": None},
        {**_LOCAL, "remote_model": False},
    ],
)
def test_unproved_or_remote_alias_refuses_before_prompt(model_data: object) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.url.path != "/api/chat"
        return _reply(request, _STATUS if request.url.path == "/api/status" else model_data)

    with patch("httpx.AsyncClient", _transport(handler)), pytest.raises(CostPolicyError):
        asyncio.run(OllamaProvider().call("innocent-alias", "private source"))
    assert paths[-2:] == ["/api/status", "/api/show"]


@pytest.mark.parametrize("model_format", ["gguf", "safetensors"])
def test_local_proof_preserves_exact_model_and_refreshes_metadata(model_format: str) -> None:
    models: list[str] = []
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/status":
            return _reply(request, _STATUS)
        if request.url.path == "/api/show":
            models.append(json.loads(request.content)["model"])
            return _reply(request, {**_LOCAL, "details": {"format": model_format}})
        if request.url.path == "/api/chat":
            models.append(json.loads(request.content)["model"])
            return _reply(request, _CHAT)
        return _reply(request, {"models": []})

    provider = OllamaProvider()
    with patch("httpx.AsyncClient", _transport(handler)):
        result = asyncio.run(provider.call("custom-name:cloud", "source", retries=0))
    assert result.text == "answer"
    assert result.usage_attempts[0].provider_type == "local"
    assert models == ["custom-name:cloud", "custom-name:cloud"]
    assert paths[-3:] == ["/api/status", "/api/show", "/api/chat"]
    assert asyncio.run(provider.get_context_window("custom-name:cloud")) == 8192


@pytest.mark.parametrize("change", ["daemon", "model"])
def test_retry_rechecks_daemon_and_model_before_second_prompt(change: str) -> None:
    chat_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_calls
        if request.url.path == "/api/status":
            return _reply(
                request,
                {"cloud": {"disabled": chat_calls == 0 or change == "model", "source": "env"}},
            )
        if request.url.path == "/api/show":
            return _reply(
                request,
                _LOCAL if chat_calls == 0 else {**_LOCAL, "remote_host": "https://ollama.com"},
            )
        if request.url.path == "/api/chat":
            chat_calls += 1
            raise httpx.ReadTimeout("retry", request=request)
        return _reply(request, {"models": []})

    with (
        patch("httpx.AsyncClient", _transport(handler)),
        patch("asyncio.sleep", AsyncMock()),
        pytest.raises(CostPolicyError) as caught,
    ):
        asyncio.run(OllamaProvider().call("alias", "source", retries=2))
    assert chat_calls == 1
    assert [row.provider_type for row in usage_attempts_from_exception(caught.value)] == [
        "local",
        "unknown",
    ]


def test_remote_response_is_refused_and_never_accounted_as_local() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        values = {
            "/api/status": _STATUS,
            "/api/show": _LOCAL,
            "/api/chat": {**_CHAT, "remote_model": "upstream"},
        }
        return _reply(request, values.get(request.url.path, {"models": []}))

    with patch("httpx.AsyncClient", _transport(handler)), pytest.raises(CostPolicyError) as caught:
        asyncio.run(OllamaProvider().call("alias", "source", retries=2))
    attempt = usage_attempts_from_exception(caught.value)[0]
    assert attempt.provider_type == "unknown"
    assert attempt.input_tokens > 0 and attempt.output_tokens > 0
    assert attempt.usage_source == "conservative"


@pytest.mark.parametrize(
    "failure", ["http", "redirect", "json", "bytes", "timeout", "duplicate", "nonfinite"]
)
def test_unavailable_or_unbounded_proof_fails_closed(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if failure == "bytes":
        monkeypatch.setattr(_ollama_show, "_LOCAL_PROOF_BYTES", 8)

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "http":
            return httpx.Response(404, request=request)
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://ollama.com"}, request=request)
        if failure == "json":
            return httpx.Response(200, content=b"invalid", request=request)
        if failure == "duplicate":
            return httpx.Response(
                200,
                content=b'{"cloud":{"disabled":false,"disabled":true,"source":"env"}}',
                request=request,
            )
        if failure == "nonfinite":
            return httpx.Response(
                200, content=b'{"cloud":{"disabled":true,"source":NaN}}', request=request
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("probe", request=request)
        return _reply(request, _STATUS)

    with patch("httpx.AsyncClient", _transport(handler)), pytest.raises(CostPolicyError):
        asyncio.run(OllamaProvider("http://localhost:11434").require_local("alias"))


def test_reused_provider_rechecks_changed_model_metadata() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/api/status":
            return _reply(request, _STATUS)
        if request.url.path == "/api/show":
            return _reply(
                request, _LOCAL if calls == 0 else {**_LOCAL, "remote_model": "cloud-alias"}
            )
        if request.url.path == "/api/chat":
            calls += 1
            return _reply(request, _CHAT)
        return _reply(request, {"models": []})

    provider = OllamaProvider()
    with patch("httpx.AsyncClient", _transport(handler)):
        assert asyncio.run(provider.call("alias", "first source")).text == "answer"
        with pytest.raises(CostPolicyError):
            asyncio.run(provider.call("alias", "second source"))
    assert calls == 1


def test_proof_has_a_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_ollama_show, "_SHOW_TIMEOUT_SECONDS", 0.01)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(60)
        return _reply(request, _STATUS)

    client_type = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return client_type(transport=httpx.MockTransport(handler), **kwargs)

    probe = ShowProbe(
        "http://localhost:11434", trust_env=False, parse_context_window=parse_context_window
    )
    with patch("httpx.AsyncClient", factory), pytest.raises(CostPolicyError) as caught:
        asyncio.run(probe.require_local("alias"))
    assert isinstance(caught.value.__cause__, TimeoutError)
