# pyright: strict
"""Adapt budget-aware usage trackers into pre-call admission controls."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import cast

from distill.llm.types import UsageTracker
from distill.llm.usage import (
    LLMUsageAttempt,
    UsageAttemptAuthorizer,
    UsageAttemptReservation,
)


def usage_admission(
    usage_tracker: UsageTracker | None,
    *,
    call_type: str,
) -> tuple[UsageAttemptAuthorizer | None, UsageAttemptReservation | None]:
    """Build strict pre-call controls only when a tracker carries a budget."""

    if usage_tracker is None or getattr(usage_tracker, "budget_limit", None) is None:
        return None, None
    raw_authorize: object = getattr(usage_tracker, "authorize_attempt", None)
    raw_reserve: object = getattr(usage_tracker, "reserve_attempt", None)
    if not callable(raw_authorize) or not callable(raw_reserve):
        raise TypeError(
            "a budget-carrying usage tracker must implement attempt authorization and reservation"
        )
    authorize_method = cast(Callable[..., None], raw_authorize)
    reserve_method = cast(Callable[..., AbstractContextManager[None]], raw_reserve)

    def authorize(attempt: LLMUsageAttempt) -> None:
        authorize_method(attempt, call_type=call_type)

    def reserve(attempt: LLMUsageAttempt) -> AbstractContextManager[None]:
        return reserve_method(attempt, call_type=call_type)

    return authorize, reserve
