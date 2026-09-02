# pyright: strict, reportPrivateUsage=false
"""Unit tests for the explicit paid OpenRouter provider."""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from distill.llm.openrouter_catalog import OpenRouterRequestShape
from distill.llm.providers.openrouter import (
    OpenRouterProvider,
    OpenRouterRequestError,
    _nonnegative_finite_number,
    _provider_preferences,
    _registered_price_ceiling,
    _sanitized_request_error,
)
from distill.llm.usage import LLMUsageAttempt, usage_attempts_from_exception


def _response(
    *,
    text: str = "answer",
    model: str = "x-ai/grok-4.6",
    cost: object = 0.00125,
    provider: str = "xai",
    prompt_tokens: object = 12,
    completion_tokens: object = 7,
    metadata_provider: str = "",
) -> SimpleNamespace:
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model_extra={"cost": cost},
    )
    model_extra: dict[str, object] = {"provider": provider}
    if metadata_provider:
        model_extra["openrouter_metadata"] = {
            "endpoints": {
                "available": [
                    {"provider": "not-selected", "selected": False},
                    {"provider": metadata_provider, "selected": True},
                ]
            }
        }
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=usage,
        model=model,
        model_extra=model_extra,
    )


def _provider(
    *,
    zdr: bool = True,
    shape: OpenRouterRequestShape | None = None,
) -> tuple[OpenRouterProvider, MagicMock, MagicMock]:
    catalog = MagicMock()
    catalog.request_shape.return_value = shape or OpenRouterRequestShape()
    with patch("distill.llm.providers.openrouter.OpenAI") as client_type:
        client = MagicMock()
        client_type.return_value = client
        provider = OpenRouterProvider(
            "test-key",
            zdr=zdr,
            endpoint_catalog=catalog,
        )
    return provider, client, catalog


def test_init_uses_openrouter_endpoint_without_hidden_sdk_retries() -> None:
    with patch("distill.llm.providers.openrouter.OpenAI") as client_type:
        OpenRouterProvider("test-key")

    client_type.assert_called_once_with(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        default_headers={"X-OpenRouter-Metadata": "enabled"},
    )


def test_success_captures_exact_cost_model_upstream_and_constraints() -> None:
    provider, client, catalog = _provider()
    client.chat.completions.create.return_value = _response()

    result = asyncio.run(
        provider.call(
            "x-ai/grok-4.6",
            "hello",
            max_tokens=64,
            temperature=0.2,
            reasoning_effort="low",
            session_id="run-123",
        )
    )

    assert result.text == "answer"
    assert result.model == "x-ai/grok-4.6"
    assert result.billed_cost_usd == 0.00125
    assert result.upstream_provider == "xai"
    assert result.usage_attempts[0].billed_cost_usd == 0.00125
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_tokens"] == 64
    assert kwargs["temperature"] == 0.2
    assert kwargs["extra_body"]["session_id"] == hashlib.sha256(b"run-123").hexdigest()
    assert kwargs["extra_body"]["reasoning"] == {"effort": "low", "exclude": True}
    preferences = kwargs["extra_body"]["provider"]
    assert preferences == {
        "allow_fallbacks": True,
        "data_collection": "deny",
        "require_parameters": True,
        "sort": "price",
        "zdr": True,
        "max_price": {"prompt": 2.0, "completion": 6.0},
    }
    catalog.request_shape.assert_called_once_with(
        "x-ai/grok-4.6",
        prompt_tokens=1029,
        max_price={"prompt": 2.0, "completion": 6.0},
        reasoning_requested=True,
        temperature_requested=True,
    )


def test_endpoint_shape_uses_completion_limit_and_omits_temperature() -> None:
    provider, client, _catalog = _provider(
        shape=OpenRouterRequestShape(
            token_parameter="max_completion_tokens",
            send_temperature=False,
            endpoint_count=2,
            source="zdr-endpoints",
        )
    )
    client.chat.completions.create.return_value = _response()

    asyncio.run(
        provider.call(
            "openai/gpt-5.6-terra",
            "hello",
            max_tokens=64,
            temperature=0.2,
        )
    )

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_completion_tokens"] == 64
    assert "max_tokens" not in kwargs
    assert "temperature" not in kwargs


def test_router_metadata_selected_endpoint_takes_priority() -> None:
    provider, client, _catalog = _provider()
    client.chat.completions.create.return_value = _response(
        provider="legacy-provider",
        metadata_provider="selected-provider",
    )

    result = asyncio.run(provider.call("x-ai/grok-4.6", "hello"))

    assert result.upstream_provider == "selected-provider"


def test_zdr_can_be_explicitly_disabled() -> None:
    provider, client, _catalog = _provider(zdr=False)
    client.chat.completions.create.return_value = _response()

    asyncio.run(provider.call("x-ai/grok-4.6", "hello", retries=0))

    preferences = client.chat.completions.create.call_args.kwargs["extra_body"]["provider"]
    assert preferences["zdr"] is False


def test_unknown_model_runs_without_an_unverified_price_ceiling() -> None:
    provider, client, _catalog = _provider()
    client.chat.completions.create.return_value = _response(
        model="meta-llama/llama-3.3-70b-instruct"
    )

    asyncio.run(provider.call("meta-llama/llama-3.3-70b-instruct", "hello"))

    preferences = client.chat.completions.create.call_args.kwargs["extra_body"]["provider"]
    assert "max_price" not in preferences


