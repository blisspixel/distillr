# pyright: strict
"""Per-attempt usage evidence shared by providers, routing, and cost ledgers."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, cast
from uuid import uuid4

UsageOutcome = Literal["success", "error"]
MAX_USAGE_TOKENS = 1_000_000_000_000


@dataclass(frozen=True)
class LLMUsageAttempt:
    """Usage evidence for one provider request, including failed requests."""

    input_tokens: int
    output_tokens: int
    model: str
    provider_name: str
    provider_type: str
    usage_source: str
    outcome: UsageOutcome
    error_type: str = ""
    attempt_id: str = ""

    def with_identity(self) -> LLMUsageAttempt:
        """Return this attempt with a collision-resistant ledger identity."""

        if self.attempt_id:
            return self
        return LLMUsageAttempt(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model=self.model,
            provider_name=self.provider_name,
            provider_type=self.provider_type,
            usage_source=self.usage_source,
            outcome=self.outcome,
            error_type=self.error_type,
            attempt_id=uuid4().hex,
        )


UsageAttemptSink = Callable[[LLMUsageAttempt], None]
UsageAttemptBatchSink = Callable[[tuple[LLMUsageAttempt, ...]], None]
UsageAttemptAuthorizer = Callable[[LLMUsageAttempt], None]
UsageAttemptReservation = Callable[[LLMUsageAttempt], AbstractContextManager[None]]
_EXCEPTION_ATTEMPTS_ATTR = "_distill_usage_attempts"


def attach_usage_attempts(
    exc: Exception,
    attempts: tuple[LLMUsageAttempt, ...] | list[LLMUsageAttempt],
) -> None:
    """Attach exact attempt evidence without changing the exception's type."""

    setattr(exc, _EXCEPTION_ATTEMPTS_ATTR, tuple(attempts))


def usage_attempts_from_exception(exc: Exception) -> tuple[LLMUsageAttempt, ...]:
    """Read validated attempt evidence attached to a provider exception."""

    value: object = getattr(exc, _EXCEPTION_ATTEMPTS_ATTR, ())
    if not isinstance(value, tuple):
        return ()
    rows = cast(tuple[object, ...], value)
    if not all(isinstance(row, LLMUsageAttempt) for row in rows):
        return ()
    return cast(tuple[LLMUsageAttempt, ...], rows)


def emit_usage_attempt(
    attempts: list[LLMUsageAttempt],
    attempt: LLMUsageAttempt,
    sink: UsageAttemptSink | None,
) -> LLMUsageAttempt:
    """Append and emit one attempt, preserving evidence if the sink stops the call."""

    identified = attempt.with_identity()
    attempts.append(identified)
    if sink is None:
        return identified
    try:
        sink(identified)
    except Exception as exc:
        attach_usage_attempts(exc, attempts)
        raise
    return identified
