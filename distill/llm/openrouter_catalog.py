# pyright: strict
"""No-cost OpenRouter endpoint capability discovery and request shaping."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import cast

import httpx

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_CATALOG_TIMEOUT_SECONDS = 30
_PER_TOKEN_TO_PER_MILLION = 1_000_000

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OpenRouterRequestShape:
    """Parameters supported by at least one eligible endpoint for a model."""

    token_parameter: str = "max_tokens"
    send_temperature: bool = True
    endpoint_count: int = 0
    source: str = "compatibility"


class OpenRouterEndpointCatalog:
    """Resolve request parameters from OpenRouter's current endpoint catalog."""

    def __init__(self, api_key: str, *, zdr: bool) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._zdr = zdr
        self._zdr_endpoints: tuple[dict[str, object], ...] | None = None
        self._model_endpoints: dict[str, tuple[dict[str, object], ...]] = {}

    def request_shape(
        self,
        model: str,
        *,
        prompt_tokens: int,
        max_price: dict[str, float],
        reasoning_requested: bool,
        temperature_requested: bool,
    ) -> OpenRouterRequestShape:
        """Return the most compatible strict request shape for one model."""

        try:
            endpoints = self._endpoints_for(model)
        except Exception as exc:
            logger.warning(
                "OpenRouter endpoint metadata unavailable (%s); using compatibility defaults",
                _catalog_error_label(exc),
            )
            return _compatibility_shape(
                model,
                zdr=self._zdr,
                temperature_requested=temperature_requested,
            )

        eligible = tuple(
            endpoint
            for endpoint in endpoints
            if _within_price_ceiling(
                endpoint,
                prompt_tokens=prompt_tokens,
                max_price=max_price,
            )
        )
        if not eligible:
            eligible = endpoints
        healthy = tuple(endpoint for endpoint in eligible if _healthy(endpoint))
        if healthy:
            eligible = healthy

        if reasoning_requested:
            reasoning_endpoints = tuple(
                endpoint for endpoint in eligible if "reasoning" in _supported_parameters(endpoint)
            )
            if reasoning_endpoints:
                eligible = reasoning_endpoints

        if not eligible:
            return _compatibility_shape(
                model,
                zdr=self._zdr,
                temperature_requested=temperature_requested,
            )

        token_parameter = _best_token_parameter(eligible, model=model, zdr=self._zdr)
        token_endpoints = tuple(
            endpoint for endpoint in eligible if token_parameter in _supported_parameters(endpoint)
        )
        if not token_endpoints:
            token_endpoints = eligible
        send_temperature = temperature_requested and any(
            "temperature" in _supported_parameters(endpoint) for endpoint in token_endpoints
        )
        return OpenRouterRequestShape(
            token_parameter=token_parameter,
            send_temperature=send_temperature,
            endpoint_count=len(token_endpoints),
            source="zdr-endpoints" if self._zdr else "model-endpoints",
        )

    def _endpoints_for(self, model: str) -> tuple[dict[str, object], ...]:
        if self._zdr:
            if self._zdr_endpoints is None:
                self._zdr_endpoints = _fetch_endpoints(
                    f"{OPENROUTER_BASE_URL}/endpoints/zdr",
                    headers=self._headers,
                    nested=False,
                )
            return tuple(
                endpoint for endpoint in self._zdr_endpoints if endpoint.get("model_id") == model
            )

        cached = self._model_endpoints.get(model)
        if cached is not None:
            return cached
        endpoints = _fetch_endpoints(
            f"{OPENROUTER_BASE_URL}/models/{model}/endpoints",
            headers=self._headers,
            nested=True,
        )
        self._model_endpoints[model] = endpoints
        return endpoints


def _fetch_endpoints(
    url: str,
    *,
    headers: dict[str, str],
    nested: bool,
) -> tuple[dict[str, object], ...]:
    response = httpx.get(url, headers=headers, timeout=_CATALOG_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = cast(object, response.json())
    if not isinstance(payload, dict):
        raise ValueError("OpenRouter endpoint response was not an object")
    data = cast(dict[object, object], payload).get("data")
    if nested:
        if not isinstance(data, dict):
            raise ValueError("OpenRouter model endpoint response omitted data")
        data = cast(dict[object, object], data).get("endpoints")
    if not isinstance(data, list):
        raise ValueError("OpenRouter endpoint response omitted endpoint rows")
    rows = cast(list[object], data)
    return tuple(cast(dict[str, object], row) for row in rows if isinstance(row, dict))


def _best_token_parameter(
    endpoints: tuple[dict[str, object], ...],
    *,
    model: str,
    zdr: bool,
) -> str:
    max_tokens_count = sum(
        "max_tokens" in _supported_parameters(endpoint) for endpoint in endpoints
    )
    max_completion_count = sum(
        "max_completion_tokens" in _supported_parameters(endpoint) for endpoint in endpoints
    )
    if max_completion_count and max_completion_count >= max_tokens_count:
        return "max_completion_tokens"
    if max_tokens_count:
        return "max_tokens"
    return _compatibility_shape(model, zdr=zdr, temperature_requested=False).token_parameter


def _compatibility_shape(
    model: str,
    *,
    zdr: bool,
    temperature_requested: bool,
) -> OpenRouterRequestShape:
    author = model.partition("/")[0]
    if author == "openai" and zdr:
        return OpenRouterRequestShape(
            token_parameter="max_completion_tokens",
            send_temperature=False,
        )
    if author in {"anthropic", "google", "openai"}:
        return OpenRouterRequestShape(
            token_parameter="max_tokens",
            send_temperature=False,
        )
    return OpenRouterRequestShape(send_temperature=temperature_requested)


def _supported_parameters(endpoint: dict[str, object]) -> frozenset[str]:
    raw = endpoint.get("supported_parameters")
    if not isinstance(raw, list):
        return frozenset()
    values = cast(list[object], raw)
    return frozenset(value for value in values if isinstance(value, str))


def _healthy(endpoint: dict[str, object]) -> bool:
    status = endpoint.get("status")
    return status is None or status == 0


def _within_price_ceiling(
    endpoint: dict[str, object],
    *,
    prompt_tokens: int,
    max_price: dict[str, float],
) -> bool:
    if not max_price:
        return True
    pricing = endpoint.get("pricing")
    if not isinstance(pricing, dict):
        return True
    normalized = cast(dict[object, object], pricing)
    override = _active_price_override(normalized, prompt_tokens=prompt_tokens)
    for field in ("prompt", "completion"):
        ceiling = max_price.get(field)
        if ceiling is None:
            continue
        raw = override.get(field, normalized.get(field))
        rate = _finite_nonnegative_float(raw)
        if rate is not None and rate * _PER_TOKEN_TO_PER_MILLION > ceiling:
            return False
    return True


def _active_price_override(
    pricing: dict[object, object],
    *,
    prompt_tokens: int,
) -> dict[object, object]:
    raw_overrides = pricing.get("overrides")
    if not isinstance(raw_overrides, list):
        return {}
    overrides = cast(list[object], raw_overrides)
    active: dict[object, object] = {}
    active_threshold = -1
    for raw in overrides:
        if not isinstance(raw, dict):
            continue
        row = cast(dict[object, object], raw)
        threshold = row.get("min_prompt_tokens")
        if (
            isinstance(threshold, int)
            and not isinstance(threshold, bool)
            and active_threshold < threshold <= prompt_tokens
        ):
            active = row
            active_threshold = threshold
    return active


def _finite_nonnegative_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        normalized = float(value)
    except ValueError:
        return None
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


def _catalog_error_label(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return f"HTTP {status}"
    return type(exc).__name__
