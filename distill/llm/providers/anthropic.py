# pyright: strict
"""Anthropic provider via the Messages API."""

from __future__ import annotations

import logging
import time
from typing import cast

import httpx

from distill.llm.retry import is_permanent_error
from distill.llm.router import LLM_Response

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
    ) -> LLM_Response:
        """Send a prompt to Anthropic and return an LLM_Response."""
        last_error: Exception | None = None
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

                return _response_from_payload(cast(dict[str, object], data), fallback_model=model)
            except Exception as exc:
                last_error = exc
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

        assert last_error is not None  # nosec B101
        raise last_error


def _response_from_payload(data: dict[str, object], *, fallback_model: str) -> LLM_Response:
    content = data.get("content")
    text = ""
    if isinstance(content, list):
        content_blocks = cast(list[object], content)
        text = "".join(_content_block_text(block) for block in content_blocks)

    usage = data.get("usage")
    usage_row = cast(dict[str, object], usage) if isinstance(usage, dict) else {}
    input_tokens = _non_negative_int(usage_row.get("input_tokens"))
    output_tokens = _non_negative_int(usage_row.get("output_tokens"))
    model = data.get("model")
    return LLM_Response(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model if isinstance(model, str) and model else fallback_model,
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


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0
