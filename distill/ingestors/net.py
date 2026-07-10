"""Small shared networking utilities used across ingestion modules.

Centralizes SSRF-safe fetching for the ``urllib.request`` calls scattered across
the codebase: :func:`safe_urlopen` validates the scheme, rejects targets that
resolve to non-public addresses (:func:`is_public_web_url`), and follows
redirects only through a handler that re-validates every hop. Callers should
still pass URLs built from trusted bases where possible.

Connect-time IP pinning (:func:`resolve_public_ip` + :func:`pin_host_to_ip`)
closes the DNS-rebind window for the Python fetch paths -- ``safe_urlopen`` and
the requests-based attachment download resolve+validate the host once and pin
the connection to that IP, while TLS still verifies the original host. The
in-browser scraper (Playwright/Chromium) does its own DNS and is bounded by its
public-web route policy rather than IP pinning.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator

logger = logging.getLogger(__name__)

__all__ = [
    "NetworkError",
    "is_public_web_url",
    "pin_host_to_ip",
    "resolve_public_ip",
    "safe_urlopen",
]

_ALLOWED_SCHEMES = frozenset({"https"})
_PUBLIC_WEB_SCHEMES = frozenset({"http", "https"})


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is globally routable on the public Internet."""

    return ip.is_global and not ip.is_multicast


def _resolve_host_to_addrs(host: str) -> list[str]:
    """Return all addresses ``host`` resolves to, or an empty list on failure.

    Treats a bare IP literal as already-resolved. DNS failure returns ``[]``
    so callers fail closed.
    """
    try:
        parsed_ip = ipaddress.ip_address(host)
    except ValueError:
        parsed_ip = None
    if parsed_ip is not None:
        return [host]
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return [info[4][0] for info in infos if isinstance(info[4][0], str) and info[4][0]]


def resolve_public_ip(url: str) -> str | None:
    """Validate ``url`` and return the single public IP its host resolves to.

    SSRF guard for any code path that fetches an attacker-influenced URL. Returns
    ``None`` for a non-http(s) scheme (``file://``, ``gopher://``, …), a
    missing/loopback host, a DNS failure, or if ANY resolved address is in a
    loopback/private/link-local/reserved/metadata range (fail closed). The
    returned IP is what a caller should connect to via :func:`pin_host_to_ip` so
    the fetch cannot be DNS-rebound to an internal address between this check and
    the connection.
    """
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in _PUBLIC_WEB_SCHEMES:
        return None
    host = (parsed.hostname or "").strip()
    if not host or host.lower() in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return None
    addrs = _resolve_host_to_addrs(host)
    if not addrs:
        return None
    for raw in addrs:
        try:
            ip = ipaddress.ip_address(raw.split("%")[0])
        except ValueError:
            return None
        if not _is_public_ip(ip):
            return None
    return addrs[0].split("%")[0]


def is_public_web_url(url: str) -> bool:
    """Return ``True`` if ``url`` is http(s) and resolves only to public IPs.

    Thin boolean wrapper over :func:`resolve_public_ip`. Pair the resolve form
    with :func:`pin_host_to_ip` when fetching, to also close the DNS-rebind
    window between the check and the connection.
    """
    return resolve_public_ip(url) is not None


@contextlib.contextmanager
def pin_host_to_ip(host: str, ip: str) -> Iterator[None]:
    """Force ``socket.getaddrinfo(host, ...)`` to return only ``ip`` in-scope.

    Closes the DNS-rebind TOCTOU: resolve+validate ``host`` -> ``ip`` once (via
    :func:`resolve_public_ip`), then fetch inside this context so the HTTP client
    connects to the validated ``ip``. TLS SNI and certificate verification still
    use ``host`` (the URL is unchanged), so HTTPS is unaffected. Only ``host`` is
    pinned; other hosts resolve normally.

    Best-effort: the patch is process-global, so a concurrent fetch to the same
    host on another thread would also be pinned. distill fetches sequentially,
    so this is safe in practice -- it is not a general-purpose primitive.
    """
    real_getaddrinfo = socket.getaddrinfo
    # Normalize the pin key so a differently-cased or trailing-dot FQDN form of
    # the same host (Example.com, example.com.) still matches -- otherwise the
    # pin would silently fail open and the host would resolve unpinned.
    norm_host = host.casefold().rstrip(".")

    def _patched(h, *args, **kwargs):  # type: ignore[no-untyped-def]
        h_norm = h.casefold().rstrip(".") if isinstance(h, str) else h
        return real_getaddrinfo(ip if h_norm == norm_host else h, *args, **kwargs)

    socket.getaddrinfo = _patched
    try:
        yield
    finally:
        socket.getaddrinfo = real_getaddrinfo


class _PublicWebRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect target against the SSRF policy.

    ``urllib`` follows 30x redirects transparently, so a trusted host can bounce
    a request to ``http://169.254.169.254/`` or an RFC1918 address. This handler
    runs each redirect hop's URL through :func:`is_public_web_url` and refuses
    the redirect if it points anywhere non-public.

    Residual (accepted): the caller's ``pin_host_to_ip`` pins only the *original*
    host, so a redirect to a *different* public host is boolean-validated here but
    then resolved fresh at connect -- a narrow DNS-rebind window on cross-host
    redirect hops. Closing it fully would require pinning each new host from
    inside this handler, which urllib's model doesn't cleanly allow; the per-hop
    public-URL check bounds the exposure to attacker-controlled rebinding of a
    host that also issues the redirect.
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
    # SSRF guard: resolve+validate the host to a public IP once and pin the
    # connection to it (closing the DNS-rebind window), and follow redirects
    # only through _SSRF_SAFE_OPENER, which re-checks every hop. (Scheme-only
    # validation here previously let a trusted host redirect to an internal
    # address, and a rebind could flip the host after the check.)
    pinned_ip = resolve_public_ip(target_url)
    if pinned_ip is None:
        raise ValueError(f"Refusing to open non-public URL: {target_url}")
    host = parsed.hostname or ""

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with pin_host_to_ip(host, pinned_ip):
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
