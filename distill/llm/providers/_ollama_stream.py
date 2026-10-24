# pyright: strict
"""Stream one Ollama chat response and report whether a thinking trace arrived."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from distill.llm.providers._ollama_metadata import frame_seconds, parse_chat_frame
from distill.llm.providers._ollama_show import require_no_remote_metadata
from distill.llm.types import LLM_Response

logger = logging.getLogger(__name__)


async def stream_chat(
    *,
    base_url: str,
    trust_env: bool,
    model: str,
    payload: dict[str, Any],
    timeout: int,
) -> tuple[LLM_Response, bool]:
    """POST /api/chat and assemble the streamed NDJSON frames into a response.

    ``timeout`` is the per-read (idle) timeout, not a total-time cap: a
    long-but-progressing generation streams to completion, while a genuinely
    stalled call fails after one idle window. The terminal (done) frame
    carries cumulative token counts. ``content`` is the answer and
    ``thinking`` is the reasoning trace, used only when content is empty.
    The trace itself is not returned. The boolean says whether one arrived.
    """
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    finish_reason = "incomplete"
    input_tokens = 0
    output_tokens = 0
    load_seconds = 0.0
    prefill_seconds = 0.0
    decode_seconds = 0.0
    async with (
        httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            trust_env=trust_env,
        ) as client,
        client.stream("POST", f"{base_url}/api/chat", json=payload) as response,
    ):
        if response.status_code >= 400:
            # Load the body so the raised error carries Ollama's message
            # (e.g. an out-of-memory explanation) rather than an empty stream.
            await response.aread()
            response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            # Provider-controlled input: skip frames we cannot read rather
            # than raising past the retry loop and usage accounting.
            parsed_frame = parse_chat_frame(line)
            if parsed_frame is None:
                logger.debug("Skipping malformed Ollama chat frame")
                continue
            frame, content_value, thinking_value = parsed_frame
            require_no_remote_metadata(frame)
            if content_value:
                content_parts.append(content_value)
            if thinking_value:
                thinking_parts.append(thinking_value)
            if frame.get("done"):
                finish_reason = str(frame.get("done_reason") or "stop")
                input_tokens = frame.get("prompt_eval_count", 0) or 0
                output_tokens = frame.get("eval_count", 0) or 0
                # Ollama reports each phase separately, in nanoseconds. They
                # are the only honest basis for a rate: wall-clock elapsed
                # includes a model load that can be 40s on a 17GB model.
                load_seconds = frame_seconds(frame, "load_duration")
                prefill_seconds = frame_seconds(frame, "prompt_eval_duration")
                decode_seconds = frame_seconds(frame, "eval_duration")
    content = "".join(content_parts)
    thinking = "".join(thinking_parts)
    return (
        LLM_Response(
            text=content if content else thinking,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            load_seconds=load_seconds,
            finish_reason=finish_reason,
            prefill_seconds=prefill_seconds,
            decode_seconds=decode_seconds,
        ),
        bool(thinking),
    )
