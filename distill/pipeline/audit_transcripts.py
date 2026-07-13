"""Structural transcript health checks for audit reports."""

# pyright: strict

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from distill.library.paths import find_artifact
from distill.parsing import read_bounded_json_object

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
_MAX_VIDEO_METADATA_BYTES = 1024 * 1024


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
    if seconds is None or isinstance(seconds, bool):
        return "?"
    try:
        normalized = float(seconds)
    except (OverflowError, TypeError, ValueError):
        return "?"
    if not math.isfinite(normalized):
        return "?"
    total = int(normalized)
    if total < 0:
        return "?"
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _read_json_dict(path: Path) -> dict[str, object]:
    return read_bounded_json_object(path, max_bytes=_MAX_VIDEO_METADATA_BYTES)


def _duration_seconds(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        duration = int(float(str(value)))
    except (OverflowError, TypeError, ValueError):
        return 0
    return max(duration, 0)


def _transcript_chars(path: Path) -> int:
    """Return an exact thin-file count without loading large transcripts.

    Once a file has more than the warning threshold of decoded characters, an
    exact total is unnecessary. If the bounded prefix is mostly whitespace and
    more content exists, return the threshold conservatively rather than issue
    a potentially false warning about a file we intentionally did not scan.
    """

    try:
        with path.open("r", encoding="utf-8") as stream:
            prefix = stream.read(MIN_TRANSCRIPT_CHARS + 1)
            has_more = bool(stream.read(1))
    except (OSError, UnicodeError):
        return 0
    if has_more:
        return max(len(prefix.strip()), MIN_TRANSCRIPT_CHARS)
    return len(prefix.strip())
