"""Exercise the real SDK transport and parsing without contacting a provider."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import httpx2
import pytest
from openai import APIStatusError, DefaultHttpxClient, OpenAI

from distill.llm.openrouter_catalog import OpenRouterRequestShape
from distill.llm.providers import grok, lmstudio, openrouter
from distill.llm.usage import usage_attempts_from_exception
from distill.pipeline.costs import CostTracker, TokenUsage


@pytest.mark.parametrize(
    "provider_name,status_code",
    [("xai", 200), ("xai", 429), ("lmstudio", 200), ("lmstudio", 429), ("lmstudio", 302)],
)
def test_sdk_transport_preserves_request_usage_and_single_attempt(
    provider_name: str, status_code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if status_code != 200:
            return httpx2.Response(
                status_code,
                headers={"Location": "https://redirect.example/v1/chat/completions"},
                json={"error": {"message": "refused"}},
            )
        return httpx2.Response(
            200,
            json={
                "id": "completion-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "source summary"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
        )

    with DefaultHttpxClient(
        trust_env=False, follow_redirects=False, transport=httpx2.MockTransport(respond)
    ) as client:

        def sdk_client(*, api_key: str, base_url: str, max_retries: int) -> OpenAI:
            return OpenAI(
                api_key=api_key, base_url=base_url, max_retries=max_retries, http_client=client
            )

        def local_http_client(*, trust_env: bool, follow_redirects: bool) -> httpx2.Client:
            assert not trust_env
            assert not follow_redirects
            return client

        if provider_name == "xai":
            monkeypatch.setattr(grok, "OpenAI", sdk_client)
            provider = grok.GrokProvider("test-key")
            model = "grok-4.7"
            endpoint = "https://api.x.ai/v1/chat/completions"
            token_field = "max_completion_tokens"
        else:
            monkeypatch.setattr(lmstudio, "DefaultHttpxClient", local_http_client)
            provider = lmstudio.LMStudioProvider("http://localhost:1234/v1")
            model = "test-model"
            endpoint = "http://localhost:1234/v1/chat/completions"
            token_field = "max_tokens"

        if status_code == 200:
            result = asyncio.run(
                provider.call(model, "receipt", max_tokens=192, retries=0, reasoning_effort="high")
            )
            assert result.text == "source summary"
            assert (result.input_tokens, result.output_tokens) == (20, 5)
            assert len(result.usage_attempts) == 1
            assert result.usage_attempts[0].outcome == "success"
        else:
            with pytest.raises(APIStatusError) as raised:
                asyncio.run(provider.call(model, "receipt", max_tokens=192, retries=0))
            attempts = usage_attempts_from_exception(raised.value)
            assert len(attempts) == 1
            assert attempts[0].outcome == "error"
            assert attempts[0].usage_source == "conservative"

    assert len(requests) == 1
    assert str(requests[0].url) == endpoint
    payload = json.loads(requests[0].content)
    assert payload["model"] == model
    assert payload["messages"] == [{"role": "user", "content": "receipt"}]
    assert payload[token_field] == 192
    if provider_name == "xai" and status_code == 200:
        assert payload["reasoning_effort"] == "high"


@pytest.mark.parametrize("billed_cost", [None, 0.0, 0.001])
def test_openrouter_sdk_preserves_routed_identity_and_billing(
    billed_cost: float | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "id": "completion-test",
                "object": "chat.completion",
                "created": 0,
                "model": "glm-5.3-prime",
                "provider": "test-upstream",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "source summary"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "total_tokens": 25,
                    "cost": billed_cost,
                },
            },
        )

    with DefaultHttpxClient(trust_env=False, transport=httpx2.MockTransport(respond)) as client:

        def sdk_client(
            *, api_key: str, base_url: str, max_retries: int, default_headers: dict[str, str]
        ) -> OpenAI:
            return OpenAI(
                api_key=api_key,
                base_url=base_url,
                max_retries=max_retries,
                default_headers=default_headers,
                http_client=client,
            )

        monkeypatch.setattr(openrouter, "OpenAI", sdk_client)
        catalog = MagicMock()
        catalog.request_shape.return_value = OpenRouterRequestShape()
        provider = openrouter.OpenRouterProvider("test-key", endpoint_catalog=catalog)
        result = asyncio.run(
            provider.call("z-ai/glm-5.3-prime", "receipt", max_tokens=192, retries=0)
        )

    assert len(requests) == 1
    assert str(requests[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["max_tokens"] == 192
    assert payload["provider"]["max_price"] == {
        "prompt": 2.80,
        "completion": 8.80,
        "request": 0,
    }
    assert payload["provider"]["require_parameters"] is True
    assert payload["provider"]["zdr"] is True
    assert result.model == "z-ai/glm-5.3-prime"
    assert result.upstream_provider == "test-upstream"
    assert result.billed_cost_usd == billed_cost
    tracker = CostTracker(budget=1.0)
    tracker.record(TokenUsage.from_response(result))
    expected = billed_cost if billed_cost is not None else (20 * 2.80 + 5 * 8.80) / 1_000_000
    assert tracker.total_cost == pytest.approx(expected)
