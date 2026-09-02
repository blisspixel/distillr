# pyright: strict
"""OpenRouter provider through its OpenAI-compatible chat API."""

from __future__ import annotations

import hashlib
import logging
import math
import time
from typing import cast

from openai import OpenAI
from openai.types.chat import ChatCompletion

from distill.llm.cost import get_pricing, has_known_pricing
from distill.llm.openrouter_catalog import (
    OPENROUTER_BASE_URL,
    OpenRouterEndpointCatalog,
    OpenRouterRequestShape,
)
from distill.llm.openrouter_policy import validate_openrouter_model_id
from distill.llm.providers._usage import conservative_usage, usage_or_conservative
from distill.llm.retry import is_permanent_error
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    UsageAttemptSink,
    attach_usage_attempts,
    emit_usage_attempt,
)

logger = logging.getLogger(__name__)


class OpenRouterRequestError(RuntimeError):
    """Sanitized OpenRouter failure that retains only HTTP classification."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        messages = {
            401: "OpenRouter rejected the API key (HTTP 401).",
            402: "OpenRouter rejected the request for billing or credit reasons (HTTP 402).",
            403: "OpenRouter rejected the API key or account policy (HTTP 403).",
            404: (
                "OpenRouter found no endpoint matching the configured model, parameters, "
                "and privacy policy (HTTP 404)."
            ),
            429: "OpenRouter or its upstream provider rate-limited the request (HTTP 429).",
        }
        super().__init__(
            messages.get(status_code, f"OpenRouter request failed (HTTP {status_code}).")
        )


class OpenRouterProvider:
    """OpenRouter text provider with privacy and price routing constraints."""

    def __init__(
        self,
        api_key: str,
        *,
        zdr: bool = True,
        endpoint_catalog: OpenRouterEndpointCatalog | None = None,
    ) -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            max_retries=0,
            default_headers={"X-OpenRouter-Metadata": "enabled"},
        )
        self._zdr = zdr
        self._endpoint_catalog = endpoint_catalog or OpenRouterEndpointCatalog(
            api_key,
            zdr=zdr,
        )

    async def call(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int = 8192,
        timeout: int = 300,
        retries: int = 2,
        temperature: float | None = None,
        call_type: str = "",
        reasoning_effort: str | None = None,
        usage_sink: UsageAttemptSink | None = None,
        session_id: str = "",
    ) -> LLM_Response:
        """Send one prompt and retain OpenRouter's billed-cost evidence."""

        del call_type
        model = validate_openrouter_model_id(model)
        last_error: Exception | None = None
        usage_attempts: list[LLMUsageAttempt] = []
        price_ceiling = _registered_price_ceiling(
            model,
            prompt=prompt,
            max_tokens=max_tokens,
        )
        prompt_tokens, _ = conservative_usage(prompt=prompt, max_tokens=max_tokens)
        request_shape = self._endpoint_catalog.request_shape(
            model,
            prompt_tokens=prompt_tokens,
            max_price=price_ceiling,
            reasoning_requested=reasoning_effort is not None,
            temperature_requested=temperature is not None,
        )
        for attempt in range(retries + 1):
            try:
                kwargs = _request_options(
                    model,
                    prompt,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    session_id=session_id,
                    zdr=self._zdr,
                    price_ceiling=price_ceiling,
                    request_shape=request_shape,
                )
                response = cast(
                    ChatCompletion,
                    self._client.chat.completions.create(
                        **kwargs  # type: ignore[arg-type] "OpenAI overloads cannot infer assembled OpenRouter options"
                    ),
                )
                usage = cast(object, response.usage)
                choices = response.choices
                text = str(choices[0].message.content or "") if choices else ""
                input_tokens, output_tokens, estimated = usage_or_conservative(
                    getattr(usage, "prompt_tokens", None),
                    getattr(usage, "completion_tokens", None),
                    prompt=prompt,
                    output_text=text,
                    max_tokens=max_tokens,
                )
                billed_cost = _nonnegative_finite_number(_extra_value(usage, "cost"))
                upstream_provider = _selected_upstream_provider(response)
                resolved_model = response.model or model
                if estimated:
                    logger.warning(
                        "OpenRouter response omitted valid usage metadata; using conservative bounds"
                    )
                if billed_cost is None:
                    logger.warning(
                        "OpenRouter response omitted valid billed-cost metadata; "
                        "using registered token pricing when available"
                    )
            except Exception as exc:
                surfaced = _sanitized_request_error(exc)
                last_error = surfaced
                failed_input, failed_output = conservative_usage(
                    prompt=prompt,
                    max_tokens=max_tokens,
                )
                emit_usage_attempt(
                    usage_attempts,
                    LLMUsageAttempt(
                        input_tokens=failed_input,
                        output_tokens=failed_output,
                        model=model,
                        provider_name="openrouter",
                        provider_type="cloud",
                        usage_source="conservative",
                        outcome="error",
                        error_type=type(exc).__name__,
                    ),
                    usage_sink,
                )
                attach_usage_attempts(surfaced, usage_attempts)
                if is_permanent_error(exc):
                    raise surfaced from None
                if attempt < retries:
                    wait = 2**attempt * 5
                    logger.warning(
                        "OpenRouter error (attempt %d/%d): %s. Retrying in %ds...",
                        attempt + 1,
                        retries + 1,
                        surfaced,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    raise surfaced from None
            else:
                source = "conservative" if estimated else "reported"
                emit_usage_attempt(
                    usage_attempts,
                    LLMUsageAttempt(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model=resolved_model,
                        provider_name="openrouter",
                        provider_type="cloud",
                        usage_source=source,
                        outcome="success",
                        billed_cost_usd=billed_cost,
                        upstream_provider=upstream_provider,
                    ),
                    usage_sink,
                )
                return LLM_Response(
                    text=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=resolved_model,
                    usage_source=source,
                    usage_attempts=tuple(usage_attempts),
                    billed_cost_usd=billed_cost,
                    upstream_provider=upstream_provider,
                )

        assert last_error is not None  # nosec B101
        raise last_error


def _request_options(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    timeout: int,
    temperature: float | None,
    reasoning_effort: str | None,
    session_id: str,
    zdr: bool,
    price_ceiling: dict[str, float],
    request_shape: OpenRouterRequestShape,
) -> dict[str, object]:
    extra_body: dict[str, object] = {
        "provider": _provider_preferences(
            model,
            prompt=prompt,
            max_tokens=max_tokens,
            zdr=zdr,
            price_ceiling=price_ceiling,
        )
    }
    if session_id:
        extra_body["session_id"] = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    if reasoning_effort is not None:
        extra_body["reasoning"] = {"effort": reasoning_effort, "exclude": True}
    kwargs: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": timeout,
        "extra_body": extra_body,
        request_shape.token_parameter: max_tokens,
    }
    if temperature is not None and request_shape.send_temperature:
        kwargs["temperature"] = temperature
    return kwargs


