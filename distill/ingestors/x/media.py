"""Download X-native video attachments to a local .mp4 for transcription."""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import httpx

from distill.ingestors.net import is_public_web_url

__all__ = ["download_video"]

# X serves amplify_video assets from video.twimg.com. The video URL comes from
# the attacker-influenced syndication JSON, so it is pinned to *.twimg.com AND
# required to resolve to a public IP -- otherwise a hostile tweet could point it
# at http://169.254.169.254/ or an internal host (SSRF). Redirects are followed
# only to likewise-allowed hosts, and the download is size-capped.
_MAX_VIDEO_BYTES = 500 * 1024 * 1024  # 500 MB
_MAX_REDIRECTS = 5
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://platform.twitter.com/",
}


def _is_allowed_video_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    on_twimg = host == "twimg.com" or host.endswith(".twimg.com")
    return on_twimg and is_public_web_url(url)


def download_video(url: str, dest: Path, *, timeout: float = 120.0) -> Path:
    """Stream a public ``video.twimg.com`` .mp4 to *dest*.

    ``url`` originates from the (attacker-influenced) syndication response, so it
    is pinned to ``*.twimg.com`` + a public IP, redirects are re-validated per
    hop, and the body is size-capped -- preventing the SSRF a hostile tweet's
    chosen video URL could otherwise trigger.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not _is_allowed_video_url(current):
            raise ValueError(f"refusing non-allowlisted video URL: {current}")
        with httpx.stream(
            "GET", current, headers=_HEADERS, timeout=timeout, follow_redirects=False
        ) as resp:
            if resp.is_redirect:
                current = urllib.parse.urljoin(current, resp.headers.get("location", ""))
                continue
            resp.raise_for_status()
            written = 0
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 16):
                    written += len(chunk)
                    if written > _MAX_VIDEO_BYTES:
                        raise ValueError(f"video exceeds {_MAX_VIDEO_BYTES}-byte cap: {url}")
                    fh.write(chunk)
            return dest
    raise ValueError(f"too many redirects fetching video: {url}")
