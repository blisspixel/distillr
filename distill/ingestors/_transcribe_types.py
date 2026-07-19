"""Shared types for parent and child transcription boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str
    language: str = ""
    duration_s: float = 0.0
    notes: list[str] = field(default_factory=list)


ProgressCallback = Callable[[float, float, int], None]


class LocalTranscriptionUnavailable(RuntimeError):
    """The local transcription route cannot safely complete the request."""
