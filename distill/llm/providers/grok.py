# pyright: strict
"""Grok provider — xAI LLM backend via the OpenAI-compatible API.

Uses the ``openai`` Python package pointed at ``https://api.x.ai/v1``.
Retry logic uses exponential backoff (base 5s, factor 2).
"""

from __future__ import annotations

import logging
import time
from typing import cast

from openai import OpenAI
from openai.types.chat import ChatCompletion

from distill.llm.model_policy import (
    is_xai_media_generation_model,
    xai_media_generation_refusal,
)
from distill.llm.providers._usage import conservative_usage, usage_or_conservative
from distill.llm.retry import is_permanent_error
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    UsageAttemptSink,
    attach_usage_attempts,
    emit_usage_attempt,
)

logger = logging.getLogger(__name__)

XAI_BASE_URL = "https://api.x.ai/v1"


class GrokProvider:
    """xAI Grok provider using the OpenAI-compatible API."""

    def __init__(self, api_key: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=XAI_BASE_URL, max_retries=0)

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
        reasoning_effort: str | None = None,
        usage_sink: UsageAttemptSink | None = None,
    ) -> LLM_Response:
        """Send a prompt to xAI Grok and return an LLM_Response.

        Retries on transient errors with exponential backoff (base 5s, factor 2).
        """
        if is_xai_media_generation_model(model):
            raise ValueError(xai_media_generation_refusal(model))

        last_error: Exception | None = None
        usage_attempts: list[LLMUsageAttempt] = []
        for attempt in range(retries + 1):
            try:
                kwargs: dict[str, object] = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_completion_tokens": max_tokens,
                    "timeout": timeout,
                }
                if temperature is not None:
                    kwargs["temperature"] = temperature
                if reasoning_effort is not None and model.startswith(("grok-4.5", "grok-4.3")):
                    kwargs["reasoning_effort"] = reasoning_effort

                response = cast(
                    ChatCompletion,
                    self._client.chat.completions.create(
                        **kwargs  # type: ignore[arg-type] "OpenAI overloads cannot infer conditionally assembled optional arguments"
                    ),
                )

                choices = response.choices
                usage = cast(object, response.usage)
                text = str(choices[0].message.content or "") if choices else ""
                in_tok, out_tok, estimated = usage_or_conservative(
                    getattr(usage, "prompt_tokens", None),
                    getattr(usage, "completion_tokens", None),
                    prompt=prompt,
                    output_text=text,
                    max_tokens=max_tokens,
                )
                if estimated:
                    logger.warning(
                        "xAI response omitted valid usage metadata; using conservative bounds"
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
                        provider_name="xai",
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
                        "Provider error (attempt %d/%d): %s. Retrying in %ds...",
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
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        model=model,
                        provider_name="xai",
                        provider_type="cloud",
                        usage_source=source,
                        outcome="success",
                    ),
                    usage_sink,
                )
                return LLM_Response(
                    text=text,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    model=model,
                    usage_source=source,
                    usage_attempts=tuple(usage_attempts),
                )

        # Unreachable — satisfies type checker
        assert last_error is not None  # nosec B101
        raise last_error
