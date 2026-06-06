"""Exponential backoff with jitter for LLM call retries."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

__all__ = [
    "PERMANENT_ERRORS",
    "compute_delay",
    "is_permanent_error",
    "retry_with_backoff",
]

# HTTP status codes and exception types that should never be retried.
PERMANENT_ERRORS: tuple[int, ...] = (400, 401, 403, 404, 422)


def is_permanent_error(exc: Exception) -> bool:
    """True if ``exc`` carries an HTTP status that must never be retried.

    Inspects the common SDK exception shapes -- a ``status_code`` attribute
    (the openai SDK) or a nested ``response.status_code`` (httpx). Returns
    False when no status can be determined, so callers safely fall back to
    their normal retry behavior rather than misclassifying an unknown error.
    """
    status: object = getattr(exc, "status_code", None)
    if status is None:
        response: object = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return status in PERMANENT_ERRORS


def compute_delay(
    attempt: int,
    base_delay: float = 2.0,
    jitter_fraction: float = 0.5,
) -> float:
    """Compute retry delay with jitter for a given attempt number.

    Formula: base_delay * 2^attempt + uniform(0, jitter_fraction * base_delay * 2^attempt)

    Args:
        attempt: Zero-based attempt number (0 = first retry).
        base_delay: Base delay in seconds before exponential scaling.
        jitter_fraction: Maximum jitter as a fraction of the exponential delay.

    Returns:
        Delay in seconds (always >= base_delay * 2^attempt).
    """
    exponential = base_delay * (2**attempt)
    jitter = random.uniform(0, jitter_fraction * exponential)
    return exponential + jitter


def retry_with_backoff[T](
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 2.0,
    jitter_fraction: float = 0.5,
    is_permanent: Callable[[Exception], bool] | None = None,
    on_retry: Callable[[int, float, Exception], None] | None = None,
) -> T:
    """Execute fn with exponential backoff + jitter on failure.

    Args:
        fn: Zero-argument callable to execute.
        max_retries: Maximum number of retry attempts (total calls = max_retries + 1).
        base_delay: Base delay in seconds for backoff calculation.
        jitter_fraction: Maximum jitter as a fraction of the exponential delay.
        is_permanent: Optional callback that returns True if an exception should
            not be retried (e.g., auth errors). If True, raises immediately.
        on_retry: Optional callback invoked before each retry sleep with
            (attempt, delay, error) arguments.

    Returns:
        The return value of fn on success.

    Raises:
        Exception: The last exception if all retries are exhausted, or a permanent
            error on the first occurrence.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc

            # Check if this is a permanent error that should not be retried.
            if is_permanent is not None and is_permanent(exc):
                raise

            # If we've exhausted all retries, raise the last error.
            if attempt >= max_retries:
                raise

            # Compute delay and notify callback before sleeping.
            delay = compute_delay(attempt, base_delay, jitter_fraction)
            if on_retry is not None:
                on_retry(attempt, delay, exc)

            time.sleep(delay)

    # This should be unreachable, but satisfies type checkers.
    raise last_error  # type: ignore[misc]
