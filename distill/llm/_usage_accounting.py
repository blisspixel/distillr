# pyright: strict
"""Usage-attempt normalization, emission, and failure accounting.

Split out from ``call_execution`` to keep each module under the package size
cap. These helpers translate a provider call's raw usage rows into the
canonical per-route attempt records, emit them through the configured sinks,
and synthesize conservative records when a failure reports none.
``call_execution`` re-exports them under their original private names.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from distill.llm.providers._usage import conservative_usage
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    attach_usage_attempts,
    emit_usage_attempt,
)

if TYPE_CHECKING:
    from distill.llm.call_execution import CallOptions


def capture_unreported_failure(
    options: CallOptions,
    provider_name: str,
    model: str,
    exc: Exception,
    provider_type: str,
) -> None:
    if provider_type == "cloud":
        input_tokens, output_tokens = conservative_usage(
            prompt=options.prompt,
            max_tokens=options.max_tokens,
        )
        usage_source = "conservative"
    else:
        input_tokens, output_tokens = 0, 0
        usage_source = "unavailable"
    collected: list[LLMUsageAttempt] = []
    emit_usage_attempt(
        collected,
        LLMUsageAttempt(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            provider_name=provider_name,
            provider_type=provider_type,
            usage_source=usage_source,
            outcome="error",
            error_type=type(exc).__name__,
        ),
        options.usage_sink,
    )
    attach_usage_attempts(exc, collected)


def normalize_success_attempts(
    options: CallOptions,
    provider_name: str,
    model: str,
    response: LLM_Response,
    provider_type: str,
) -> tuple[LLMUsageAttempt, ...]:
    attempts = tuple(
        _normalized_attempt_identity(provider_name, provider_type, attempt).with_identity()
        for attempt in response.usage_attempts
    )
    if attempts:
        emit_existing_attempts(options, attempts)
        return attempts
    collected: list[LLMUsageAttempt] = []
    emit_usage_attempt(
        collected,
        LLMUsageAttempt(
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            model=response.model or model,
            provider_name=provider_name,
            provider_type=provider_type,
            usage_source=response.usage_source,
            outcome="success",
            billed_cost_usd=response.billed_cost_usd,
            upstream_provider=response.upstream_provider,
        ),
        options.usage_sink,
    )
    return tuple(collected)


def _normalized_attempt_identity(
    route_provider: str,
    route_provider_type: str,
    attempt: LLMUsageAttempt,
) -> LLMUsageAttempt:
    if route_provider == "agent" and attempt.provider_type == "host-managed":
        return attempt
    return replace(
        attempt,
        provider_name=route_provider,
        provider_type=route_provider_type,
    )


def emit_existing_attempts(
    options: CallOptions,
    attempts: tuple[LLMUsageAttempt, ...],
) -> None:
    if options.usage_batch_sink is not None:
        try:
            options.usage_batch_sink(attempts)
        except Exception as exc:
            attach_usage_attempts(exc, attempts)
            raise
        return
    if options.usage_sink is None:
        return
    first_error: Exception | None = None
    for attempt in attempts:
        try:
            options.usage_sink(attempt)
        except Exception as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        attach_usage_attempts(first_error, attempts)
        raise first_error
