"""Download X-native video attachments to a local .mp4 for transcription."""

from __future__ import annotations

from pathlib import Path

import httpx

__all__ = ["download_video"]


def download_video(url: str, dest: Path, *, timeout: float = 120.0) -> Path:
    """Stream a public ``video.twimg.com`` .mp4 to *dest*.

    The syndication endpoint hands us a direct ``.mp4`` URL on
    ``video.twimg.com`` which serves without auth for embed clients;
    no yt-dlp / signed-cookie dance required for amplify_video assets.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Referer": "https://platform.twitter.com/",
    }
    with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1 << 16):
                fh.write(chunk)
    return dest
