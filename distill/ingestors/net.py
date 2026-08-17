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
import http.client
import io
import ipaddress
import logging
import math
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from queue import Empty, Queue
from typing import Any

import idna

logger = logging.getLogger(__name__)

__all__ = [
    "NetworkDeadline",
    "NetworkError",
    "is_public_web_url",
    "pin_host_to_ip",
    "resolve_public_ip",
    "safe_urlopen",
    "url_for_diagnostic",
    "url_for_persistence",
]

_ALLOWED_SCHEMES = frozenset({"https"})
_PUBLIC_WEB_SCHEMES = frozenset({"http", "https"})
_PIN_LOCK = threading.RLock()
_PIN_STATE = threading.local()
_DNS_RESOLUTION_SLOTS = threading.BoundedSemaphore(8)


class NetworkError(Exception):
    """Raised when a network request fails or exhausts its work budget."""

    def __init__(self, message: str, url: str = "", status_code: int = 0):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class NetworkDeadline:
    """One monotonic deadline that can interrupt registered network resources."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        clock: Any = None,
        label: str = "network operation",
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("network timeout must be a positive finite number")
        self.timeout_seconds = float(timeout_seconds)
        self.label = label
        self._clock = time.monotonic if clock is None else clock
        self._expires_at = self._clock() + self.timeout_seconds
        self._lock = threading.Lock()
        self._resources: dict[int, Any] = {}
        self._expired = False
        self._timer = threading.Timer(self.timeout_seconds, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _error(self) -> NetworkError:
        return NetworkError(f"{self.label} exceeded its {self.timeout_seconds:g}-second deadline")

    def _expire(self) -> None:
        with self._lock:
            if self._expired:
                return
            self._expired = True
            resources = list(self._resources.values())
            self._resources.clear()
        for resource in resources:
            with contextlib.suppress(Exception):
                resource.close()

    def remaining(self) -> float:
        remaining = self._expires_at - self._clock()
        if remaining <= 0:
            self._expire()
            raise self._error()
        with self._lock:
            expired = self._expired
        if expired:
            raise self._error()
        return remaining

    def register(self, resource: Any) -> None:
        try:
            self.remaining()
        except NetworkError:
            with contextlib.suppress(Exception):
                resource.close()
            raise
        with self._lock:
            if not self._expired:
                self._resources[id(resource)] = resource
                return
        with contextlib.suppress(Exception):
            resource.close()
        raise self._error()

    def unregister(self, resource: Any) -> None:
        with self._lock:
            self._resources.pop(id(resource), None)

    def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            self.remaining()
            return
        remaining = self.remaining()
        time.sleep(min(seconds, remaining))
        if seconds >= remaining:
            raise self._error()
        self.remaining()

    def cancel(self) -> None:
        self._timer.cancel()
        self._expire()


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is globally routable on the public Internet."""

    return ip.is_global and not ip.is_multicast


def _resolve_host_to_addrs(host: str) -> list[str]:
    """Return all addresses ``host`` resolves to, or an empty list on failure.

    Treats a bare IP literal as already-resolved. DNS failure returns ``[]``
    so callers fail closed.
    """
    normalized_host = _normalize_host(host)
    if normalized_host is None:
        return []
    try:
        parsed_ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        parsed_ip = None
    if parsed_ip is not None:
        return [parsed_ip.compressed]
    try:
        infos = socket.getaddrinfo(normalized_host, None)
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
    host = _normalize_host((parsed.hostname or "").strip())
    if not host or host in {"localhost", "ip6-localhost", "ip6-loopback"}:
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


def _resolve_public_ip_before_deadline(
    url: str,
    deadline: NetworkDeadline | None,
) -> str | None:
    """Resolve in a bounded daemon worker so DNS cannot overrun a fetch."""

    if deadline is None:
        return resolve_public_ip(url)
    if not _DNS_RESOLUTION_SLOTS.acquire(timeout=deadline.remaining()):
        raise deadline._error()
    outcomes: Queue[str | None | Exception] = Queue(maxsize=1)

    def resolve() -> None:
        try:
            outcomes.put(resolve_public_ip(url))
        except Exception as exc:
            outcomes.put(exc)
        finally:
            _DNS_RESOLUTION_SLOTS.release()

    threading.Thread(target=resolve, daemon=True, name="distill-network-dns").start()
    try:
        outcome = outcomes.get(timeout=deadline.remaining())
    except Empty as exc:
        raise deadline._error() from exc
    deadline.remaining()
    if isinstance(outcome, Exception):
        raise NetworkError(f"DNS resolution failed: {outcome}", url=url) from outcome
    return outcome


