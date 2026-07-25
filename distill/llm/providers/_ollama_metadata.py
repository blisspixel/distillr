# pyright: strict
"""Pure metadata helpers for the Ollama provider.

Model classification, name normalization, request-payload assembly, error
rendering, and context-window extraction from an ``/api/show`` response. These
are pure functions with no transport or provider state, separated from
``ollama.py`` so that module stays within its size budget and these helpers
stay independently testable. ``ollama`` re-imports every name it needs from
here, so the provider's public surface is unchanged.
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx

from distill.llm.providers._ollama_registry import bounded_context_window

# Names re-imported by ``ollama.py`` (and, through it, its tests). Listing them
# marks the underscore-prefixed helpers as exported so pyright does not flag them
# as unused within this module.
__all__ = [
    "_STRUCTURED_JSON_CALL_TYPES",
    "_canonical_model_name",
    "_describe_ollama_error",
    "_is_thinking_model",
    "_uses_structured_json",
    "build_chat_payload",
    "is_terminal_show_status",
    "parse_chat_frame",
    "parse_context_window",
]

# Models that support thinking mode (reasoning trace)
_THINKING_MODEL_PREFIXES: tuple[str, ...] = (
    "qwen3",
    "deepseek-r1",
    "deepseek-v3",
    "gpt-oss",
    "gemma4",
)

_MAX_CONTEXT_WINDOW = 16_777_216
_MAX_PARAMETERS_CHARS = 100_000
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


def build_chat_payload(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    num_ctx: int,
    temperature: float | None,
    call_type: str = "",
) -> dict[str, Any]:
    """Assemble the /api/chat request body.

    Streams (see ``OllamaProvider._stream_chat``) so the read timeout is an idle
    timeout. Trusted structured workloads force ``format=json`` without thinking
    because thinking conflicts with the JSON constraint on most models. Prompt
    text never controls transport options.
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


def parse_context_window(data: object) -> int:
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


def parse_chat_frame(line: str) -> tuple[dict[str, Any], str, str] | None:
    """Parse one NDJSON chat frame into ``(frame, content, thinking)``.

    Frames are provider-controlled input. ``json.loads`` followed by
    ``frame.get(...)`` raised ``JSONDecodeError``/``AttributeError`` straight out
    of the provider, bypassing the retry loop, the conservative-usage accounting,
    and the Ollama error diagnostics. Return ``None`` for anything unreadable so
    the caller can skip it, matching the bounded ``/api/tags`` and ``/api/ps``
    parsers.
    """
    try:
        frame = json.loads(line)
    except ValueError:
        return None
    if not isinstance(frame, dict):
        return None
    frame = cast("dict[str, Any]", frame)
    message = frame.get("message")
    message = cast("dict[str, Any]", message) if isinstance(message, dict) else {}
    content = message.get("content")
    thinking = message.get("thinking")
    return (
        frame,
        content if isinstance(content, str) else "",
        thinking if isinstance(thinking, str) else "",
    )


# ``/api/show`` statuses that describe the model itself rather than a passing
# server condition. Only these justify caching the degraded default window; a 5xx
# or 429 is retryable and must not pin the window for the process lifetime.
_TERMINAL_SHOW_STATUSES = frozenset({400, 401, 403, 404, 410, 422})


def is_terminal_show_status(status: int) -> bool:
    """Whether an ``/api/show`` status describes the model, not a transient fault."""
    return status in _TERMINAL_SHOW_STATUSES
