# pyright: strict
"""Filesystem-backed inventory helpers for the doctor command."""

from __future__ import annotations

import json
from typing import cast

from distill.config import DistillConfig
from distill.library import Library
from distill.library.state import ChannelState

__all__ = ["corpus_library_stats"]


def corpus_library_stats(
    config: DistillConfig,
    lib: Library,
) -> tuple[list[str], int, int, int]:
    """Count readable corpus topics, channels, videos, and scan artifacts."""
    topics = lib.get_corpus_topics()
    total_channels = 0
    total_videos = 0
    scan_videos = 0
    for topic in topics:
        channel_names = lib.get_corpus_channel_names(topic)
        total_channels += len(channel_names)
        for channel_name in channel_names:
            state = ChannelState(config.channel_dir(topic, channel_name) / "state.json")
            modes = {
                video_id: state.get_analysis_mode(video_id)
                for video_id in state.processed_video_ids()
            }
            videos_dir = config.videos_dir(topic, channel_name)
            if videos_dir.is_dir():
                for video_dir in videos_dir.iterdir():
                    metadata_path = video_dir / "metadata.json"
                    if not video_dir.is_dir() or not metadata_path.is_file():
                        continue
                    try:
                        raw: object = json.loads(metadata_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    if not isinstance(raw, dict):
                        continue
                    metadata = cast("dict[str, object]", raw)
                    video_id = str(metadata.get("video_id") or video_dir.name)
                    mode = str(metadata.get("analysis_mode") or "full")
                    modes.setdefault(video_id, mode)
            total_videos += len(modes)
            scan_videos += sum(mode == "scan" for mode in modes.values())
    return topics, total_channels, total_videos, scan_videos
