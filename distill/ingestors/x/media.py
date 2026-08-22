"""Download X-native video attachments to a local .mp4 for transcription."""

from __future__ import annotations

import urllib.parse
from pathlib import Path
from tempfile import NamedTemporaryFile

from distill.ingestors.net import (
    is_public_web_url,
    pin_host_to_ip,
    resolve_public_ip,
    url_for_diagnostic,
)

__all__ = ["download_video", "is_reusable_video"]


def __getattr__(name: str) -> object:
    """Lazily expose ``httpx`` so importing this module stays cheap.

    Only the live download path needs ``httpx``; deferring it keeps the
    library off the CLI startup path. Tests that patch
    ``distill.ingestors.x.media.httpx.stream`` keep working: this hook
    resolves ``httpx`` to the real module on first attribute access.
    """
    if name == "httpx":
        import httpx

        return httpx
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    on_twimg = host == "twimg.com" or host.endswith(".twimg.com")
    return parsed.scheme.lower() == "https" and on_twimg and is_public_web_url(url)


def is_reusable_video(path: Path) -> bool:
    """Return whether a cached media file is nonempty and within the byte cap."""

    try:
        return path.is_file() and 0 < path.stat().st_size <= _MAX_VIDEO_BYTES
    except OSError:
        return False


def download_video(url: str, dest: Path, *, timeout: float = 120.0) -> Path:
    """Stream a public ``video.twimg.com`` .mp4 to *dest*.

    ``url`` originates from the (attacker-influenced) syndication response, so it
    is restricted to HTTPS on ``*.twimg.com`` plus a public IP, redirects are
    re-validated per hop, and the body is size-capped. These controls prevent
    SSRF and cleartext transport downgrade from hostile response metadata.
    """
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not _is_allowed_video_url(current):
            raise ValueError(f"refusing non-allowlisted video URL: {url_for_diagnostic(current)}")
        # Pin the connection to the validated public IP so a DNS rebind between
        # the is_public_web_url check and httpx's connect can't flip the host to
        # an internal address (pin_host_to_ip patches socket.getaddrinfo, which
        # httpx's sync resolver goes through).
        pinned_ip = resolve_public_ip(current)
        if pinned_ip is None:
            raise ValueError(f"refusing non-public video URL: {url_for_diagnostic(current)}")
        host = urllib.parse.urlparse(current).hostname or ""
        with (
            pin_host_to_ip(host, pinned_ip),
            httpx.stream(
                "GET",
                current,
                headers=_HEADERS,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as resp,
        ):
            if resp.is_redirect:
                current = urllib.parse.urljoin(current, resp.headers.get("location", ""))
                continue
            resp.raise_for_status()
            temporary_path: Path | None = None
            try:
                written = 0
                with NamedTemporaryFile(
                    mode="wb",
                    dir=dest.parent,
                    prefix=f".{dest.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as stream:
                    temporary_path = Path(stream.name)
                    for chunk in resp.iter_bytes(chunk_size=1 << 16):
                        written += len(chunk)
                        if written > _MAX_VIDEO_BYTES:
                            raise ValueError(
                                f"video exceeds {_MAX_VIDEO_BYTES}-byte cap: "
                                f"{url_for_diagnostic(url)}"
                            )
                        stream.write(chunk)
                if written == 0:
                    raise ValueError(f"video response was empty: {url_for_diagnostic(url)}")
                temporary_path.replace(dest)
                return dest
            except BaseException:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
                raise
    raise ValueError(f"too many redirects fetching video: {url_for_diagnostic(url)}")
