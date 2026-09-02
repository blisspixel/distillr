"""Human-readable classification of known LLM-provider failures.

Provider SDKs raise rich exceptions (``openai.PermissionDeniedError`` and
friends) that, uncaught, reach the terminal as a full traceback. For *expected
operational* conditions -- credits exhausted, rate limited, bad key -- that is
noise, not signal. This module maps those classes to a clean one-line message
with a concrete next step, and identifies the credit/auth class that an opt-in
local fallback should trigger on.

Kept dependency-free (only the stdlib + the local ``retry`` helper) so it stays
inside the foundational ``llm`` layer.
"""

from __future__ import annotations

from distill.llm.retry import is_permanent_error

__all__ = [
    "ProviderBusyTimeoutError",
    "describe_provider_error",
    "is_credit_or_auth_error",
]


class ProviderBusyTimeoutError(TimeoutError):
    """Raised when a provider stays occupied past a bounded wait."""

    def __init__(
        self,
        *,
        provider: str,
        requested_model: str,
        active_models: tuple[str, ...],
        timeout_seconds: float,
    ) -> None:
        self.provider = provider
        self.requested_model = requested_model
        self.active_models = active_models
        self.timeout_seconds = timeout_seconds
        active = ", ".join(active_models) or "another model"
        super().__init__(
            f"{provider} remained busy with {active} for {timeout_seconds:g}s while waiting "
            f"for requested model '{requested_model}'. No model was substituted. Retry after "
            "the current workload finishes, or use `ollama ps` and `ollama stop <model>` "
            "before retrying. Set DISTILL_LOCAL_TIMEOUT to a larger number of seconds if this "
            "bounded wait is too short."
        )


# Substrings that mark a billing/credit/quota problem in a provider message,
# independent of HTTP status (xAI returns 403 for credit exhaustion, others 402
# or 429 with a quota message).
_CREDIT_MARKERS: tuple[str, ...] = (
    "credit",
    "spending limit",
    "billing",
    "quota",
    "insufficient_quota",
    "out of credits",
    "payment",
    "exceeded your current",
)

_AUTH_MARKERS: tuple[str, ...] = (
    "api key",
    "api_key",
    "unauthorized",
    "authentication",
    "invalid key",
    "no auth credentials",
)


def _status_of(exc: Exception) -> int | None:
    """Best-effort HTTP status extraction across SDK exception shapes."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def is_credit_or_auth_error(exc: Exception) -> bool:
    """True when ``exc`` is a credit-exhaustion, billing, or auth failure.

    This is the class an opt-in local fallback should trigger on: retrying the
    same cloud provider will not help, but a local model can carry the run.
    """
    status = _status_of(exc)
    if status in (401, 402, 403):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in (*_CREDIT_MARKERS, *_AUTH_MARKERS))


def describe_provider_error(exc: Exception) -> str | None:
    """Return a clean one-line message for a known provider failure, else None.

    ``None`` means "not a recognized operational error" -- the caller should let
    the original exception propagate rather than masking an unexpected bug.
    """
    status = _status_of(exc)
    message = str(exc).lower()

    if isinstance(exc, ProviderBusyTimeoutError):
        return str(exc)

    if status in (402, 403) or any(marker in message for marker in _CREDIT_MARKERS):
        return (
            "LLM provider rejected the request: credits exhausted or spending limit reached. "
            "Top up the provider account, or set DISTILL_FALLBACK_PROVIDER=ollama (with "
            "DISTILL_FALLBACK_MODEL) to continue on a local model."
        )
    if status == 401 or any(marker in message for marker in _AUTH_MARKERS):
        return (
            "LLM provider rejected the API key (authentication failed). Check the key in your "
            ".env (XAI_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY / OPENROUTER_API_KEY)."
        )
    if status == 429:
        return (
            "LLM provider rate-limited the request (HTTP 429). Wait and retry, lower concurrency, "
            "or route this workload to a local model."
        )
    if is_permanent_error(exc) and status == 404:
        return (
            "LLM provider returned 404 (model or endpoint not found). Check the configured model "
            "id for this workload."
        )
    return None
