"""YouTube ingestor — search, download, and transcript acquisition."""

from distill.ingestors.youtube.browser_search import (
    parse_search_results_html,
    search_youtube_results,
)
from distill.ingestors.youtube.discovery import (
    VideoInfo,
    discover_videos,
    enrich_videos,
    get_video_info,
    resolve_channel_name,
    search_videos,
)
from distill.ingestors.youtube.transcripts import get_transcript

__all__ = [
    "VideoInfo",
    "discover_videos",
    "enrich_videos",
    "get_transcript",
    "get_video_info",
    "parse_search_results_html",
    "resolve_channel_name",
    "search_videos",
    "search_youtube_results",
]
