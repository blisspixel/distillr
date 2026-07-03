# pyright: strict
"""Ollama provider — local inference via the Ollama HTTP API.

Communicates with a local Ollama server at http://localhost:11434.
Override with OLLAMA_BASE_URL environment variable.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from distill.llm.retry import is_permanent_error
from distill.llm.router import LLM_Response

logger = logging.getLogger(__name__)

OLLAMA_DEFAULT_URL = "http://localhost:11434"

# Models that support thinking mode (reasoning trace)
_THINKING_MODEL_PREFIXES: tuple[str, ...] = (
    "qwen3",
    "deepseek-r1",
    "deepseek-v3",
    "gpt-oss",
    "gemma4",
)


def _is_thinking_model(model: str) -> bool:
    """Check if a model supports thinking mode."""
    model_lower = model.lower()
    return any(model_lower.startswith(prefix) for prefix in _THINKING_MODEL_PREFIXES)


def _wants_json_output(prompt: str) -> bool:
    """Detect if a prompt explicitly requests JSON output.

    Looks for common patterns in distillr prompts that indicate
    structured JSON is expected. When detected, we set format="json"
    in the Ollama request to constrain output.
    """
    lower = prompt.lower()
    return (
        "return only valid json" in lower
        or "return only json" in lower
        or "respond with json" in lower
        or '"ranked_videos"' in lower
        or '"ranked_papers"' in lower
        or '"ranked_items"' in lower
        or '"paper_queries"' in lower
        or '"queries"' in lower
    )


class OllamaProvider:
    """Ollama local inference provider."""

    def __init__(self, base_url: str = "") -> None:
        self._base_url = base_url or os.environ.get("OLLAMA_BASE_URL", OLLAMA_DEFAULT_URL)
        self._context_window_cache: dict[str, int] = {}

    async def call(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int = 8192,
        timeout: int = 600,
        retries: int = 2,
        temperature: float | None = None,
        call_type: str = "",
        reasoning_effort: str | None = None,  # Ignored for local models
    ) -> LLM_Response:
        """Send a prompt to Ollama and return an LLM_Response.

        Uses POST /api/chat with thinking enabled. Thinking-capable models
        (Qwen3, DeepSeek R1) produce a reasoning trace that drives quality.
        The final answer (message.content) is returned as the response text.
        Retries on transient errors with exponential backoff (base 2s, factor 2).
        """
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                # Size the context window to the actual need. A model's default
                # context can be enormous (e.g. 262144); Ollama would then allocate
                # a KV cache to match and spill VRAM to CPU — turning a 24GB GPU
                # run into a slow, error-prone CPU one even for a tiny prompt. We
                # request only prompt + output + headroom, capped at the model's max.
                num_ctx = await self._adaptive_num_ctx(model, prompt, max_tokens)
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"num_predict": max_tokens, "num_ctx": num_ctx},
                }
                # For JSON-structured prompts: use format="json" without thinking
                # (thinking conflicts with JSON format constraint in most models)
                # For analysis prompts: use thinking for deep reasoning
                wants_json = _wants_json_output(prompt)
                if wants_json:
                    payload["format"] = "json"
                    payload["think"] = False  # Explicitly disable thinking for JSON
                elif _is_thinking_model(model):
                    payload["think"] = True
                if temperature is not None:
                    payload["options"]["temperature"] = temperature

                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(timeout, connect=10.0)
                ) as client:
                    response = await client.post(
                        f"{self._base_url}/api/chat",
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                # /api/chat returns message.content (final answer) and
                # message.thinking (reasoning trace)
                message = data.get("message", {})
                content = message.get("content", "")
                thinking = message.get("thinking", "")

                # Use the final answer; fall back to thinking if content is empty
                text = content if content else thinking

                # Token counts from top-level response fields
                input_tokens = data.get("prompt_eval_count", 0) or 0
                output_tokens = data.get("eval_count", 0) or 0

                return LLM_Response(
                    text=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=model,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise ConnectionError(
                    f"Cannot reach Ollama at {self._base_url}. "
                    f"Run `ollama serve` to start the server."
                ) from exc
            except (httpx.HTTPStatusError, httpx.TimeoutException) as exc:
                last_error = exc
                if is_permanent_error(exc):
                    raise
                if attempt < retries:
                    wait = 2**attempt * 2
                    logger.warning(
                        "Ollama error (attempt %d/%d): %s. Retrying in %ds...",
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

    _MIN_NUM_CTX: int = 4096

    @staticmethod
    def _num_ctx_ceiling() -> int:
        """Operator ceiling on ``num_ctx`` from ``OLLAMA_MAX_NUM_CTX`` (0 = off).

        ``_adaptive_num_ctx`` already caps at the model's advertised window, but
        that window can be enormous (262144) and the request scales with prompt
        length -- which includes attacker-influenced ingested text (a 120K-char
        scraped page is ~40K tokens). On a fixed-VRAM box a large prompt can size
        the KV cache past available memory. This env knob lets an operator bound
        num_ctx to a VRAM-safe value; unset (the default) preserves the
        send-it-whole behavior so quality is never silently degraded.
        """
        raw = os.environ.get("OLLAMA_MAX_NUM_CTX", "").strip()
        return int(raw) if raw.isdigit() else 0

    async def _adaptive_num_ctx(self, model: str, prompt: str, max_tokens: int) -> int:
        """Context size for this call: prompt + output + headroom, capped at model max.

        Prevents a model's huge default context from allocating a KV cache that
        exceeds VRAM. Estimates prompt tokens at ~4 chars/token with 30% headroom.
        """
        needed = int(len(prompt) / 4 * 1.3) + max_tokens + 512
        try:
            model_max = await self.get_context_window(model)
        except (ConnectionError, OSError):
            model_max = 0
        if model_max:
            needed = min(needed, model_max)
        ceiling = self._num_ctx_ceiling()
        if ceiling:
            # Never drop below the floor even if the operator sets a tiny ceiling.
            needed = min(needed, max(ceiling, self._MIN_NUM_CTX))
        return max(self._MIN_NUM_CTX, needed)

    async def get_context_window(self, model: str) -> int:
        """Query Ollama /api/show for the model's context window. Cached per model."""
        if model in self._context_window_cache:
            return self._context_window_cache[model]

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    f"{self._base_url}/api/show",
                    json={"name": model},
                )
                response.raise_for_status()
                data = response.json()

            ctx = self._parse_context_window(data)

            # Default fallback
            if not ctx:
                ctx = 4096
                logger.warning(
                    "Could not determine context window for '%s'; defaulting to %d",
                    model,
                    ctx,
                )

            self._context_window_cache[model] = ctx
            return ctx
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._base_url}. Run `ollama serve` to start the server."
            ) from exc
        except httpx.HTTPStatusError as exc:
            # Ollama is reachable but /api/show returned an error status for this
            # model (an unpulled model 404s). Degrade to the default context
            # window rather than failing the run. Connection and timeout errors
            # are deliberately not caught here, so retry/backoff behavior and the
            # "start Ollama" hint above are unchanged.
            logger.warning(
                "Ollama /api/show returned %s for '%s'; defaulting context window to 4096",
                exc.response.status_code,
                model,
            )
            self._context_window_cache[model] = 4096
            return 4096

    @staticmethod
    def _parse_context_window(data: dict[str, Any]) -> int:
        """Extract context window from Ollama /api/show response data."""
        model_info = data.get("model_info", {})

        # Try model_info first (more reliable)
        for key, value in model_info.items():
            if "context_length" in key.lower():
                return int(value)

        # Fallback: parse from parameters string
        params = data.get("parameters", "")
        if "num_ctx" in params:
            for line in params.split("\n"):
                if "num_ctx" in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        import contextlib

                        with contextlib.suppress(ValueError):
                            return int(parts[-1])
                    break

        return 0

    async def list_models(self) -> list[dict[str, Any]]:
        """Query Ollama /api/tags for locally available models."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self._base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
            return data.get("models", [])
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._base_url}. Run `ollama serve` to start the server."
            ) from exc
