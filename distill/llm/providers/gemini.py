# pyright: strict
"""Gemini provider — Google Gemini LLM backend via the google-genai SDK.

Uses lazy import of ``google.genai`` to avoid import-time dependency on the SDK.
Retry logic uses exponential backoff (base 5s, factor 2).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from distill.llm.router import LLM_Response

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Google Gemini provider using the google-genai SDK."""

    def __init__(self, api_key: str) -> None:
        from google import genai  # type: ignore[import-untyped]

        self._client: Any = genai.Client(api_key=api_key)

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
        reasoning_effort: str | None = None,  # accepted for provider-interface parity; unused
    ) -> LLM_Response:
        """Send a prompt to Google Gemini and return an LLM_Response.

        Retries on transient errors with exponential backoff (base 5s, factor 2).
        """
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                config: dict[str, Any] = {"max_output_tokens": max_tokens}
                if temperature is not None:
                    config["temperature"] = temperature

                response: Any = self._client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config,
                )

                text: str = response.text or ""
                usage: Any = getattr(response, "usage_metadata", None)
                input_tokens: int = getattr(usage, "prompt_token_count", 0) or 0
                output_tokens: int = getattr(usage, "candidates_token_count", 0) or 0

                return LLM_Response(
                    text=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=model,
                )
            except Exception as exc:
                last_error = exc
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

        # Unreachable — satisfies type checker
        assert last_error is not None  # nosec B101
        raise last_error
