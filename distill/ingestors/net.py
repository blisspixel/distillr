"""Small shared networking utilities used across ingestion modules.

Centralizes SSRF-safe fetching for the ``urllib.request`` calls scattered across
the codebase: :func:`safe_urlopen` validates the scheme, rejects targets that
resolve to non-public addresses (:func:`is_public_web_url`), and follows
redirects only through a handler that re-validates every hop. Callers should
still pass URLs built from trusted bases where possible.

Residual risk: the public-IP check resolves DNS independently of the subsequent
connection, so a determined attacker controlling DNS with a low TTL can in
principle rebind between the check and the fetch. Host-pinned callers (arXiv)
are unaffected; closing it fully needs connect-time IP pinning.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

__all__ = ["NetworkError", "is_public_web_url", "safe_urlopen"]

_ALLOWED_SCHEMES = frozenset({"https"})
_PUBLIC_WEB_SCHEMES = frozenset({"http", "https"})


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_host_to_addrs(host: str) -> list[str]:
    """Return all addresses ``host`` resolves to, or an empty list on failure.

    Treats a bare IP literal as already-resolved. DNS failure returns ``[]``
    so callers fail closed.
    """
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return [info[4][0] for info in infos if isinstance(info[4][0], str) and info[4][0]]


def is_public_web_url(url: str) -> bool:
    """Return ``True`` if ``url`` is http(s) and resolves to a public IP.

    SSRF guard for any code path that fetches an attacker-influenced URL —
    site seeds, attachment downloads, redirects. Rejects:

    - non-http(s) schemes (``file://``, ``gopher://``, ``ftp://``, …)
    - bare-IP hosts that fall in loopback/private/link-local/reserved/metadata
      ranges (RFC1918, 127.0.0.0/8, 169.254.0.0/16, ::1, fc00::/7, …)
    - hostnames that resolve to any address in those ranges

    Best-effort: DNS resolution failure returns ``False`` (refuse to fetch).
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in _PUBLIC_WEB_SCHEMES:
        return False
    host = (parsed.hostname or "").strip()
    if not host or host.lower() in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return False

    addrs = _resolve_host_to_addrs(host)
    if not addrs:
        return False
    for raw in addrs:
        try:
            ip = ipaddress.ip_address(raw.split("%")[0])
        except ValueError:
            return False
        if not _is_public_ip(ip):
            return False
    return True


class _PublicWebRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect target against the SSRF policy.

    ``urllib`` follows 30x redirects transparently, so a trusted host can bounce
    a request to ``http://169.254.169.254/`` or an RFC1918 address. This handler
    runs each redirect hop's URL through :func:`is_public_web_url` and refuses
    the redirect if it points anywhere non-public.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if not is_public_web_url(newurl):
            raise urllib.error.HTTPError(
                newurl, code, "refusing redirect to non-public URL", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SSRF_SAFE_OPENER = urllib.request.build_opener(_PublicWebRedirectHandler())


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
    # SSRF guard: reject a target whose host resolves to a non-public address,
    # and follow redirects only through _SSRF_SAFE_OPENER, which re-checks every
    # hop. (Scheme-only validation here previously let a trusted host redirect to
    # an internal/metadata address.)
    if not is_public_web_url(target_url):
        raise ValueError(f"Refusing to open non-public URL: {target_url}")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return _SSRF_SAFE_OPENER.open(url_or_request, timeout=timeout)  # nosec B310
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