@contextlib.contextmanager
def pin_host_to_ip(
    host: str,
    ip: str,
    *,
    timeout_seconds: float | None = None,
) -> Iterator[None]:
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
    if timeout_seconds is None:
        acquired = _PIN_LOCK.acquire()
    elif timeout_seconds <= 0:
        acquired = False
    else:
        acquired = _PIN_LOCK.acquire(timeout=timeout_seconds)
    if not acquired:
        raise TimeoutError("timed out waiting for the process-wide DNS pin lock")
    try:
        real_getaddrinfo = socket.getaddrinfo
        previous_pins = getattr(_PIN_STATE, "pins", None)
        pins = dict(previous_pins or {})
        normalized_host = _normalize_host(host)
        if normalized_host is None:
            raise ValueError("cannot pin an invalid hostname")
        try:
            normalized_ip = ipaddress.ip_address(ip.split("%", 1)[0]).compressed
        except ValueError as exc:
            raise ValueError("cannot pin an invalid IP address") from exc
        pins[normalized_host] = normalized_ip
        _PIN_STATE.pins = pins

        def _patched(h: str | bytes | None, *args: Any, **kwargs: Any) -> Any:
            normalized = _normalize_host(h) if isinstance(h, str) else h
            pinned = pins.get(normalized, h) if normalized is not None else h
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
    finally:
        _PIN_LOCK.release()


def _normalize_host(host: str) -> str | None:
    """Return the HTTP-stack-compatible canonical key for a hostname.

    Requests and urllib3 convert Unicode authorities to UTS 46 IDNA ASCII
    before connecting. The pin map must use the same representation or a
    validated Unicode name can be resolved again under its punycode spelling.
    """

    candidate = host.strip().rstrip(".")
    if not candidate or "\x00" in candidate:
        return None
    try:
        address = ipaddress.ip_address(candidate.split("%", 1)[0])
    except ValueError:
        address = None
    if address is not None:
        return address.compressed.casefold()
    try:
        return idna.encode(candidate, uts46=True, std3_rules=True).decode("ascii").casefold()
    except (idna.IDNAError, UnicodeError):
        return None


