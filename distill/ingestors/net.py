"""Small shared networking utilities used across ingestion modules.

Centralizes URL-scheme validation for the ``urllib.request.urlopen`` calls
scattered across the codebase, so every open goes through a single checked
entry point. Callers should still only pass URLs built from trusted bases
(e.g. the arXiv API endpoint, a hard-coded YouTube search URL constructor).
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

__all__ = ["NetworkError", "safe_urlopen"]

_ALLOWED_SCHEMES = frozenset({"https"})


class NetworkError(Exception):
    """Raised when a network request fails after all retries."""

    def __init__(self, message: str, url: str = "", status_code: int = 0):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


def safe_urlopen(
    url_or_request: str | urllib.request.Request,
    timeout: int = 30,
    retries: int = 3,
    backoff_base: float = 3.0,
):
    """Open an HTTP(S) URL with scheme validation, retry, and exponential backoff.

    Retries on:
    - HTTP 429 (rate limited)
    - HTTP 5xx (server errors)
    - urllib.error.URLError (network connectivity issues)
    - TimeoutError / socket.timeout

    Does NOT retry on:
    - HTTP 4xx (except 429) — client errors are not transient
    - ValueError — scheme validation failure
    """
    target_url = (
        url_or_request.full_url
        if isinstance(url_or_request, urllib.request.Request)
        else url_or_request
    )
    parsed = urllib.parse.urlparse(target_url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Refusing to open URL with scheme {parsed.scheme!r}: {target_url}")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(url_or_request, timeout=timeout)  # nosec B310
        except urllib.error.HTTPError as exc:
            last_error = exc
            if (exc.code == 429 or exc.code >= 500) and attempt < retries:
                # 429s need longer backoff than 5xx — rate limits are time-windowed
                base = backoff_base * 3 if exc.code == 429 else backoff_base
                wait = base * (2**attempt)
                logger.warning(
                    "HTTP %d from %s (attempt %d/%d). Retrying in %.0fs...",
                    exc.code,
                    _truncate_url(target_url),
                    attempt + 1,
                    retries + 1,
                    wait,
                )
                time.sleep(wait)
                continue
            # Non-retryable HTTP error (4xx except 429), or retries exhausted
            raise NetworkError(
                f"HTTP {exc.code} from {_truncate_url(target_url)}: {exc.reason}",
                url=target_url,
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                wait = backoff_base * (2**attempt)
                logger.warning(
                    "Network error from %s (attempt %d/%d): %s. Retrying in %.0fs...",
                    _truncate_url(target_url),
                    attempt + 1,
                    retries + 1,
                    exc,
                    wait,
                )
                time.sleep(wait)
                continue
            raise NetworkError(
                f"Network error after {retries + 1} attempts: {exc}",
                url=target_url,
            ) from exc

    # Should be unreachable
    raise NetworkError(
        f"Failed after {retries + 1} attempts: {last_error}",
        url=target_url,
    )


def _truncate_url(url: str, max_len: int = 80) -> str:
    """Truncate a URL for log messages."""
    return url[:max_len] + "..." if len(url) > max_len else url
