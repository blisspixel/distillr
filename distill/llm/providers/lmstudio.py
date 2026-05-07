# pyright: strict
"""LM Studio provider — local inference via OpenAI-compatible API.

Communicates with LM Studio's local server at http://localhost:1234/v1.
Override with LMSTUDIO_BASE_URL environment variable.
"""

from __future__ import annotations

import logging
import os
import time

from openai import OpenAI

from distill.llm.router import LLM_Response

logger = logging.getLogger(__name__)

LMSTUDIO_DEFAULT_URL = "http://localhost:1234/v1"


class LMStudioProvider:
    """LM Studio provider via OpenAI-compatible API."""

    def __init__(self, base_url: str = "") -> None:
        url = base_url or os.environ.get("LMSTUDIO_BASE_URL", LMSTUDIO_DEFAULT_URL)
        self._base_url = url
        self._client = OpenAI(api_key="lm-studio", base_url=url)

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
    ) -> LLM_Response:
        """Send a prompt to LM Studio and return an LLM_Response.

        Retries on transient errors with exponential backoff (base 2s, factor 2).
        """
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                kwargs: dict = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                }
                if temperature is not None:
                    kwargs["temperature"] = temperature

                response = self._client.chat.completions.create(**kwargs)

                choices = response.choices
                if not choices:
                    return LLM_Response(text="", input_tokens=0, output_tokens=0, model=model)

                usage = response.usage
                text = str(choices[0].message.content or "")
                in_tok = int(usage.prompt_tokens) if usage else 0
                out_tok = int(usage.completion_tokens) if usage else 0

                return LLM_Response(
                    text=text,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    model=model,
                )
            except Exception as exc:
                # Check for connection errors specifically
                exc_str = str(exc).lower()
                is_conn_err = (
                    "connection" in exc_str or "refused" in exc_str or "timeout" in exc_str
                )
                if is_conn_err and attempt == 0:
                    raise ConnectionError(
                        f"Cannot reach LM Studio at {self._base_url}. "
                        f"Start LM Studio and enable the local server."
                    ) from exc

                last_error = exc
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

        assert last_error is not None  # nosec B101
        raise last_error
