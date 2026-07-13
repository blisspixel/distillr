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
browser scraper uses a loopback CONNECT proxy that applies the same exact-IP
validation before tunneling Chromium traffic without intercepting TLS.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any

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
_PIN_LOCK = threading.RLock()
_PIN_STATE = threading.local()


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

    The socket patch is process-global, so pinned scopes are serialized. Nested
    scopes in one thread remain supported through the reentrant lock. This
    prevents out-of-order restoration from leaving an obsolete resolver active.
    """
    with _PIN_LOCK:
        real_getaddrinfo = socket.getaddrinfo
        previous_pins = getattr(_PIN_STATE, "pins", None)
        pins = dict(previous_pins or {})
        pins[_normalize_host(host)] = ip
        _PIN_STATE.pins = pins

        def _patched(h: str | bytes | None, *args: Any, **kwargs: Any) -> Any:
            normalized = _normalize_host(h) if isinstance(h, str) else h
            pinned = pins.get(normalized, h)
            return real_getaddrinfo(pinned, *args, **kwargs)

        socket.getaddrinfo = _patched
        try:
            yield
        finally:
            socket.getaddrinfo = real_getaddrinfo
            if previous_pins is None:
                delattr(_PIN_STATE, "pins")
            else:
                _PIN_STATE.pins = previous_pins


def _normalize_host(host: str) -> str:
    """Return the canonical pin-map key for a hostname."""

    return host.casefold().rstrip(".")


def _pin_public_redirect(url: str) -> bool:
    """Validate an HTTPS redirect and retain its IP for the pending connect."""

    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    host = parsed.hostname or ""
    pinned_ip = resolve_public_ip(url)
    pins = getattr(_PIN_STATE, "pins", None)
    if not host or pinned_ip is None or pins is None:
        return False
    pins[_normalize_host(host)] = pinned_ip
    return True


class _PublicWebRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect target against the SSRF policy.

    ``urllib`` follows 30x redirects transparently, so a trusted host can bounce
    a request to ``http://169.254.169.254/`` or an RFC1918 address. This handler
    validates each redirect hop, retains the selected public IP in the active
    pin scope, and refuses scheme downgrades. The subsequent urllib connection
    therefore resolves the redirect host to the exact address that passed the
    policy check.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if not _pin_public_redirect(newurl):
            raise urllib.error.HTTPError(
                newurl, code, "refusing redirect to non-public URL", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# A proxy would resolve the target outside this process and bypass the exact-IP
# pin. Security-sensitive fetches therefore use a direct connection.
def _build_ssrf_safe_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _PublicWebRedirectHandler(),
    )


_SSRF_SAFE_OPENER = _build_ssrf_safe_opener()


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
    if isinstance(url_or_request, urllib.request.Request) and _request_uses_proxy(
        url_or_request, target_url
    ):
        raise ValueError("Refusing a request with a preconfigured proxy")
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


def _request_uses_proxy(request: urllib.request.Request, target_url: str) -> bool:
    """Detect Request mutation that would route around the direct opener."""

    if request.has_proxy() or getattr(request, "_tunnel_host", None) is not None:
        return True
    target_host = urllib.parse.urlparse(target_url).hostname or ""
    try:
        request_host = urllib.parse.urlsplit(f"//{request.host}").hostname or ""
    except ValueError:
        return True
    return _normalize_host(request_host) != _normalize_host(target_host)


def _truncate_url(url: str, max_len: int = 80) -> str:
    """Truncate a URL for log messages."""
    return url[:max_len] + "..." if len(url) > max_len else url
