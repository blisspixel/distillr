"""Podcast ingestion (RSS-first; publisher transcripts preferred over audio)."""

from distill.ingestors.podcasts.feed import (
    PodcastEpisode,
    PodcastFeed,
    PodcastFetchError,
    download_audio,
    fetch_feed,
    fetch_transcript,
    looks_like_feed_url,
    parse_feed,
)

__all__ = [
    "PodcastEpisode",
    "PodcastFeed",
    "PodcastFetchError",
    "download_audio",
    "fetch_feed",
    "fetch_transcript",
    "looks_like_feed_url",
    "parse_feed",
]
