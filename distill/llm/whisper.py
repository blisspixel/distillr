"""OpenAI Whisper audio-transcription client.

Lives under ``distill/llm/`` because the architectural test
``test_no_openai_construction_outside_llm`` enforces that direct
``OpenAI()`` construction stays in the LLM layer. Whisper is a
different OpenAI API surface than chat completions, but the same
client-construction discipline applies.

The ingestion layer (``distill/ingestors/transcribe.py``) imports and
calls :func:`transcribe_with_openai`; it does not construct the client
itself.
"""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI

__all__ = ["transcribe_with_openai"]


_OPENAI_WHISPER_MAX_BYTES = 25 * 1024 * 1024  # 25 MB upload cap per OpenAI's docs


def transcribe_with_openai(
    media_path: Path,
    api_key: str,
    *,
    model: str = "whisper-1",
    vocabulary_hint: str = "",
) -> str:
    """Transcribe *media_path* via the OpenAI Whisper API.

    ``vocabulary_hint`` becomes the ``prompt`` parameter, which biases
    Whisper toward the supplied proper nouns. Caller is responsible for
    clipping the hint to Whisper's ~224-token budget.

    Raises :class:`ValueError` if *media_path* exceeds OpenAI's
    documented 25 MB upload cap, surfacing the limit upfront instead of
    waiting for the API's HTTP 413. Callers that need to handle longer
    audio should chunk the file or use ``distill.llm.grok_stt`` instead
    (Grok STT supports up to 500 MB per call).
    """
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    size_bytes = media_path.stat().st_size
    if size_bytes > _OPENAI_WHISPER_MAX_BYTES:
        raise ValueError(
            f"OpenAI Whisper-1 rejects files larger than 25 MB; "
            f"{media_path.name} is {size_bytes / 1_000_000:.1f} MB. "
            "Use Grok STT (500 MB cap) or local faster-whisper instead."
        )

    client = OpenAI(api_key=api_key)
    kwargs: dict[str, str] = {
        "model": model,
        "response_format": "text",
    }
    if vocabulary_hint:
        kwargs["prompt"] = vocabulary_hint
    with media_path.open("rb") as fh:
        result = client.audio.transcriptions.create(file=fh, **kwargs)  # type: ignore[arg-type]
    if isinstance(result, str):
        return result
    return str(getattr(result, "text", "") or result)
