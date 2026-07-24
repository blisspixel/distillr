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
from dataclasses import replace
from time import monotonic as _monotonic
from typing import Any

import httpx

from distill.llm._parsing import parse_ascii_uint
from distill.llm.cost_policy import classify_provider, local_provider_endpoint_is_valid
from distill.llm.errors import ProviderBusyTimeoutError

# Re-exported for callers/tests that import it from this module; the redundant
# alias marks the intentional re-export (the transport code does not use it).
from distill.llm.providers._ollama_metadata import (
    _STRUCTURED_JSON_CALL_TYPES as _STRUCTURED_JSON_CALL_TYPES,  # pyright: ignore[reportPrivateUsage]  -- compatibility re-export
)
from distill.llm.providers._ollama_metadata import (  # pyright: ignore[reportPrivateUsage]  -- private helpers shared with the transport module
    _canonical_model_name,
    _describe_ollama_error,
    build_chat_payload,
    parse_context_window,
)
from distill.llm.providers._ollama_registry import (
    TagRegistryLimits,
    parse_running_model_names,
    parse_tags_response,
)
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

OLLAMA_DEFAULT_URL = "http://localhost:11434"

_CONTENTION_INITIAL_BACKOFF_SECONDS = 1.0
_CONTENTION_MAX_BACKOFF_SECONDS = 10.0
_RUNNING_MODELS_REQUEST_TIMEOUT_SECONDS = 5.0
_RUNNING_MODELS_RESPONSE_BYTES = 1024 * 1024
_RUNNING_MODELS_MAX_MODELS = 256
_TAGS_RESPONSE_BYTES = 2 * 1024 * 1024
_TAGS_MAX_MODELS = 1_024
_TAGS_MAX_MODEL_FIELDS = 32
_TAGS_MAX_DETAILS_FIELDS = 32
_TAGS_MAX_LIST_ITEMS = 32
_TAGS_MAX_FIELD_NAME_CHARS = 128
_TAGS_MAX_MODEL_NAME_CHARS = 512
_TAGS_TOTAL_SECONDS = 10.0
_TAGS_MAX_STRING_CHARS = 4_096


def _tag_limits(models: int) -> TagRegistryLimits:
    # Read the module-level bounds per call (not at import) so a test can tune a
    # single limit via monkeypatch.setattr and have it affect the parse path.
    return TagRegistryLimits(
        models=models,
        model_fields=_TAGS_MAX_MODEL_FIELDS,
        details_fields=_TAGS_MAX_DETAILS_FIELDS,
        list_items=_TAGS_MAX_LIST_ITEMS,
        field_name_chars=_TAGS_MAX_FIELD_NAME_CHARS,
        model_name_chars=_TAGS_MAX_MODEL_NAME_CHARS,
        string_chars=_TAGS_MAX_STRING_CHARS,
    )


def _parse_tags_response(raw: bytes) -> list[dict[str, Any]]:
    return parse_tags_response(raw, limits=_tag_limits(_TAGS_MAX_MODELS))


def _parse_running_models_response(raw: bytes) -> tuple[str, ...]:
    return parse_running_model_names(raw, limits=_tag_limits(_RUNNING_MODELS_MAX_MODELS))


class OllamaProvider:
    """Ollama local inference provider."""

    def __init__(self, base_url: str = "") -> None:
        url = base_url or os.environ.get("OLLAMA_BASE_URL", OLLAMA_DEFAULT_URL)
        if not local_provider_endpoint_is_valid(url):
            raise ValueError(
                "Ollama requires a valid HTTP(S) endpoint without credentials, "
                "query parameters, or fragments."
            )
        self._base_url = url
        self._provider_type = (
            "local" if classify_provider("ollama", endpoint=url) == "local" else "unknown"
        )
        self._trust_env = self._provider_type != "local"
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
        usage_attempts: list[LLMUsageAttempt] = []
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
                response = await self._stream_chat(model, payload, timeout)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                surfaced = ConnectionError(
                    f"Cannot reach Ollama at {self._base_url}. "
                    f"Run `ollama serve` to start the server."
                )
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
                        provider_name="ollama",
                        provider_type=self._provider_type,
                        usage_source="conservative",
                        outcome="error",
                        error_type=type(exc).__name__,
                    ),
                    usage_sink,
                )
                attach_usage_attempts(surfaced, usage_attempts)
                raise surfaced from exc
            except (httpx.HTTPStatusError, httpx.TimeoutException) as exc:
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
                        provider_name="ollama",
                        provider_type=self._provider_type,
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
            else:
                emit_usage_attempt(
                    usage_attempts,
                    LLMUsageAttempt(
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        model=response.model or model,
                        provider_name="ollama",
                        provider_type=self._provider_type,
                        usage_source=response.usage_source,
                        outcome="success",
                    ),
                    usage_sink,
                )
                return replace(response, usage_attempts=tuple(usage_attempts))

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
            raw = bytearray()
            started = _monotonic()
            async with (
                httpx.AsyncClient(
                    timeout=request_timeout,
                    trust_env=self._trust_env,
                ) as client,
                client.stream("GET", f"{self._base_url}/api/ps") as response,
            ):
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if _monotonic() - started > request_timeout:
                        raise TimeoutError("Ollama running-model probe exceeded its total deadline")
                    if len(raw) + len(chunk) > _RUNNING_MODELS_RESPONSE_BYTES:
                        raise ValueError(
                            "Ollama running-model response exceeds its response byte limit"
                        )
                    raw.extend(chunk)
            return _parse_running_models_response(bytes(raw))
        except (httpx.HTTPError, TimeoutError, TypeError, ValueError) as exc:
            logger.debug(
                "Could not inspect Ollama running models through /api/ps: %s. "
                "Continuing with the normal call path.",
                _describe_ollama_error(exc),
            )
            return None

    # Bound from ``_ollama_metadata`` so these stay callable as class methods.
    _build_chat_payload = staticmethod(build_chat_payload)

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
            httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=10.0),
                trust_env=self._trust_env,
            ) as client,
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
            async with httpx.AsyncClient(timeout=5, trust_env=self._trust_env) as client:
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

    _parse_context_window = staticmethod(parse_context_window)

    async def list_models(self) -> list[dict[str, Any]]:
        """Query Ollama /api/tags for locally available models."""
        try:
            raw = bytearray()
            started = _monotonic()
            async with (
                httpx.AsyncClient(timeout=5, trust_env=self._trust_env) as client,
                client.stream("GET", f"{self._base_url}/api/tags") as response,
            ):
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if _monotonic() - started > _TAGS_TOTAL_SECONDS:
                        raise TimeoutError("Ollama model registry exceeded its total deadline")
                    if len(raw) + len(chunk) > _TAGS_RESPONSE_BYTES:
                        raise ValueError("Ollama model registry exceeds its response byte limit")
                    raw.extend(chunk)
            return _parse_tags_response(bytes(raw))
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ConnectionError(
                f"Cannot reach Ollama at {self._base_url}. Run `ollama serve` to start the server."
            ) from exc
