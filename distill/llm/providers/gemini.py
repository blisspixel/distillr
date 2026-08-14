# pyright: strict
"""Gemini provider — Google Gemini LLM backend via the google-genai SDK.

Uses lazy import of ``google.genai`` to avoid import-time dependency on the SDK.
Retry logic uses exponential backoff (base 5s, factor 2).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from google.genai.types import HttpOptionsDict

from distill.llm.providers._usage import (
    combined_output_usage,
    conservative_usage,
    usage_or_conservative,
)
from distill.llm.retry import is_permanent_error
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    UsageAttemptSink,
    attach_usage_attempts,
    emit_usage_attempt,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 300

# Gemini 3.6 Flash, 3.7 Flash, 3.5 Flash-Lite, and later releases deprecate sampling
# parameters (temperature / top_p / top_k). The API currently ignores them and
# will reject them on future generations; omit rather than forward.
_NO_CUSTOM_SAMPLING_PREFIXES: tuple[str, ...] = (
    "gemini-3.7",
    "gemini-3.6",
    "gemini-3.5-flash-lite",
    "gemini-4",
)


def _supports_custom_sampling(model: str) -> bool:
    normalized = model.strip().lower()
    return not normalized.startswith(_NO_CUSTOM_SAMPLING_PREFIXES)


def _http_options(timeout_seconds: int) -> HttpOptionsDict:
    return cast(
        "HttpOptionsDict",
        {
            "retry_options": {"attempts": 1},
            "timeout": timeout_seconds * 1_000,
        },
    )


def _close_custom_client(client: Any) -> None:
    """Best-effort cleanup that cannot turn a completed request into failure."""

    try:
        client.close()
    except Exception:
        logger.warning("Gemini custom transport cleanup failed", exc_info=True)


class GeminiProvider:
    """Google Gemini provider using the google-genai SDK."""

    def __init__(self, api_key: str) -> None:
        from google import genai  # type: ignore[import-untyped]

        self._api_key = api_key
        self._client_factory: Any = genai.Client
        self._default_timeout = _DEFAULT_TIMEOUT_SECONDS
        self._client: Any = genai.Client(
            api_key=api_key,
            http_options=_http_options(_DEFAULT_TIMEOUT_SECONDS),
        )

    def _client_for_timeout(self, timeout: int) -> tuple[Any, bool]:
        factory: Any = getattr(self, "_client_factory", None)
        if factory is None or timeout == getattr(self, "_default_timeout", None):
            return self._client, False
        return (
            factory(
                api_key=self._api_key,
                http_options=_http_options(timeout),
            ),
            True,
        )

    async def call(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int = 8192,
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
        retries: int = 2,
        temperature: float | None = None,
        call_type: str = "",
        reasoning_effort: str | None = None,  # accepted for provider-interface parity; unused
        usage_sink: UsageAttemptSink | None = None,
    ) -> LLM_Response:
        """Send a prompt to Google Gemini and return an LLM_Response.

        Retries on transient errors with exponential backoff (base 5s, factor 2).
        """
        last_error: Exception | None = None
        usage_attempts: list[LLMUsageAttempt] = []
        client, close_client = self._client_for_timeout(timeout)
        try:
            for attempt in range(retries + 1):
                try:
                    config: dict[str, Any] = {"max_output_tokens": max_tokens}
                    if temperature is not None and _supports_custom_sampling(model):
                        config["temperature"] = temperature

                    response: Any = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=config,
                    )

                    text: str = response.text or ""
                    usage: Any = getattr(response, "usage_metadata", None)
                    thoughts_tokens = getattr(usage, "thoughts_token_count", 0)
                    if thoughts_tokens is None:
                        thoughts_tokens = 0
                    input_tokens, output_tokens, estimated = usage_or_conservative(
                        getattr(usage, "prompt_token_count", None),
                        combined_output_usage(
                            getattr(usage, "candidates_token_count", None),
                            thoughts_tokens,
                            output_text=text,
                        ),
                        prompt=prompt,
                        output_text=text,
                        max_tokens=max_tokens,
                    )
                    if estimated:
                        logger.warning(
                            "Gemini response omitted valid usage metadata; using conservative bounds"
                        )
                except Exception as exc:
                    last_error = exc
                    failed_input, failed_output = conservative_usage(
                        prompt=prompt,
                        max_tokens=max_tokens,
                    )
                    emit_usage_attempt(
                        usage_attempts,
                        LLMUsageAttempt(
                            input_tokens=failed_input,
                            output_tokens=failed_output,
                            model=model,
                            provider_name="gemini",
                            provider_type="cloud",
                            usage_source="conservative",
                            outcome="error",
                            error_type=type(exc).__name__,
                        ),
                        usage_sink,
                    )
                    attach_usage_attempts(exc, usage_attempts)
                    if is_permanent_error(exc):
                        raise
                    if attempt < retries:
                        wait = 2**attempt * 5
                        logger.warning(
                            "Gemini error (attempt %d/%d): %s. Retrying in %ds...",
                            attempt + 1,
                            retries + 1,
                            exc,
                            wait,
                        )
                        time.sleep(wait)
                    else:
                        raise
                else:
                    source = "conservative" if estimated else "reported"
                    emit_usage_attempt(
                        usage_attempts,
                        LLMUsageAttempt(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            model=model,
                            provider_name="gemini",
                            provider_type="cloud",
                            usage_source=source,
                            outcome="success",
                        ),
                        usage_sink,
                    )
                    return LLM_Response(
                        text=text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model=model,
                        usage_source=source,
                        usage_attempts=tuple(usage_attempts),
                    )
        finally:
            if close_client:
                _close_custom_client(client)

        # Unreachable — satisfies type checker
        assert last_error is not None  # nosec B101
        raise last_error
