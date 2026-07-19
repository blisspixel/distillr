# pyright: strict
"""Ollama provider — local inference via the Ollama HTTP API.

Communicates with a local Ollama server at http://localhost:11434.
Override with OLLAMA_BASE_URL environment variable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, cast

import httpx

from distill.llm._parsing import parse_ascii_uint
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.providers._ollama_registry import (
    TagRegistryLimits,
    bounded_context_window,
    parse_tags_response,
)
from distill.llm.retry import is_permanent_error
from distill.llm.types import LLM_Response
from distill.llm.usage import UsageAttemptSink

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

_CONTENTION_INITIAL_BACKOFF_SECONDS = 1.0
_CONTENTION_MAX_BACKOFF_SECONDS = 10.0
_RUNNING_MODELS_REQUEST_TIMEOUT_SECONDS = 5.0
_MAX_CONTEXT_WINDOW = 16_777_216
_MAX_PARAMETERS_CHARS = 100_000
_TAGS_RESPONSE_BYTES = 2 * 1024 * 1024
_TAGS_MAX_MODELS = 1_024
_TAGS_MAX_MODEL_FIELDS = 32
_TAGS_MAX_DETAILS_FIELDS = 32
_TAGS_MAX_LIST_ITEMS = 32
_TAGS_MAX_FIELD_NAME_CHARS = 128
_TAGS_MAX_MODEL_NAME_CHARS = 512
_TAGS_MAX_STRING_CHARS = 4_096
_STRUCTURED_JSON_CALL_TYPES = frozenset(
    {
        "discover_plan",
        "discover_rerank",
        "paper_expand",
        "paper_rerank",
        "search_expand",
        "search_rerank",
    }
)


def _is_thinking_model(model: str) -> bool:
    """Check if a model supports thinking mode."""
    model_lower = model.lower()
    return any(model_lower.startswith(prefix) for prefix in _THINKING_MODEL_PREFIXES)


def _canonical_model_name(model: str) -> str:
    """Normalize an Ollama model reference for running-model comparisons."""
    normalized = model.strip().casefold()
    final_component = normalized.rsplit("/", 1)[-1]
    if ":" not in final_component and "@" not in final_component:
        return f"{normalized}:latest"
    return normalized


def _uses_structured_json(call_type: str) -> bool:
    """Select JSON mode only from trusted first-party workload metadata."""

    return call_type in _STRUCTURED_JSON_CALL_TYPES


def _parse_tags_response(raw: bytes) -> list[dict[str, Any]]:
    return parse_tags_response(
        raw,
        limits=TagRegistryLimits(
            models=_TAGS_MAX_MODELS,
            model_fields=_TAGS_MAX_MODEL_FIELDS,
            details_fields=_TAGS_MAX_DETAILS_FIELDS,
            list_items=_TAGS_MAX_LIST_ITEMS,
            field_name_chars=_TAGS_MAX_FIELD_NAME_CHARS,
            model_name_chars=_TAGS_MAX_MODEL_NAME_CHARS,
            string_chars=_TAGS_MAX_STRING_CHARS,
        ),
    )


def _describe_ollama_error(exc: Exception) -> str:
    """Render an Ollama call error as a diagnosable string.

    ``str(exc)`` is empty for httpx timeout exceptions (e.g. ``ReadTimeout``) and
    hides the server's body for an ``HTTPStatusError``, so a bare ``%s`` in a log
    line can read as an empty message. Always return something actionable: the
    HTTP status and response body when present, else the message, else the type.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text.strip()
        status = exc.response.status_code
        return f"HTTP {status}: {body}" if body else f"HTTP {status}"
    return str(exc).strip() or type(exc).__name__


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
        usage_sink: UsageAttemptSink | None = None,
    ) -> LLM_Response:
        """Send a prompt to Ollama and return an LLM_Response.

        Uses POST /api/chat with thinking enabled. Thinking-capable models
        (Qwen3, DeepSeek R1) produce a reasoning trace that drives quality.
        The final answer (message.content) is returned as the response text.
        Retries on transient errors with exponential backoff (base 2s, factor 2).
        """
        await self._wait_for_model_slot(model, timeout)

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                # Size the context to prompt + output + headroom so a model's huge
                # default window does not allocate a KV cache that spills VRAM.
                num_ctx = await self._adaptive_num_ctx(model, prompt, max_tokens)
                payload = self._build_chat_payload(
                    model,
                    prompt,
                    max_tokens=max_tokens,
                    num_ctx=num_ctx,
                    temperature=temperature,
                    call_type=call_type,
                )
                return await self._stream_chat(model, payload, timeout)
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
                        _describe_ollama_error(exc),
                        wait,
                    )
                    time.sleep(wait)
                else:
                    raise

        assert last_error is not None  # nosec B101
        raise last_error

    async def _wait_for_model_slot(self, model: str, timeout: int) -> None:
        """Wait until Ollama is free or already has the requested model loaded.

        Ollama may unload a running model to satisfy a request for another one,
        which can disrupt an unrelated local workload and make this call appear
        to hang during model loading. Poll ``/api/ps`` with bounded backoff so
        the configured model remains explicit. The call timeout is also the
        maximum contention wait. Older or unavailable ``/api/ps`` endpoints
        preserve the previous behavior and let the normal call proceed.
        """
        wait_limit = max(float(timeout), 0.0)
        deadline = time.monotonic() + wait_limit
        backoff = _CONTENTION_INITIAL_BACKOFF_SECONDS
        first_wait = True
        last_running: tuple[str, ...] | None = None

        while True:
            remaining = deadline - time.monotonic()
            if last_running is not None and remaining <= 0:
                raise ProviderBusyTimeoutError(
                    provider="Ollama",
                    requested_model=model,
                    active_models=last_running,
                    timeout_seconds=wait_limit,
                )

            running = await self._running_model_names(max(remaining, 0.0))
            if (
                running is None
                or not running
                or any(
                    _canonical_model_name(model) == _canonical_model_name(running_model)
                    for running_model in running
                )
            ):
                return

            last_running = running
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderBusyTimeoutError(
                    provider="Ollama",
                    requested_model=model,
                    active_models=running,
                    timeout_seconds=wait_limit,
                )

            active = ", ".join(running)
            sleep_for = min(backoff, remaining)
            if first_wait:
                logger.warning(
                    "Ollama is running %s; waiting up to %gs for requested model '%s'. "
                    "No model will be substituted.",
                    active,
                    wait_limit,
                    model,
                )
                first_wait = False
            logger.info(
                "Ollama is still running %s; checking again in %.1fs (%.1fs remaining)",
                active,
                sleep_for,
                remaining,
            )
            await asyncio.sleep(sleep_for)
            backoff = min(backoff * 2, _CONTENTION_MAX_BACKOFF_SECONDS)

    async def _running_model_names(self, probe_timeout: float) -> tuple[str, ...] | None:
        """Return models reported by ``/api/ps``, or ``None`` when unavailable."""
        request_timeout = max(
            min(_RUNNING_MODELS_REQUEST_TIMEOUT_SECONDS, probe_timeout),
            0.001,
        )
        try:
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                response = await client.get(f"{self._base_url}/api/ps")
                response.raise_for_status()
                data = cast(object, response.json())
            if not isinstance(data, dict):
                raise ValueError("Ollama /api/ps response is not an object")
            data_dict = cast(dict[object, object], data)
            if "models" not in data_dict:
                raise ValueError("Ollama /api/ps response has no model list")
            raw_models = data_dict["models"]
            if not isinstance(raw_models, list):
                raise ValueError("Ollama /api/ps response has no model list")

            names: set[str] = set()
            for raw_model in cast(list[object], raw_models):
                if not isinstance(raw_model, dict):
                    continue
                model_data = cast(dict[object, object], raw_model)
                name: object = None
                if "name" in model_data:
                    name = model_data["name"]
                elif "model" in model_data:
                    name = model_data["model"]
                if isinstance(name, str) and name:
                    names.add(name)
            return tuple(sorted(names))
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            logger.debug(
                "Could not inspect Ollama running models through /api/ps: %s. "
                "Continuing with the normal call path.",
                _describe_ollama_error(exc),
            )
            return None

    @staticmethod
    def _build_chat_payload(
        model: str,
        prompt: str,
        *,
        max_tokens: int,
        num_ctx: int,
        temperature: float | None,
        call_type: str = "",
    ) -> dict[str, Any]:
        """Assemble the /api/chat request body.

        Streams (see :meth:`_stream_chat`) so the read timeout is an idle timeout.
        Trusted structured workloads force ``format=json`` without thinking
        because thinking conflicts with the JSON constraint on most models.
        Prompt text never controls transport options.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "options": {"num_predict": max_tokens, "num_ctx": num_ctx},
        }
        if _uses_structured_json(call_type):
            payload["format"] = "json"
            payload["think"] = False
        elif _is_thinking_model(model):
            payload["think"] = True
        if temperature is not None:
            payload["options"]["temperature"] = temperature
        return payload

    async def _stream_chat(self, model: str, payload: dict[str, Any], timeout: int) -> LLM_Response:
        """POST /api/chat and assemble the streamed NDJSON frames into a response.

        ``timeout`` is the per-read (idle) timeout, not a total-time cap: a
        long-but-progressing generation streams to completion, while a genuinely
        stalled call fails after one idle window. The terminal (done) frame
        carries cumulative token counts; ``content`` is the answer and
        ``thinking`` the reasoning trace, used only when content is empty.
        """
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client,
            client.stream("POST", f"{self._base_url}/api/chat", json=payload) as response,
        ):
            if response.status_code >= 400:
                # Load the body so the raised error carries Ollama's message
                # (e.g. an out-of-memory explanation) rather than an empty stream.
                await response.aread()
                response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                frame = json.loads(line)
                frame_message = frame.get("message", {})
                if frame_message.get("content"):
                    content_parts.append(frame_message["content"])
                if frame_message.get("thinking"):
                    thinking_parts.append(frame_message["thinking"])
                if frame.get("done"):
                    input_tokens = frame.get("prompt_eval_count", 0) or 0
                    output_tokens = frame.get("eval_count", 0) or 0
        content = "".join(content_parts)
        thinking = "".join(thinking_parts)
        return LLM_Response(
            text=content if content else thinking,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )

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
        return parse_ascii_uint(raw) or 0

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
    def _parse_context_window(data: object) -> int:
        """Extract context window from Ollama /api/show response data."""
        if not isinstance(data, dict):
            return 0
        payload = cast(dict[object, object], data)
        raw_model_info = payload.get("model_info")
        model_info = (
            cast(dict[object, object], raw_model_info) if isinstance(raw_model_info, dict) else {}
        )

        # Try model_info first (more reliable)
        for key, value in model_info.items():
            if isinstance(key, str) and "context_length" in key.casefold():
                context_window = bounded_context_window(value, maximum=_MAX_CONTEXT_WINDOW)
                if context_window:
                    return context_window

        # Fallback: parse from parameters string
        params = payload.get("parameters")
        if isinstance(params, str) and len(params) <= _MAX_PARAMETERS_CHARS:
            for line in params.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "num_ctx":
                    return bounded_context_window(parts[-1], maximum=_MAX_CONTEXT_WINDOW) or 0

        return 0

    async def list_models(self) -> list[dict[str, Any]]:
        """Query Ollama /api/tags for locally available models."""
        try:
            raw = bytearray()
            async with (
                httpx.AsyncClient(timeout=5) as client,
                client.stream("GET", f"{self._base_url}/api/tags") as response,
            ):
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > _TAGS_RESPONSE_BYTES:
                        raise ValueError("Ollama model registry exceeds its response byte limit")
                    raw.extend(chunk)
            return _parse_tags_response(bytes(raw))
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._base_url}. Run `ollama serve` to start the server."
            ) from exc