def _provider_preferences(
    model: str,
    *,
    prompt: str,
    max_tokens: int,
    zdr: bool,
    price_ceiling: dict[str, float] | None = None,
) -> dict[str, object]:
    preferences: dict[str, object] = {
        "allow_fallbacks": True,
        "data_collection": "deny",
        "require_parameters": True,
        "sort": "price",
        "zdr": zdr,
    }
    ceiling = (
        price_ceiling
        if price_ceiling is not None
        else _registered_price_ceiling(model, prompt=prompt, max_tokens=max_tokens)
    )
    if ceiling:
        preferences["max_price"] = ceiling
    return preferences


def _registered_price_ceiling(
    model: str,
    *,
    prompt: str,
    max_tokens: int,
) -> dict[str, float]:
    if not has_known_pricing(model):
        return {}
    rates = get_pricing(model)
    if "per_query" in rates:
        return {}
    input_tokens, _ = conservative_usage(prompt=prompt, max_tokens=max_tokens)
    threshold = rates.get("long_context_min_input")
    use_long = threshold is not None and input_tokens >= threshold
    prompt_rate = rates.get("long_input" if use_long else "input")
    completion_rate = rates.get("long_output" if use_long else "output")
    if prompt_rate is None or completion_rate is None:
        return {}
    return {"prompt": prompt_rate, "completion": completion_rate}


def _extra_value(value: object, key: str) -> object:
    direct = getattr(value, key, None)
    if direct is not None:
        return direct
    extra = getattr(value, "model_extra", None)
    if isinstance(extra, dict):
        return cast(dict[object, object], extra).get(key)
    return None


def _text_extra(value: object, key: str) -> str:
    raw = _extra_value(value, key)
    return raw if isinstance(raw, str) else ""


def _selected_upstream_provider(response: object) -> str:
    metadata = _extra_value(response, "openrouter_metadata")
    if isinstance(metadata, dict):
        endpoints = cast(dict[object, object], metadata).get("endpoints")
        if isinstance(endpoints, dict):
            available = cast(dict[object, object], endpoints).get("available")
            if isinstance(available, list):
                for raw in cast(list[object], available):
                    if not isinstance(raw, dict):
                        continue
                    endpoint = cast(dict[object, object], raw)
                    provider = endpoint.get("provider")
                    if endpoint.get("selected") is True and isinstance(provider, str):
                        return provider
    return _text_extra(response, "provider")


def _nonnegative_finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


def _sanitized_request_error(exc: Exception) -> Exception:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return OpenRouterRequestError(status)
    return exc
