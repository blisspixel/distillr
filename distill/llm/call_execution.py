# pyright: strict
"""Provider-attempt execution, fallback routing, and usage telemetry."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, NoReturn, Protocol

from distill.llm.async_compat import run_coroutine_sync
from distill.llm.fallback import (
    FallbackConfig,
    fallback_failure_to_surface,
    fallback_target,
    require_fallback_route_allowed,
)
from distill.llm.metadata import LOCAL_PROVIDERS, local_call_timeout
from distill.llm.providers._usage import conservative_usage
from distill.llm.reasoning import configured_anthropic_effort, resolve_xai_reasoning_effort
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    UsageAttemptBatchSink,
    UsageAttemptSink,
    attach_usage_attempts,
    emit_usage_attempt,
    usage_attempts_from_exception,
)

logger = logging.getLogger(__name__)


class _PostResponseAccountingError(Exception):
    """Carry a successful response across a fail-closed accounting error."""

    def __init__(self, cause: Exception, response: LLM_Response) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.response = response


class ExecutionConfig(FallbackConfig, Protocol):
    """Router settings needed by the provider execution layer."""

    PREMIUM_WORKLOADS: tuple[str, ...]


@dataclass(frozen=True)
class CallOptions:
    """Stable inputs shared across a primary and optional fallback route."""

    config: ExecutionConfig
    workload_tag: str
    prompt: str
    max_tokens: int
    timeout: int
    retries: int
    temperature: float | None
    call_type: str
    ops_dir: str
    run_id: str
    usage_sink: UsageAttemptSink | None
    usage_batch_sink: UsageAttemptBatchSink | None
    provider_getter: Callable[[str], Any]


def execute_call(options: CallOptions, provider_name: str, model: str) -> LLM_Response:
    """Run a primary route and its policy-eligible fallback, if required."""

    started = time.monotonic()
    try:
        response = _run_provider_call(options, provider_name, model)
    except _PostResponseAccountingError as exc:
        _raise_post_response_accounting_error(
            options,
            provider_name,
            model,
            started=started,
            error=exc,
        )
    except Exception as exc:
        primary_attempts = usage_attempts_from_exception(exc)
        _record_route(
            options,
            provider_name,
            model,
            None,
            "error",
            type(exc).__name__,
            time.monotonic() - started,
            primary_attempts,
        )
        target = fallback_target(options.config, provider_name, exc)
        if target is None:
            raise
        return _call_fallback(options, provider_name, exc, primary_attempts, target)
    _record_route(
        options,
        provider_name,
        model,
        response,
        "success",
        "",
        time.monotonic() - started,
        response.usage_attempts,
    )
    return response


def _provider_type(provider_name: str) -> str:
    return "local" if provider_name in LOCAL_PROVIDERS else "cloud"


def _provider_reasoning_effort(
    config: ExecutionConfig,
    workload_tag: str,
    provider_name: str,
    model: str,
) -> str | None:
    if provider_name == "xai" and model.startswith("grok-4.3"):
        return resolve_xai_reasoning_effort(config, workload_tag)
    if provider_name == "anthropic" and model.startswith("claude-sonnet-5"):
        return configured_anthropic_effort(workload_tag)
    return None


def _capture_unreported_failure(
    options: CallOptions,
    provider_name: str,
    model: str,
    exc: Exception,
) -> None:
    provider_type = _provider_type(provider_name)
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


def _normalize_success_attempts(
    options: CallOptions,
    provider_name: str,
    model: str,
    response: LLM_Response,
) -> tuple[LLMUsageAttempt, ...]:
    provider_type = _provider_type(provider_name)
    attempts = tuple(
        replace(
            attempt,
            provider_name=provider_name,
            provider_type=provider_type,
        ).with_identity()
        for attempt in response.usage_attempts
    )
    if attempts:
        _emit_existing_attempts(options, attempts)
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
        ),
        options.usage_sink,
    )
    return tuple(collected)


def _emit_existing_attempts(
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


def _run_provider_call(
    options: CallOptions,
    provider_name: str,
    model: str,
) -> LLM_Response:
    provider = options.provider_getter(provider_name)
    effective_timeout = (
        local_call_timeout(options.timeout) if provider_name in LOCAL_PROVIDERS else options.timeout
    )
    call_kwargs: dict[str, object] = {
        "max_tokens": options.max_tokens,
        "timeout": effective_timeout,
        "retries": options.retries,
        "temperature": options.temperature,
        "call_type": options.call_type,
        "reasoning_effort": _provider_reasoning_effort(
            options.config,
            options.workload_tag,
            provider_name,
            model,
        ),
    }
    if provider_name not in LOCAL_PROVIDERS:
        call_kwargs["usage_sink"] = options.usage_sink
    coroutine = provider.call(model, options.prompt, **call_kwargs)
    try:
        response = run_coroutine_sync(coroutine)
    except Exception as exc:
        attempts = tuple(
            replace(
                row,
                provider_name=provider_name,
                provider_type=_provider_type(provider_name),
            ).with_identity()
            for row in usage_attempts_from_exception(exc)
        )
        if not attempts:
            _capture_unreported_failure(options, provider_name, model, exc)
        else:
            attach_usage_attempts(exc, attempts)
            _emit_existing_attempts(options, attempts)
        raise
    try:
        attempts = _normalize_success_attempts(options, provider_name, model, response)
    except Exception as exc:
        raise _PostResponseAccountingError(exc, response) from exc
    return replace(
        response,
        provider_name=provider_name,
        provider_type=_provider_type(provider_name),
        usage_attempts=attempts,
    )


def _call_fallback(
    options: CallOptions,
    primary_provider: str,
    primary_error: Exception,
    primary_attempts: tuple[LLMUsageAttempt, ...],
    target: tuple[str, str],
) -> LLM_Response:
    fallback_provider, fallback_model = target
    require_fallback_route_allowed(options.config, fallback_provider, options.workload_tag)
    logger.warning(
        "Primary provider '%s' failed (%s); falling back to '%s' / '%s'.",
        primary_provider,
        type(primary_error).__name__,
        fallback_provider,
        fallback_model,
    )
    started = time.monotonic()
    try:
        response = _run_provider_call(options, fallback_provider, fallback_model)
    except _PostResponseAccountingError as exc:
        _raise_post_response_accounting_error(
            options,
            fallback_provider,
            fallback_model,
            started=started,
            error=exc,
            prior_attempts=primary_attempts,
        )
    except Exception as fallback_error:
        fallback_attempts = usage_attempts_from_exception(fallback_error)
        _record_route(
            options,
            fallback_provider,
            fallback_model,
            None,
            "error",
            "FallbackFailed",
            time.monotonic() - started,
            fallback_attempts,
        )
        surfaced = fallback_failure_to_surface(primary_error, fallback_error)
        attach_usage_attempts(surfaced, primary_attempts + fallback_attempts)
        raise surfaced from None
    fallback_attempts = response.usage_attempts
    _record_route(
        options,
        fallback_provider,
        fallback_model,
        response,
        "success",
        "",
        time.monotonic() - started,
        fallback_attempts,
    )
    return replace(response, usage_attempts=primary_attempts + fallback_attempts)


def _raise_post_response_accounting_error(
    options: CallOptions,
    provider_name: str,
    model: str,
    *,
    started: float,
    error: _PostResponseAccountingError,
    prior_attempts: tuple[LLMUsageAttempt, ...] = (),
) -> NoReturn:
    """Record a paid success and surface its fail-closed accounting error."""

    route_attempts = usage_attempts_from_exception(error.cause)
    _record_route(
        options,
        provider_name,
        model,
        error.response,
        "success",
        "",
        time.monotonic() - started,
        route_attempts,
    )
    if prior_attempts:
        attach_usage_attempts(error.cause, prior_attempts + route_attempts)
    raise error.cause from None


def _record_route(
    options: CallOptions,
    provider_name: str,
    model: str,
    response: LLM_Response | None,
    outcome: str,
    error_type: str,
    elapsed: float,
    attempts: tuple[LLMUsageAttempt, ...],
) -> None:
    provider_type = _provider_type(provider_name)
    tokens_per_second = 0.0
    if response is not None and provider_type == "local" and elapsed > 0:
        tokens_per_second = response.output_tokens / elapsed
    input_tokens = sum(row.input_tokens for row in attempts)
    output_tokens = sum(row.output_tokens for row in attempts)
    if not attempts and response is not None:
        input_tokens = response.input_tokens
        output_tokens = response.output_tokens
    usage_source = (
        "conservative"
        if any(row.usage_source == "conservative" for row in attempts)
        else (attempts[-1].usage_source if attempts else "unavailable")
    )
    _emit_telemetry(
        ops_dir=options.ops_dir,
        model=response.model if response is not None else model,
        workload_tag=options.workload_tag,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_seconds=round(elapsed, 3),
        outcome=outcome,
        error_type=error_type,
        call_type=options.call_type,
        run_id=options.run_id,
        provider_type=provider_type,
        provider_name=provider_name,
        tokens_per_second=round(tokens_per_second, 2),
        usage_source=usage_source,
    )


def _emit_telemetry(
    *,
    ops_dir: str,
    model: str,
    workload_tag: str,
    input_tokens: int,
    output_tokens: int,
    elapsed_seconds: float,
    outcome: str,
    error_type: str,
    call_type: str,
    run_id: str,
    provider_type: str,
    provider_name: str,
    tokens_per_second: float,
    usage_source: str,
) -> None:
    if not ops_dir:
        return
    from distill.llm.telemetry import Telemetry_Record, write_record

    write_record(
        ops_dir,
        Telemetry_Record(
            model=model,
            workload_tag=workload_tag,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_seconds=elapsed_seconds,
            outcome=outcome,
            error_type=error_type,
            call_type=call_type,
            run_id=run_id,
            provider_type=provider_type,
            provider_name=provider_name,
            tokens_per_second=tokens_per_second,
            usage_source=usage_source,
        ),
    )