def _pin_public_redirect(url: str) -> bool:
    """Validate an HTTPS redirect and retain its IP for the pending connect."""

    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    host = _normalize_host(parsed.hostname or "")
    deadline = getattr(_PIN_STATE, "deadline", None)
    pinned_ip = _resolve_public_ip_before_deadline(url, deadline)
    pins = getattr(_PIN_STATE, "pins", None)
    if not host or pinned_ip is None or pins is None:
        return False
    pins[host] = pinned_ip
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

    max_redirections = 5
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if not _pin_public_redirect(newurl):
            raise urllib.error.HTTPError(
                newurl, code, "refusing redirect to non-public URL", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _DeadlineSocketIO(io.RawIOBase):
    """Unbuffered response reader that reapplies one absolute deadline."""

    def __init__(self, deadline_socket: _DeadlineSocket) -> None:
        super().__init__()
        self._deadline_socket = deadline_socket

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        if self.closed:
            raise ValueError("I/O operation on closed deadline socket")
        return self._deadline_socket.recv_into(buffer)

    def fileno(self) -> int:
        return self._deadline_socket.fileno()

    def close(self) -> None:
        if self.closed:
            return
        with contextlib.suppress(OSError):
            self._deadline_socket.close()
        super().close()


class _DeadlineSocket:
    """Socket proxy whose blocking sends and receives share one deadline."""

    def __init__(self, sock: Any, deadline: NetworkDeadline) -> None:
        self._socket = sock
        self._deadline = deadline

    def _cap_timeout(self, requested: float | None) -> None:
        remaining = self._deadline.remaining()
        effective = remaining if requested is None else min(float(requested), remaining)
        self._socket.settimeout(effective)

    def settimeout(self, value: float | None) -> None:
        self._cap_timeout(value)

    def recv_into(self, buffer: Any, *args: Any) -> int:
        self._cap_timeout(self._socket.gettimeout())
        received = self._socket.recv_into(buffer, *args)
        self._deadline.remaining()
        return int(received)

    def sendall(self, data: Any, *args: Any) -> None:
        self._cap_timeout(self._socket.gettimeout())
        self._socket.sendall(data, *args)
        self._deadline.remaining()

    def makefile(
        self,
        mode: str = "r",
        buffering: int | None = None,
        *,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> Any:
        if (
            mode not in {"r", "rb"}
            or encoding is not None
            or errors is not None
            or newline is not None
        ):
            raise ValueError("deadline socket supports binary response reads only")
        raw = _DeadlineSocketIO(self)
        if buffering == 0:
            return raw
        buffer_size = io.DEFAULT_BUFFER_SIZE if buffering in {None, -1} else buffering
        assert buffer_size is not None
        return io.BufferedReader(raw, buffer_size)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._socket, name)


class _DeadlineHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection whose headers and body inherit the active deadline."""

    def connect(self) -> None:
        deadline = getattr(_PIN_STATE, "deadline", None)
        if not isinstance(deadline, NetworkDeadline):
            super().connect()
            return
        deadline.register(self)
        try:
            remaining = deadline.remaining()
            self.timeout = (
                remaining if self.timeout is None else min(float(self.timeout), remaining)
            )
            super().connect()
            if self.sock is not None and not isinstance(self.sock, _DeadlineSocket):
                self.sock = _DeadlineSocket(self.sock, deadline)  # type: ignore[assignment] - socket-compatible deadline proxy
            deadline.remaining()
        finally:
            deadline.unregister(self)

    def getresponse(self) -> http.client.HTTPResponse:
        deadline = getattr(_PIN_STATE, "deadline", None)
        if not isinstance(deadline, NetworkDeadline):
            return super().getresponse()
        if self.sock is not None and not isinstance(self.sock, _DeadlineSocket):
            self.sock = _DeadlineSocket(self.sock, deadline)  # type: ignore[assignment] - socket-compatible deadline proxy
        deadline.register(self)
        try:
            response = super().getresponse()
            deadline.remaining()
            return response
        finally:
            deadline.unregister(self)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # type: ignore[override] - urllib exposes a dynamic handler signature
        # Python 3.12 removed ``check_hostname`` from ``HTTPSConnection.__init__``;
        # forwarding it raised TypeError on every supported interpreter, so this
        # whole fallback path was dead as shipped (requires-python is >= 3.12).
        # Hostname verification rides on the SSLContext, exactly as CPython's own
        # HTTPSHandler.https_open does on 3.12+.
        return self.do_open(
            _DeadlineHTTPSConnection,
            req,
            context=getattr(self, "_context", None),
        )


class _DeadlineResponse:
    """Response proxy that keeps the deadline active through caller reads."""

    def __init__(
        self,
        response: Any,
        deadline: NetworkDeadline,
        *,
        owns_deadline: bool,
    ) -> None:
        self._response = response
        self._deadline = deadline
        self._owns_deadline = owns_deadline
        self._closed = False
        deadline.register(response)

    def __enter__(self) -> _DeadlineResponse:
        self._deadline.remaining()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        self.close()

    def __iter__(self):
        return iter(self._response)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._deadline.unregister(self._response)
        with contextlib.suppress(Exception):
            self._response.close()
        if self._owns_deadline:
            self._deadline.cancel()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)


# A proxy would resolve the target outside this process and bypass the exact-IP
# pin. Security-sensitive fetches therefore use a direct connection.
def _build_ssrf_safe_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _PublicWebRedirectHandler(),
        _DeadlineHTTPSHandler(),
    )


_SSRF_SAFE_OPENER = _build_ssrf_safe_opener()


def _validate_fetch_options(timeout: float, retries: int, backoff_base: float) -> None:
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("network timeout must be a positive finite number")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 8:
        raise ValueError("network retries must be an integer between 0 and 8")
    if (
        isinstance(backoff_base, bool)
        or not isinstance(backoff_base, (int, float))
        or not math.isfinite(backoff_base)
        or backoff_base < 0
    ):
        raise ValueError("network backoff must be a non-negative finite number")


def _fetch_target(
    url_or_request: str | urllib.request.Request,
) -> tuple[str, str]:
    target_url = (
        url_or_request.full_url
        if isinstance(url_or_request, urllib.request.Request)
        else url_or_request
    )
    if isinstance(url_or_request, urllib.request.Request) and _request_uses_proxy(
        url_or_request, target_url
    ):
        raise ValueError("Refusing a request with a preconfigured proxy")
    try:
        parsed = urllib.parse.urlparse(target_url)
    except ValueError as exc:
        raise ValueError(f"Refusing malformed URL: {_url_for_log(target_url)}") from exc
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"Refusing to open URL with scheme {parsed.scheme!r}: {_url_for_log(target_url)}"
        )
    host = _normalize_host(parsed.hostname or "")
    if host is None:
        raise ValueError(f"Refusing to open URL with invalid host: {_url_for_log(target_url)}")
    return target_url, host


def _cancel_owned_deadline(deadline: NetworkDeadline, owns_deadline: bool) -> None:
    if owns_deadline:
        deadline.cancel()


def _open_pinned_attempt(
    url_or_request: str | urllib.request.Request,
    *,
    host: str,
    pinned_ip: str,
    timeout: float,
    deadline: NetworkDeadline,
) -> Any:
    previous_deadline = getattr(_PIN_STATE, "deadline", None)
    _PIN_STATE.deadline = deadline
    try:
        with pin_host_to_ip(
            host,
            pinned_ip,
            timeout_seconds=deadline.remaining(),
        ):
            return _SSRF_SAFE_OPENER.open(  # nosec B310
                url_or_request,
                timeout=min(timeout, deadline.remaining()),
            )
    finally:
        if previous_deadline is None:
            with contextlib.suppress(AttributeError):
                delattr(_PIN_STATE, "deadline")
        else:
            _PIN_STATE.deadline = previous_deadline


def _retry_delay(
    *,
    target_url: str,
    attempt: int,
    retries: int,
    wait: float,
    reason: str,
    deadline: NetworkDeadline,
) -> None:
    logger.warning(
        "%s from %s (attempt %d/%d). Retrying in %.0fs...",
        reason,
        _url_for_log(target_url),
        attempt + 1,
        retries + 1,
        wait,
    )
    deadline.sleep(wait)


def _open_with_retries(
    url_or_request: str | urllib.request.Request,
    *,
    target_url: str,
    host: str,
    pinned_ip: str,
    timeout: float,
    retries: int,
    backoff_base: float,
    deadline: NetworkDeadline,
    owns_deadline: bool,
) -> _DeadlineResponse:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = _open_pinned_attempt(
                url_or_request,
                host=host,
                pinned_ip=pinned_ip,
                timeout=timeout,
                deadline=deadline,
            )
            return _DeadlineResponse(response, deadline, owns_deadline=owns_deadline)
        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code == 429 or exc.code >= 500
            if retryable and attempt < retries:
                base = backoff_base * 3 if exc.code == 429 else backoff_base
                exc.close()
                try:
                    _retry_delay(
                        target_url=target_url,
                        attempt=attempt,
                        retries=retries,
                        wait=base * (2**attempt),
                        reason=f"HTTP {exc.code}",
                        deadline=deadline,
                    )
                except NetworkError as deadline_exc:
                    _cancel_owned_deadline(deadline, owns_deadline)
                    deadline_exc.url = target_url
                    raise deadline_exc from exc
                continue
            exc.close()
            _cancel_owned_deadline(deadline, owns_deadline)
            raise NetworkError(
                f"HTTP {exc.code} from {_url_for_log(target_url)}: {exc.reason}",
                url=target_url,
                status_code=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                try:
                    _retry_delay(
                        target_url=target_url,
                        attempt=attempt,
                        retries=retries,
                        wait=backoff_base * (2**attempt),
                        reason=f"Network error: {exc}",
                        deadline=deadline,
                    )
                except NetworkError as deadline_exc:
                    _cancel_owned_deadline(deadline, owns_deadline)
                    deadline_exc.url = target_url
                    raise deadline_exc from exc
                continue
            _cancel_owned_deadline(deadline, owns_deadline)
            raise NetworkError(
                f"Network error after {retries + 1} attempts: {exc}",
                url=target_url,
            ) from exc
        except Exception:
            _cancel_owned_deadline(deadline, owns_deadline)
            raise
    _cancel_owned_deadline(deadline, owns_deadline)
    raise NetworkError(
        f"Failed after {retries + 1} attempts: {last_error}",
        url=target_url,
    )


def safe_urlopen(
    url_or_request: str | urllib.request.Request,
    timeout: float = 30,
    retries: int = 3,
    backoff_base: float = 3.0,
    *,
    deadline: NetworkDeadline | None = None,
):
    """Open public HTTPS under one absolute DNS-to-body deadline.

    ``timeout`` covers DNS, the pin lock, connect, TLS, response headers,
    redirects, caller body reads, retries, and backoff. A shared ``deadline``
    lets a caller compose several requests under one workflow budget.
    """
    _validate_fetch_options(timeout, retries, backoff_base)
    target_url, host = _fetch_target(url_or_request)
    owns_deadline = deadline is None
    active_deadline = deadline or NetworkDeadline(
        float(timeout),
        label=f"fetch from {_url_for_log(target_url)}",
    )
    # SSRF guard: resolve+validate the host to a public IP once and pin the
    # connection to it (closing the DNS-rebind window), and follow redirects
    # only through _SSRF_SAFE_OPENER, which re-checks every hop. (Scheme-only
    # validation here previously let a trusted host redirect to an internal
    # address, and a rebind could flip the host after the check.)
    try:
        pinned_ip = _resolve_public_ip_before_deadline(target_url, active_deadline)
    except Exception:
        _cancel_owned_deadline(active_deadline, owns_deadline)
        raise
    if pinned_ip is None:
        _cancel_owned_deadline(active_deadline, owns_deadline)
        raise ValueError(f"Refusing to open non-public URL: {_url_for_log(target_url)}")
    return _open_with_retries(
        url_or_request,
        target_url=target_url,
        host=host,
        pinned_ip=pinned_ip,
        timeout=float(timeout),
        retries=retries,
        backoff_base=float(backoff_base),
        deadline=active_deadline,
        owns_deadline=owns_deadline,
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
    normalized_request = _normalize_host(request_host)
    normalized_target = _normalize_host(target_host)
    return (
        normalized_request is None
        or normalized_target is None
        or normalized_request != normalized_target
    )


def _safe_url_view_parts(url: str) -> tuple[str, str, str] | None:
    """Return normalized public-web scheme, authority, and path URL parts."""

    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
        host = _normalize_host(parsed.hostname or "")
        port = parsed.port
    except (ValueError, UnicodeError):
        return None
    scheme = parsed.scheme.lower()
    if scheme not in _PUBLIC_WEB_SCHEMES or host is None:
        return None
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority = f"{authority}:{port}"
    return scheme, authority, parsed.path or "/"


def url_for_diagnostic(url: str, max_len: int = 80) -> str:
    """Render only a normalized URL origin for diagnostics."""

    parts = _safe_url_view_parts(url)
    if parts is None:
        return "<invalid-url>"
    scheme, authority, _path = parts
    rendered = urllib.parse.urlunsplit((scheme, authority, "", "", ""))
    return rendered[:max_len] + "..." if len(rendered) > max_len else rendered


def url_for_persistence(url: str) -> str:
    """Render scheme, host, explicit port, and path for storage or model input."""

    parts = _safe_url_view_parts(url)
    if parts is None:
        return "<invalid-url>"
    scheme, authority, path = parts
    return urllib.parse.urlunsplit((scheme, authority, path, "", ""))


def _url_for_log(url: str, max_len: int = 80) -> str:
    """Compatibility wrapper for the public diagnostic URL view."""

    return url_for_diagnostic(url, max_len=max_len)
