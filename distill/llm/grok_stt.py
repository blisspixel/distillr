"""xAI Grok Speech-to-Text client.

Lives under ``distill/llm/`` because the architectural test
``test_no_openai_construction_outside_llm`` keeps API client construction
contained in the LLM layer. Grok STT is a separate API surface from
xAI's chat completions but the same containment discipline applies.

API reference: https://docs.x.ai/developers/model-capabilities/audio/speech-to-text

Endpoint: ``POST https://api.x.ai/v1/stt`` (multipart/form-data)
Pricing: $0.10/hour batch (~3.6x cheaper than OpenAI Whisper-1)
Supports up to 500 MB audio files and a ``keyterm`` parameter that
biases transcription toward supplied proper nouns (analogous to
Whisper's ``initial_prompt``, but with a different shape: keyterm
expects a list of short individual terms, not a free-form initial
prompt sentence).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

__all__ = ["STT_ENDPOINT", "keyterms_from_hint", "transcribe_with_grok"]

STT_ENDPOINT = "https://api.x.ai/v1/stt"


def keyterms_from_hint(hint: str, *, max_terms: int = 60, max_term_chars: int = 50) -> str:
    """Comma-joined string form of :func:`_keyterm_list` (kept for tests
    and external callers that prefer a flat string preview)."""
    return ", ".join(_keyterm_list(hint, max_terms=max_terms, max_term_chars=max_term_chars))


def _keyterm_list(hint: str, *, max_terms: int = 60, max_term_chars: int = 50) -> list[str]:
    """Extract a Grok-STT-compatible list of short individual keyterms.

    Whisper's ``initial_prompt`` accepts free-form text (often a full
    tweet body + LLM-expanded proper nouns). Grok STT's ``keyterm``
    rejects sentences and expects one short term per repeated form
    field, not a delimited string.

    Strategy: split on common delimiters (comma, em-dash, newline,
    semicolon, pipe), trim, drop empty entries and anything that looks
    like a sentence (long, has many spaces, URL-like fragment). Cap at
    *max_terms* terms and *max_term_chars* per term.
    """
    if not hint:
        return []
    parts = re.split(r"[,—\n;|]", hint)
    out: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        term = raw.strip().strip(".!?\"'`()[]")
        if not term:
            continue
        if len(term) > max_term_chars:
            continue
        if "http" in term or "://" in term:
            continue
        if term.count(" ") > 6:  # > 7 words ~ likely a sentence
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= max_terms:
            break
    return out


_FORMAT_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
}


def transcribe_with_grok(
    media_path: Path,
    api_key: str,
    *,
    vocabulary_hint: str = "",
    language: str = "",
    timeout: float = 600.0,
) -> str:
    """Transcribe *media_path* via the xAI Grok STT batch endpoint.

    ``vocabulary_hint`` becomes the ``keyterm`` form field, which biases
    Grok STT toward the supplied terms — analogous to Whisper's
    ``initial_prompt``. Caller is responsible for clipping the hint to
    a reasonable size (Grok STT does not document a hard cap; we pass
    it as-is and let the API reject if oversized).

    ``language`` (e.g. ``"en"``, ``"fr"``) lets the caller skip
    auto-detect when the source language is known. Empty string lets
    Grok auto-detect.
    """
    if not api_key:
        raise RuntimeError("XAI_API_KEY not configured")
    if not media_path.exists():
        raise FileNotFoundError(f"Media file not found: {media_path}")

    content_type = _FORMAT_BY_EXT.get(media_path.suffix.lower(), "application/octet-stream")
    # ``format=true`` enables punctuation + casing + paragraph breaks. Grok
    # STT rejects that flag unless ``language`` is also set. When caller
    # doesn't know the language, omit both so the API auto-detects.
    #
    # ``keyterm`` is a repeated multipart form field: each list entry
    # becomes a separate ``keyterm`` part on the wire. httpx serializes
    # ``{"keyterm": [...]}`` as the correct repeated form structure.
    data: dict[str, Any] = {}
    if language:
        data["language"] = language
        data["format"] = "true"
    if vocabulary_hint:
        terms = _keyterm_list(vocabulary_hint)
        if terms:
            data["keyterm"] = terms

    with media_path.open("rb") as fh:
        files = {"file": (media_path.name, fh, content_type)}
        resp = httpx.post(
            STT_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            data=data,
            timeout=timeout,
        )
    if resp.status_code >= 400:
        # Surface the response body so callers can see WHY the request was
        # rejected (missing field, wrong model, oversized file, etc.).
        # httpx's default raise_for_status() drops the body entirely.
        body_preview = resp.text[:500] if resp.text else "(empty body)"
        raise RuntimeError(f"Grok STT {resp.status_code} {resp.reason_phrase}: {body_preview}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected Grok STT payload shape: {type(payload).__name__}")
    text = payload.get("text")
    if not isinstance(text, str):
        raise RuntimeError(f"Grok STT response missing 'text' field: {payload!r}")
    return text
