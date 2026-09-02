# pyright: strict
"""Tests for no-cost OpenRouter endpoint capability discovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import httpx
import pytest

import distill.llm.openrouter_catalog as catalog_module
from distill.llm.openrouter_catalog import OpenRouterEndpointCatalog


class _Response:
    def __init__(self, payload: object, *, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> object:
        return self._payload


def _install_get(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> list[tuple[str, dict[str, object]]]:
    calls: list[tuple[str, dict[str, object]]] = []

    def get(url: str, **kwargs: object) -> _Response:
        calls.append((url, kwargs))
        return _Response(payload)

    monkeypatch.setattr(catalog_module.httpx, "get", get)
    return calls


def _endpoint(
    model: str,
    *parameters: str,
    prompt: str = "0.000001",
    completion: str = "0.000002",
    status: int = 0,
    overrides: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    pricing: dict[str, object] = {"prompt": prompt, "completion": completion}
    if overrides is not None:
        pricing["overrides"] = overrides
    return {
        "model_id": model,
        "supported_parameters": list(parameters),
        "pricing": pricing,
        "status": status,
    }


def test_zdr_catalog_filters_model_and_caches_full_endpoint_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_get(
        monkeypatch,
        {
            "data": [
                _endpoint("google/gemini", "max_tokens", "reasoning"),
                _endpoint("x-ai/grok", "max_tokens", "temperature"),
            ]
        },
    )
    catalog = OpenRouterEndpointCatalog("secret", zdr=True)

    shape = catalog.request_shape(
        "google/gemini",
        prompt_tokens=100,
        max_price={"prompt": 2.0, "completion": 4.0},
        reasoning_requested=True,
        temperature_requested=True,
    )
    catalog.request_shape(
        "x-ai/grok",
        prompt_tokens=100,
        max_price={},
        reasoning_requested=False,
        temperature_requested=True,
    )

    assert shape.token_parameter == "max_tokens"
    assert shape.send_temperature is False
    assert shape.endpoint_count == 1
    assert shape.source == "zdr-endpoints"
    assert len(calls) == 1
    assert calls[0][0] == "https://openrouter.ai/api/v1/endpoints/zdr"
    assert calls[0][1]["headers"] == {"Authorization": "Bearer secret"}


def test_non_zdr_catalog_uses_model_endpoint_and_caches_per_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_get(
        monkeypatch,
        {"data": {"endpoints": [_endpoint("ignored", "max_completion_tokens")]}},
    )
    catalog = OpenRouterEndpointCatalog("secret", zdr=False)

    first = catalog.request_shape(
        "openai/model",
        prompt_tokens=1,
        max_price={},
        reasoning_requested=False,
        temperature_requested=False,
    )
    second = catalog.request_shape(
        "openai/model",
        prompt_tokens=1,
        max_price={},
        reasoning_requested=False,
        temperature_requested=False,
    )

    assert first == second
    assert first.token_parameter == "max_completion_tokens"
    assert first.source == "model-endpoints"
    assert len(calls) == 1
    assert calls[0][0].endswith("/models/openai/model/endpoints")


def test_completion_limit_wins_when_support_is_tied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_get(
        monkeypatch,
        {
            "data": [
                _endpoint("openai/model", "max_completion_tokens"),
                _endpoint("openai/model", "max_tokens"),
            ]
        },
    )

    shape = OpenRouterEndpointCatalog("secret", zdr=True).request_shape(
        "openai/model",
        prompt_tokens=1,
        max_price={},
        reasoning_requested=False,
        temperature_requested=False,
    )

    assert shape.token_parameter == "max_completion_tokens"


def test_price_ceiling_excludes_incompatible_expensive_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_get(
        monkeypatch,
        {
            "data": [
                _endpoint(
                    "openai/model",
                    "max_completion_tokens",
                    prompt="0.000003",
                    completion="0.000007",
                ),
                _endpoint("openai/model", "max_tokens", "temperature"),
            ]
        },
    )

    shape = OpenRouterEndpointCatalog("secret", zdr=True).request_shape(
        "openai/model",
        prompt_tokens=10,
        max_price={"prompt": 2.0, "completion": 6.0},
        reasoning_requested=False,
        temperature_requested=True,
    )

    assert shape.token_parameter == "max_tokens"
    assert shape.send_temperature is True


def test_long_context_override_is_used_for_price_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_get(
        monkeypatch,
        {
            "data": [
                _endpoint(
                    "x-ai/model",
                    "max_completion_tokens",
                    overrides=[
                        {
                            "min_prompt_tokens": 1_000,
                            "prompt": "0.000005",
                            "completion": "0.000010",
                        }
                    ],
                ),
                _endpoint("x-ai/model", "max_tokens"),
            ]
        },
    )

    shape = OpenRouterEndpointCatalog("secret", zdr=True).request_shape(
        "x-ai/model",
        prompt_tokens=2_000,
        max_price={"prompt": 2.0, "completion": 6.0},
        reasoning_requested=False,
        temperature_requested=False,
    )

    assert shape.token_parameter == "max_tokens"


def test_healthy_and_reasoning_capable_endpoints_are_preferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_get(
        monkeypatch,
        {
            "data": [
                _endpoint("anthropic/model", "max_completion_tokens", status=2),
                _endpoint("anthropic/model", "max_tokens", "reasoning"),
                _endpoint("anthropic/model", "max_completion_tokens"),
            ]
        },
    )

    shape = OpenRouterEndpointCatalog("secret", zdr=True).request_shape(
        "anthropic/model",
        prompt_tokens=1,
        max_price={},
        reasoning_requested=True,
        temperature_requested=False,
    )

    assert shape.token_parameter == "max_tokens"
    assert shape.endpoint_count == 1


@pytest.mark.parametrize(
    ("model", "zdr", "expected_token", "expected_temperature"),
    [
        ("openai/model", True, "max_completion_tokens", False),
        ("openai/model", False, "max_tokens", False),
        ("google/model", True, "max_tokens", False),
        ("anthropic/model", True, "max_tokens", False),
        ("x-ai/model", True, "max_tokens", True),
    ],
)
def test_empty_catalog_uses_conservative_compatibility_defaults(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    zdr: bool,
    expected_token: str,
    expected_temperature: bool,
) -> None:
    payload: object = {"data": []} if zdr else {"data": {"endpoints": []}}
    _install_get(monkeypatch, payload)

    shape = OpenRouterEndpointCatalog("secret", zdr=zdr).request_shape(
        model,
        prompt_tokens=1,
        max_price={},
        reasoning_requested=False,
        temperature_requested=True,
    )

    assert shape.token_parameter == expected_token
    assert shape.send_temperature is expected_temperature
    assert shape.source == "compatibility"


@pytest.mark.parametrize("payload", [None, {"data": None}, {"data": {}}])
def test_malformed_catalog_falls_back_without_exposing_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    payload: object,
) -> None:
    _install_get(monkeypatch, payload)

    shape = OpenRouterEndpointCatalog("secret", zdr=True).request_shape(
        "x-ai/model",
        prompt_tokens=1,
        max_price={},
        reasoning_requested=False,
        temperature_requested=True,
    )

    assert shape.source == "compatibility"
    assert "secret" not in caplog.text
    assert "ValueError" in caplog.text


def test_http_catalog_error_logs_only_status(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = httpx.Request("GET", "https://openrouter.ai/api/v1/endpoints/zdr")
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError(
        "sensitive account metadata",
        request=request,
        response=response,
    )

    def get(*_args: object, **_kwargs: object) -> _Response:
        return _Response({}, error=error)

    monkeypatch.setattr(
        catalog_module.httpx,
        "get",
        cast(Callable[..., object], get),
    )

    OpenRouterEndpointCatalog("secret", zdr=True).request_shape(
        "x-ai/model",
        prompt_tokens=1,
        max_price={},
        reasoning_requested=False,
        temperature_requested=False,
    )

    assert "HTTP 500" in caplog.text
    assert "sensitive" not in caplog.text
    assert "secret" not in caplog.text


def test_unusable_endpoint_values_do_not_break_capability_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_get(
        monkeypatch,
        {
            "data": [
                {
                    "model_id": "x-ai/model",
                    "supported_parameters": "max_tokens",
                    "pricing": {
                        "prompt": True,
                        "completion": "unknown",
                        "overrides": [{"min_prompt_tokens": True, "prompt": "not-a-number"}],
                    },
                }
            ]
        },
    )

    shape = OpenRouterEndpointCatalog("secret", zdr=True).request_shape(
        "x-ai/model",
        prompt_tokens=1,
        max_price={"prompt": 1.0, "completion": 1.0},
        reasoning_requested=False,
        temperature_requested=True,
    )

    assert shape.token_parameter == "max_tokens"
    assert shape.send_temperature is False
