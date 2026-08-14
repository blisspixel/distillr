# pyright: strict
"""Conservative usage accounting for metered provider responses."""

from __future__ import annotations

import hashlib

from distill.llm.providers._agent_protocol import HostSubmission
from distill.llm.usage import MAX_USAGE_TOKENS, LLMUsageAttempt

_CONSERVATIVE_INPUT_OVERHEAD_TOKENS = 1024


def conservative_usage(*, prompt: str, max_tokens: int) -> tuple[int, int]:
    """Return fail-closed token bounds for a request with no usage metadata."""

    return (
        max(1, len(prompt.encode("utf-8")) + _CONSERVATIVE_INPUT_OVERHEAD_TOKENS),
        min(MAX_USAGE_TOKENS, max(0, max_tokens)),
    )


def projected_usage_attempt(
    *,
    prompt: str,
    max_tokens: int,
    model: str,
    provider_name: str,
    provider_type: str,
) -> LLMUsageAttempt:
    """Build the conservative upper-bound row used for pre-call admission."""

    input_tokens, output_tokens = conservative_usage(prompt=prompt, max_tokens=max_tokens)
    return LLMUsageAttempt(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        provider_name=provider_name,
        provider_type=provider_type,
        usage_source="conservative",
        outcome="success",
    )


def deferred_usage_attempt(
    *,
    prompt: str,
    prompt_hash: str,
    task_filename: str,
    max_tokens: int,
    submission: HostSubmission | None = None,
) -> LLMUsageAttempt:
    """Build stable conservative evidence for one deferred external task."""

    attempt_id = hashlib.sha256(f"agent:{prompt_hash}:{task_filename}".encode()).hexdigest()
    if submission is None:
        input_tokens, output_tokens = conservative_usage(
            prompt=prompt,
            max_tokens=max_tokens,
        )
        model = "agent"
        provider_name = "agent"
        provider_type = "host-managed"
        usage_source = "conservative"
    else:
        if submission.input_tokens is None:
            input_tokens, output_tokens = conservative_usage(
                prompt=prompt,
                max_tokens=max_tokens,
            )
            usage_source = "conservative"
        else:
            input_tokens = submission.input_tokens
            output_tokens = submission.output_tokens or 0
            usage_source = submission.usage_source
        model = submission.model_label
        provider_name = submission.host
        provider_type = "host-managed"
    return LLMUsageAttempt(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        provider_name=provider_name,
        provider_type=provider_type,
        usage_source=usage_source,
        outcome="success",
        attempt_id=attempt_id,
    )


def combined_output_usage(
    candidate_value: object,
    thoughts_value: object,
    *,
    output_text: str,
) -> int | None:
    """Combine visible and thinking tokens when metadata matches the response."""

    candidate_tokens = _non_negative_int(candidate_value)
    thoughts_tokens = _non_negative_int(thoughts_value)
    if (
        candidate_tokens is None
        or thoughts_tokens is None
        or (output_text and candidate_tokens == 0)
    ):
        return None
    combined = candidate_tokens + thoughts_tokens
    return combined if combined <= MAX_USAGE_TOKENS else None


def usage_or_conservative(
    input_value: object,
    output_value: object,
    *,
    prompt: str,
    output_text: str,
    max_tokens: int,
) -> tuple[int, int, bool]:
    """Return reported usage or conservative bounds when metadata is invalid."""

    input_tokens = _non_negative_int(input_value)
    output_tokens = _non_negative_int(output_value)
    if prompt and input_tokens == 0:
        input_tokens = None
    if output_text and output_tokens == 0:
        output_tokens = None
    estimated = input_tokens is None or output_tokens is None
    if input_tokens is None:
        input_tokens = conservative_usage(prompt=prompt, max_tokens=max_tokens)[0]
    if output_tokens is None:
        output_tokens = min(MAX_USAGE_TOKENS, max(0, max_tokens))
    return input_tokens, output_tokens, estimated


def _non_negative_int(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > MAX_USAGE_TOKENS
    ):
        return None
    return value
