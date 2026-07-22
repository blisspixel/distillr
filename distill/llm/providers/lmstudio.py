# pyright: strict
"""LM Studio provider — local inference via OpenAI-compatible API.

Communicates with LM Studio's local server at http://localhost:1234/v1.
Override with LMSTUDIO_BASE_URL environment variable.
"""

from __future__ import annotations

import logging
import os
import time

import httpx
from openai import OpenAI

from distill.llm.cost_policy import classify_provider, local_provider_endpoint_is_valid
from distill.llm.providers._usage import conservative_usage
from distill.llm.retry import is_permanent_error
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    UsageAttemptSink,
    attach_usage_attempts,
    emit_usage_attempt,
)

logger = logging.getLogger(__name__)

LMSTUDIO_DEFAULT_URL = "http://localhost:1234/v1"


class LMStudioProvider:
    """LM Studio provider via OpenAI-compatible API."""

    def __init__(self, base_url: str = "") -> None:
        url = base_url or os.environ.get("LMSTUDIO_BASE_URL", LMSTUDIO_DEFAULT_URL)
        if not local_provider_endpoint_is_valid(url):
            raise ValueError(
                "LM Studio requires a valid HTTP(S) endpoint without credentials, "
                "query parameters, or fragments."
            )
        self._base_url = url
        self._provider_type = (
            "local" if classify_provider("lmstudio", endpoint=url) == "local" else "unknown"
        )
        self._trust_env = self._provider_type != "local"
        self._http_client = httpx.Client(trust_env=self._trust_env)
        self._client = OpenAI(
            api_key="lm-studio",
            base_url=url,
            http_client=self._http_client,
            max_retries=0,
        )

    async def call(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int = 8192,
        timeout: int = 300,
        retries: int = 2,
        temperature: float | None = None,
        call_type: str = "",
        reasoning_effort: str | None = None,  # Ignored for local models
        usage_sink: UsageAttemptSink | None = None,
    ) -> LLM_Response:
        """Send a prompt to LM Studio and return an LLM_Response.

        Retries on transient errors with exponential backoff (base 2s, factor 2).
        """
        last_error: Exception | None = None
        usage_attempts: list[LLMUsageAttempt] = []
        for attempt in range(retries + 1):
            try:
                kwargs: dict[str, object] = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                }
                if temperature is not None:
                    kwargs["temperature"] = temperature

                response = self._client.chat.completions.create(**kwargs)  # type: ignore[arg-type]

                choices = response.choices  # type: ignore[reportUnknownMemberType]
                if not choices:
                    text = ""
                    in_tok = 0
                    out_tok = 0
                else:
                    usage = response.usage  # type: ignore[reportUnknownMemberType]
                    text = str(choices[0].message.content or "")  # type: ignore[reportUnknownMemberType]
                    in_tok = int(usage.prompt_tokens) if usage else 0  # type: ignore[reportUnknownMemberType]
                    out_tok = int(usage.completion_tokens) if usage else 0  # type: ignore[reportUnknownMemberType]
            except Exception as exc:
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
                        provider_name="lmstudio",
                        provider_type=self._provider_type,
                        usage_source="conservative",
                        outcome="error",
                        error_type=type(exc).__name__,
                    ),
                    usage_sink,
                )
                # Check for connection errors specifically
                exc_str = str(exc).lower()
                is_conn_err = (
                    "connection" in exc_str or "refused" in exc_str or "timeout" in exc_str
                )
                if is_conn_err and attempt == 0:
                    surfaced = ConnectionError(
                        f"Cannot reach LM Studio at {self._base_url}. "
                        f"Start LM Studio and enable the local server."
                    )
                    attach_usage_attempts(surfaced, usage_attempts)
                    raise surfaced from exc

                last_error = exc
                attach_usage_attempts(exc, usage_attempts)
                if is_permanent_error(exc):
                    raise
                if attempt < retries:
                    wait = 2**attempt * 2
                    logger.warning(
                        "LM Studio error (attempt %d/%d): %s. Retrying in %ds...",
                        attempt + 1,
                        retries + 1,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                else:
                    raise
            else:
                emit_usage_attempt(
                    usage_attempts,
                    LLMUsageAttempt(
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        model=model,
                        provider_name="lmstudio",
                        provider_type=self._provider_type,
                        usage_source="reported",
                        outcome="success",
                    ),
                    usage_sink,
                )
                return LLM_Response(
                    text=text,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    model=model,
                    usage_attempts=tuple(usage_attempts),
                )

        assert last_error is not None  # nosec B101
        raise last_error
