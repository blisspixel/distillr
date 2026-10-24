# pyright: strict
"""Telemetry emission and local reasoning receipts for one provider attempt."""

from __future__ import annotations

from dataclasses import replace

from distill.llm.local_reasoning import lmstudio_effort_receipt, requested_effort_token
from distill.llm.types import LLM_Response
from distill.llm.usage import LLMUsageAttempt


def emit_telemetry(
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
    billed_cost_usd: float | None = None,
    upstream_provider: str = "",
    reasoning_requested: str = "",
    reasoning_sent: str = "",
    reasoning_support: str = "",
    reasoning_effective: str = "",
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
            billed_cost_usd=billed_cost_usd,
            upstream_provider=upstream_provider,
            reasoning_requested=reasoning_requested,
            reasoning_sent=reasoning_sent,
            reasoning_support=reasoning_support,
            reasoning_effective=reasoning_effective,
        ),
    )


def apply_ollama_call_kwargs(
    call_kwargs: dict[str, object],
    *,
    provider_name: str,
    workload_tag: str,
    explicit_think: bool | None,
) -> None:
    """Pass the boolean think switch and any untranslated effort token."""

    if provider_name != "ollama":
        return
    if explicit_think is not None:
        call_kwargs["local_think"] = explicit_think
    effort_token = requested_effort_token(workload_tag)
    if effort_token:
        call_kwargs["reasoning_effort"] = effort_token


def record_lmstudio_effort(
    response: LLM_Response,
    provider_name: str,
    workload_tag: str,
) -> LLM_Response:
    """Record an effort setting LM Studio did not send. Leave a filled receipt alone."""

    if provider_name != "lmstudio" or response.reasoning_requested:
        return response
    receipt = lmstudio_effort_receipt(workload_tag)
    if receipt is None:
        return response
    requested, sent, support, effective = receipt
    return replace(
        response,
        reasoning_requested=requested,
        reasoning_sent=sent,
        reasoning_support=support,
        reasoning_effective=effective,
    )


def reasoning_text(
    attempts: tuple[LLMUsageAttempt, ...],
    response: LLM_Response | None,
    field_name: str,
) -> str:
    for row in reversed(attempts):
        value = getattr(row, field_name, "")
        if isinstance(value, str) and value:
            return value
    if response is None:
        return ""
    value = getattr(response, field_name, "")
    return value if isinstance(value, str) else ""
