"""Structural transcript health checks for audit reports."""

# pyright: strict

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from distill.library.paths import find_artifact

__all__ = [
    "LONG_VIDEO_SECONDS",
    "MIN_TRANSCRIPT_CHARS",
    "ThinTranscript",
    "collect_thin_video_transcripts",
    "format_duration",
    "render_thin_video_transcripts_section",
]

LONG_VIDEO_SECONDS = 1800
MIN_TRANSCRIPT_CHARS = 500


@dataclass(frozen=True)
class ThinTranscript:
    """A long video whose transcript receipt is suspiciously short."""

    path: str
    channel: str
    title: str
    duration_seconds: int
    transcript_chars: int


def collect_thin_video_transcripts(topic_dir: Path) -> list[ThinTranscript]:
    """Find long-video transcript receipts that look like capture failures."""
    channels_dir = topic_dir / "channels"
    if not channels_dir.is_dir():
        return []

    warnings: list[ThinTranscript] = []
    for channel_dir in sorted(channels_dir.iterdir(), key=lambda path: path.name.lower()):
        videos_dir = channel_dir / "videos"
        if not videos_dir.is_dir():
            continue
        for video_dir in sorted(videos_dir.iterdir(), key=lambda path: path.name.lower()):
            if not video_dir.is_dir():
                continue
            metadata = _read_json_dict(video_dir / "metadata.json")
            duration = _duration_seconds(metadata.get("duration"))
            if duration < LONG_VIDEO_SECONDS:
                continue
            transcript_path = find_artifact(video_dir, "transcript", extension="txt")
            if not transcript_path.exists():
                continue
            transcript_chars = _transcript_chars(transcript_path)
            if transcript_chars >= MIN_TRANSCRIPT_CHARS:
                continue
            warnings.append(
                ThinTranscript(
                    path=video_dir.relative_to(topic_dir).as_posix(),
                    channel=channel_dir.name,
                    title=str(metadata.get("title") or video_dir.name),
                    duration_seconds=duration,
                    transcript_chars=transcript_chars,
                )
            )
    return warnings


def render_thin_video_transcripts_section(items: list[ThinTranscript]) -> list[str]:
    lines = ["## Thin video transcripts", ""]
    if not items:
        return [*lines, "- No suspiciously thin long-video transcripts found."]
    lines.append(
        f"Long videos should usually have at least {MIN_TRANSCRIPT_CHARS} transcript characters. "
        "These are advisory capture-failure warnings, not content-quality scores."
    )
    lines.append("")
    for item in items:
        lines.append(
            f"- `{item.path}` - {item.title} ({item.channel}): "
            f"{item.transcript_chars} chars for {format_duration(item.duration_seconds)}"
        )
    return lines


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "?"
    total = int(seconds)
    if total < 0:
        return "?"
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


def _duration_seconds(value: object) -> int:
    try:
        duration = int(float(str(value)))
    except (TypeError, ValueError):
        return 0
    return max(duration, 0)


def _transcript_chars(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").strip())
    except OSError:
        return 0
