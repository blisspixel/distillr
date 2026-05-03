# pyright: strict
"""Grok provider — xAI LLM backend via the OpenAI-compatible API.

Uses the ``openai`` Python package pointed at ``https://api.x.ai/v1``.
Retry logic uses exponential backoff (base 5s, factor 2).
"""

from __future__ import annotations

import logging
import time

from openai import OpenAI

from distill.llm.router import LLM_Response

logger = logging.getLogger(__name__)

XAI_BASE_URL = "https://api.x.ai/v1"


class GrokProvider:
    """xAI Grok provider using the OpenAI-compatible API."""

    def __init__(self, api_key: str) -> None:
        self._client = OpenAI(api_key=api_key, base_url=XAI_BASE_URL)

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
    ) -> LLM_Response:
        """Send a prompt to xAI Grok and return an LLM_Response.

        Retries on transient errors with exponential backoff (base 5s, factor 2).
        """
        last_error: Exception | None = None
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

                response = self._client.chat.completions.create(**kwargs)  # type: ignore[arg-type]

                choices = response.choices  # type: ignore[reportUnknownMemberType]
                if not choices:
                    return LLM_Response(text="", input_tokens=0, output_tokens=0, model=model)

                usage = response.usage  # type: ignore[reportUnknownMemberType]
                text: str = str(choices[0].message.content or "")  # type: ignore[reportUnknownMemberType]
                in_tok: int = int(usage.prompt_tokens) if usage else 0  # type: ignore[reportUnknownMemberType]
                out_tok: int = int(usage.completion_tokens) if usage else 0  # type: ignore[reportUnknownMemberType]
                return LLM_Response(
                    text=text,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    model=model,
                )
            except Exception as exc:
                last_error = exc
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

        # Unreachable — satisfies type checker
        assert last_error is not None  # nosec B101
        raise last_error
