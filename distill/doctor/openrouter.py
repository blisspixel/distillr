# pyright: strict
"""Live OpenRouter key and selected-model validation."""

from __future__ import annotations

import math
from typing import cast

from distill.config import DistillConfig
from distill.llm.async_compat import run_coroutine_sync
from distill.llm.cost_policy import CostPolicyError, route_block_reason
from distill.llm.openrouter_catalog import OPENROUTER_BASE_URL
from distill.llm.providers._usage import conservative_usage
from distill.llm.providers.openrouter import OpenRouterProvider
from distill.llm.usage import usage_attempts_from_exception
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.usage_records import TokenUsage

_PROBE_PROMPT = "hi"
_PROBE_MAX_TOKENS = 1


def validate_openrouter_key(
    config: DistillConfig,
    tracker: CostTracker,
    *,
    model: str = "",
) -> tuple[str, str]:
    """Validate the key, and the exact model route when one is selected."""

    api_key = config.openrouter_api_key.get_secret_value().strip()
    if not api_key:
        return ("not_set", "")
    blocked = route_block_reason(
        cost_mode=config.distill_cost_mode,
        provider="openrouter",
        workload="doctor-key-validation",
    )
    if blocked:
        return ("skipped", blocked)
    if not model:
        return _validate_key_metadata(api_key)

    projection = _probe_usage(model=model, outcome="authorized")
    try:
        tracker.authorize_token_usage(projection)
    except (BudgetExceededError, CostPolicyError) as exc:
        return ("skipped", str(exc))

    provider = OpenRouterProvider(api_key, zdr=config.distill_openrouter_zdr)
    try:
        response = run_coroutine_sync(
            provider.call(
                model,
                _PROBE_PROMPT,
                max_tokens=_PROBE_MAX_TOKENS,
                retries=0,
                timeout=30,
            )
        )
    except BaseException as exc:
        if isinstance(exc, Exception):
            attempts = usage_attempts_from_exception(exc)
            if attempts:
                tracker.record_attempts(attempts, call_type="doctor-key-validation")
            else:
                tracker.record(_probe_usage(model=model, outcome="error", exc=exc))
            return (_error_status(exc), str(exc))
        tracker.record(_probe_usage(model=model, outcome="error", exc=exc))
        raise
    tracker.record(TokenUsage.from_response(response, call_type="doctor-key-validation"))
    return ("ok", response.model)


def _validate_key_metadata(api_key: str) -> tuple[str, str]:
    try:
        import httpx

        response = httpx.get(
            f"{OPENROUTER_BASE_URL}/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = cast(object, response.json())
    except Exception as exc:
        return (_error_status(exc), str(exc))
    return ("ok", _key_metadata_detail(payload))


def _key_metadata_detail(payload: object) -> str:
    prefix = "key accepted"
    if not isinstance(payload, dict):
        return f"{prefix}; select an exact model to probe inference"
    data = cast(dict[object, object], payload).get("data")
    if not isinstance(data, dict):
        return f"{prefix}; select an exact model to probe inference"
    normalized = cast(dict[object, object], data)
    if "limit" not in normalized:
        return f"{prefix}; select an exact model to probe inference"
    raw_limit = normalized.get("limit")
    if raw_limit is None:
        return f"{prefix}; no key spending limit configured"
    limit = _finite_nonnegative_number(raw_limit)
    remaining = _finite_nonnegative_number(normalized.get("limit_remaining"))
    if limit is None:
        return f"{prefix}; select an exact model to probe inference"
    if remaining is None:
        return f"{prefix}; ${limit:.2f} key spending limit"
    return f"{prefix}; ${limit:.2f} key spending limit, ${remaining:.2f} remaining"


def _finite_nonnegative_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        return None
    return normalized


def _probe_usage(
    *,
    model: str,
    outcome: str,
    exc: BaseException | None = None,
) -> TokenUsage:
    input_tokens, output_tokens = conservative_usage(
        prompt=_PROBE_PROMPT,
        max_tokens=_PROBE_MAX_TOKENS,
    )
    return TokenUsage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        model=model,
        call_type="doctor-key-validation",
        provider_name="openrouter",
        provider_type="cloud",
        usage_source="conservative",
        outcome=outcome,
        error_type=type(exc).__name__ if exc is not None else "",
    )


def _error_status(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return "invalid" if status in {401, 403} else "unknown"
