# pyright: strict
"""Anthropic provider via the Messages API."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import cast

import httpx

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

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
_SONNET_5_PREFIX = "claude-sonnet-5"


class AnthropicProvider:
    """Anthropic Claude provider using the native Messages API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = ANTHROPIC_MESSAGES_URL,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url

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
        """Send a prompt to Anthropic and return an LLM_Response."""
        last_error: Exception | None = None
        usage_attempts: list[LLMUsageAttempt] = []
        for attempt in range(retries + 1):
            try:
                payload: dict[str, object] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if temperature is not None and _supports_custom_sampling(model):
                    payload["temperature"] = temperature
                if reasoning_effort is not None:
                    payload["output_config"] = {"effort": reasoning_effort}

                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        self._base_url,
                        headers={
                            "x-api-key": self._api_key,
                            "anthropic-version": ANTHROPIC_API_VERSION,
                            "content-type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                parsed = _response_from_payload(
                    cast(dict[str, object], data),
                    fallback_model=model,
                    prompt=prompt,
                    max_tokens=max_tokens,
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
                        provider_name="anthropic",
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
                        "Anthropic error (attempt %d/%d): %s. Retrying in %ds...",
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
                        input_tokens=parsed.input_tokens,
                        output_tokens=parsed.output_tokens,
                        model=parsed.model,
                        provider_name="anthropic",
                        provider_type="cloud",
                        usage_source=parsed.usage_source,
                        outcome="success",
                    ),
                    usage_sink,
                )
                return replace(parsed, usage_attempts=tuple(usage_attempts))

        assert last_error is not None  # nosec B101
        raise last_error


def _response_from_payload(
    data: dict[str, object],
    *,
    fallback_model: str,
    prompt: str,
    max_tokens: int,
) -> LLM_Response:
    content = data.get("content")
    text = ""
    if isinstance(content, list):
        content_blocks = cast(list[object], content)
        text = "".join(_content_block_text(block) for block in content_blocks)

    usage = data.get("usage")
    usage_row = cast(dict[str, object], usage) if isinstance(usage, dict) else {}
    input_tokens, output_tokens, estimated = usage_or_conservative(
        usage_row.get("input_tokens"),
        usage_row.get("output_tokens"),
        prompt=prompt,
        output_text=text,
        max_tokens=max_tokens,
    )
    if estimated:
        logger.warning("Anthropic response omitted valid usage metadata; using conservative bounds")
    model = data.get("model")
    return LLM_Response(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model if isinstance(model, str) and model else fallback_model,
        usage_source="conservative" if estimated else "reported",
    )


def _content_block_text(block: object) -> str:
    if not isinstance(block, dict):
        return ""
    row = cast(dict[str, object], block)
    if row.get("type") != "text":
        return ""
    text = row.get("text")
    return text if isinstance(text, str) else ""


def _supports_custom_sampling(model: str) -> bool:
    return not model.startswith(_SONNET_5_PREFIX)