def test_long_context_price_ceiling_matches_registered_long_rates() -> None:
    ceiling = _registered_price_ceiling(
        "x-ai/grok-4.6",
        prompt="x" * 199_000,
        max_tokens=1,
    )

    assert ceiling == {"prompt": 4.0, "completion": 12.0}


def test_per_query_pricing_is_not_used_as_a_token_ceiling() -> None:
    assert (
        _registered_price_ceiling(
            "google/deep-research",
            prompt="hello",
            max_tokens=1,
        )
        == {}
    )


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/auto",
        "openrouter/free",
        "openrouter/bodybuilder",
        "~anthropic/claude-sonnet-latest",
        "anthropic/claude-sonnet-4:free",
        "anthropic/claude-sonnet-4-latest",
        "Claude/Sonnet",
        "missing-slash",
    ],
)
def test_nonconcrete_model_ids_are_rejected_before_contact(model: str) -> None:
    provider, client, _catalog = _provider()

    with pytest.raises(ValueError, match="OpenRouter"):
        asyncio.run(provider.call(model, "hello"))

    client.chat.completions.create.assert_not_called()


def test_xai_media_model_is_rejected_before_contact() -> None:
    provider, client, _catalog = _provider()

    with pytest.raises(ValueError, match="text analysis model"):
        asyncio.run(provider.call("x-ai/grok-imagine-image", "hello"))

    client.chat.completions.create.assert_not_called()


def test_missing_usage_and_cost_fall_back_conservatively(caplog: pytest.LogCaptureFixture) -> None:
    provider, client, _catalog = _provider()
    client.chat.completions.create.return_value = _response(
        text="",
        cost="not-a-number",
        provider="",
        prompt_tokens=None,
        completion_tokens=None,
    )

    result = asyncio.run(provider.call("x-ai/grok-4.6", "hello", max_tokens=9, retries=0))

    assert result.input_tokens == 1029
    assert result.output_tokens == 9
    assert result.usage_source == "conservative"
    assert result.billed_cost_usd is None
    assert result.upstream_provider == ""
    assert "billed-cost" in caplog.text


def test_retry_preserves_each_attempt_and_billed_success() -> None:
    provider, client, _catalog = _provider()
    client.chat.completions.create.side_effect = [RuntimeError("temporary"), _response()]

    with patch("distill.llm.providers.openrouter.time.sleep") as sleep:
        result = asyncio.run(provider.call("x-ai/grok-4.6", "hello", max_tokens=5, retries=1))

    assert [row.outcome for row in result.usage_attempts] == ["error", "success"]
    assert result.usage_attempts[0].billed_cost_usd is None
    assert result.usage_attempts[1].billed_cost_usd == 0.00125
    sleep.assert_called_once_with(5)


def test_exhausted_retry_attaches_conservative_attempts() -> None:
    provider, client, _catalog = _provider()
    client.chat.completions.create.side_effect = RuntimeError("offline")

    with (
        patch("distill.llm.providers.openrouter.time.sleep"),
        pytest.raises(RuntimeError, match="offline") as raised,
    ):
        asyncio.run(provider.call("x-ai/grok-4.6", "hello", retries=1))

    assert len(usage_attempts_from_exception(raised.value)) == 2


def test_http_error_is_sanitized_without_losing_status_or_usage() -> None:
    class SensitiveError(RuntimeError):
        status_code = 429

    provider, client, _catalog = _provider()
    client.chat.completions.create.side_effect = SensitiveError("raw metadata user_id=user-secret")

    with pytest.raises(OpenRouterRequestError, match="rate-limited") as raised:
        asyncio.run(provider.call("x-ai/grok-4.6", "hello", retries=0))

    assert raised.value.status_code == 429
    assert "user-secret" not in str(raised.value)
    assert len(usage_attempts_from_exception(raised.value)) == 1


def test_error_without_http_status_is_preserved() -> None:
    error = RuntimeError("offline")

    assert _sanitized_request_error(error) is error


def test_usage_sink_can_stop_retry_after_accounting() -> None:
    class Stop(Exception):
        pass

    provider, client, _catalog = _provider()
    client.chat.completions.create.side_effect = RuntimeError("offline")

    def stop(_attempt: LLMUsageAttempt) -> None:
        raise Stop

    with pytest.raises(Stop):
        asyncio.run(
            provider.call(
                "x-ai/grok-4.6",
                "hello",
                retries=2,
                usage_sink=stop,
            )
        )

    assert client.chat.completions.create.call_count == 1


@pytest.mark.parametrize("value", [True, -1, float("inf"), "0.1", None])
def test_invalid_billed_cost_values_are_rejected(value: object) -> None:
    assert _nonnegative_finite_number(value) is None


def test_zero_billed_cost_and_non_dict_extras_are_supported() -> None:
    assert _nonnegative_finite_number(0) == 0.0
    preferences = _provider_preferences(
        "meta-llama/llama-3.3-70b-instruct",
        prompt="hello",
        max_tokens=5,
        zdr=True,
    )
    assert preferences["data_collection"] == "deny"
