# pyright: strict
"""Persistence and verification evidence helpers for fetched videos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from distill.commands._formatting import format_date

if TYPE_CHECKING:
    from distill.ingestors.youtube.discovery import VideoInfo


def video_metadata(
    video: VideoInfo,
    channel_name: str,
    *,
    analysis_mode: str,
) -> dict[str, object]:
    """Return the deterministic fetched metadata persisted for one video."""
    try:
        resolved_channel = video.channel_name
    except AttributeError:
        resolved_channel = channel_name
    return {
        "video_id": video.video_id,
        "title": video.title,
        "upload_date": video.upload_date,
        "duration": video.duration,
        "url": video.url,
        "channel": resolved_channel or channel_name or "",
        "analysis_mode": analysis_mode,
    }


def video_verification_evidence(
    video: VideoInfo,
    channel_name: str,
    transcript: str,
    *,
    analysis_mode: str,
) -> str:
    """Render the fetched metadata and transcript used to verify an insight."""
    metadata = video_metadata(video, channel_name, analysis_mode=analysis_mode)
    metadata["upload_date_display"] = format_date(video.upload_date)
    return (
        "Fetched video metadata (metadata.json, with normalized upload date):\n"
        f"{json.dumps(metadata, ensure_ascii=False, sort_keys=True)}\n\n"
        "Video transcript:\n"
        f"{transcript}"
    )


def write_video_metadata(
    vid_dir: Path,
    video: VideoInfo,
    channel_name: str = "",
    analysis_mode: str = "full",
) -> None:
    metadata = video_metadata(video, channel_name, analysis_mode=analysis_mode)
    (vid_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
