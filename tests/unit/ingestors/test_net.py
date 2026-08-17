"""Tests for distill.ingestors.net SSRF guards."""

from __future__ import annotations

import http.client
import io
import socket
import threading
import urllib.error
import urllib.request
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from distill.ingestors import net
from distill.ingestors.net import (
    NetworkDeadline,
    NetworkError,
    _PublicWebRedirectHandler,
    _url_for_log,
    is_public_web_url,
    pin_host_to_ip,
    resolve_public_ip,
    safe_urlopen,
    url_for_diagnostic,
    url_for_persistence,
)

_PUBLIC_IP_URL = "https://8.8.8.8/"  # literal public IP -> no DNS, passes the SSRF guard


def _http_error(code: int, url: str = _PUBLIC_IP_URL) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, f"status {code}", None, None)  # type: ignore[arg-type] - urllib accepts absent headers in tests


def _headers() -> http.client.HTTPMessage:
    return http.client.HTTPMessage()


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",  # loopback
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://localhost/",  # loopback name
        "https://10.0.0.5/",  # RFC1918
        "https://192.168.1.1/",  # RFC1918
        "https://100.64.0.1/",  # shared address space
        "https://192.0.2.1/",  # documentation range
        "https://[2001:db8::1]/",  # IPv6 documentation range
        "https://224.0.0.1/",  # IPv4 multicast
        "https://239.255.255.250/",  # administratively scoped multicast
        "https://[ff02::1]/",  # IPv6 multicast
        "file:///etc/passwd",  # non-http scheme
        "gopher://x/",  # non-http scheme
    ],
)
def test_is_public_web_url_rejects_internal_and_nonhttp(url: str) -> None:
    assert is_public_web_url(url) is False


def test_safe_urlopen_refuses_non_public_target() -> None:
    # Even with an allowed (https) scheme, a host resolving to a non-public IP
    # must be refused before any connection.
    with pytest.raises(ValueError, match="non-public"):
        safe_urlopen("https://127.0.0.1/")
    with pytest.raises(ValueError, match="non-public"):
        safe_urlopen("https://169.254.169.254/x")


def test_safe_urlopen_refuses_nonhttps_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        safe_urlopen("http://example.com/")


def test_resolve_public_ip() -> None:
    # Literal public IP resolves to itself; internal/non-http return None.
    assert resolve_public_ip("https://8.8.8.8/") == "8.8.8.8"
    assert resolve_public_ip("https://127.0.0.1/") is None
    assert resolve_public_ip("https://10.0.0.1/") is None
    assert resolve_public_ip("https://169.254.169.254/") is None
    assert resolve_public_ip("https://100.64.0.1/") is None
    assert resolve_public_ip("https://192.0.2.1/") is None
    assert resolve_public_ip("https://[2001:db8::1]/") is None
    assert resolve_public_ip("https://224.0.0.1/") is None
    assert resolve_public_ip("https://[ff02::1]/") is None
    assert resolve_public_ip("file:///etc/passwd") is None
    assert resolve_public_ip("http://localhost/") is None


def test_host_and_url_normalization_fail_closed_on_malformed_unicode() -> None:
    assert net._resolve_host_to_addrs("\ud800") == []
    assert net._normalize_host("\ud800") is None
    assert resolve_public_ip("https://[") is None


def test_pin_host_to_ip_forces_resolution_and_restores() -> None:
    # Closes the DNS-rebind window: inside the context, the host resolves only to
    # the pinned IP; other hosts are unaffected; getaddrinfo is restored after.
    real = socket.getaddrinfo
    with pin_host_to_ip("example.com", "203.0.113.5"):
        infos = socket.getaddrinfo("example.com", 443)
        assert all(info[4][0] == "203.0.113.5" for info in infos)
        other = socket.getaddrinfo("8.8.8.8", 443)
        assert other[0][4][0] == "8.8.8.8"
    assert socket.getaddrinfo is real


def test_pin_host_to_ip_matches_case_and_trailing_dot() -> None:
    # A differently-cased / FQDN-trailing-dot form of the pinned host must still
    # match, or the pin silently fails open and the host resolves unpinned.
    real = socket.getaddrinfo
    with pin_host_to_ip("Example.COM", "203.0.113.7"):
        infos = socket.getaddrinfo("example.com.", 443)
        assert all(info[4][0] == "203.0.113.7" for info in infos)
    assert socket.getaddrinfo is real


def test_pin_host_to_ip_matches_unicode_and_punycode_forms() -> None:
    real = socket.getaddrinfo
    with pin_host_to_ip("täst.invalid", "93.184.216.34"):
        infos = socket.getaddrinfo("xn--tst-qla.invalid", 443)
        assert all(info[4][0] == "93.184.216.34" for info in infos)
    assert socket.getaddrinfo is real


def test_resolve_public_ip_canonicalizes_idna_before_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    lookups: list[str] = []

    def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(net.socket, "getaddrinfo", fake_getaddrinfo)

    assert resolve_public_ip("https://täst.invalid/file.pdf") == "93.184.216.34"
    assert lookups == ["xn--tst-qla.invalid"]


def test_network_deadline_closes_registered_resource_and_stays_terminal() -> None:
    class Resource:
        closed = False

        def close(self) -> None:
            self.closed = True

    deadline = NetworkDeadline(10)
    resource = Resource()
    deadline.register(resource)

    deadline.cancel()

    assert resource.closed is True
    with pytest.raises(NetworkError, match="deadline"):
        deadline.remaining()


def test_deadline_socket_file_close_releases_underlying_socket() -> None:
    class Socket:
        closed = False

        def close(self) -> None:
            self.closed = True

    socket_resource = Socket()
    stream = net._DeadlineSocketIO(socket_resource)  # type: ignore[arg-type] - close-only socket test double

    stream.close()

    assert socket_resource.closed is True


def test_safe_urlopen_honors_an_already_exhausted_shared_deadline() -> None:
    now = [1.0]
    deadline = NetworkDeadline(10, clock=lambda: now[0])
    now[0] = 12.0
    try:
        with pytest.raises(NetworkError, match="deadline"):
            safe_urlopen(_PUBLIC_IP_URL, deadline=deadline)
    finally:
        deadline.cancel()


def test_pin_host_to_ip_serializes_process_global_patches() -> None:
    real = socket.getaddrinfo
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first() -> None:
        with pin_host_to_ip("first.example", "93.184.216.34"):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def second() -> None:
        assert first_entered.wait(timeout=2)
        with pin_host_to_ip("second.example", "8.8.8.8"):
            second_entered.set()

    first_thread = threading.Thread(target=first)
    second_thread = threading.Thread(target=second)
    first_thread.start()
    second_thread.start()
    assert first_entered.wait(timeout=2)
    try:
        serialized = not second_entered.wait(timeout=0.1)
    finally:
        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

    assert serialized
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert second_entered.is_set()
    assert socket.getaddrinfo is real


# ---------------------------------------------------------------------------
# resolve_public_ip — fail-closed branches
# ---------------------------------------------------------------------------


def test_resolve_public_ip_empty_url_returns_none() -> None:
    assert resolve_public_ip("") is None


def test_resolve_public_ip_dns_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> list[Any]:
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(net.socket, "getaddrinfo", _boom)
    assert resolve_public_ip("https://example.test/") is None


def test_resolve_public_ip_unparseable_resolved_address_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        net.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("not-an-ip", 0))]
    )
    assert resolve_public_ip("https://example.test/") is None


def test_resolve_public_ip_resolves_hostname_to_public_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        net.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    assert resolve_public_ip("https://example.test/") == "93.184.216.34"


def test_resolve_public_ip_rejects_when_any_resolved_addr_is_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail closed: one private address among the resolved set rejects the whole URL.
    monkeypatch.setattr(
        net.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("10.0.0.1", 0))],
    )
    assert resolve_public_ip("https://example.test/") is None


# ---------------------------------------------------------------------------
# _PublicWebRedirectHandler — per-hop re-validation
# ---------------------------------------------------------------------------


def test_redirect_handler_refuses_non_public_target() -> None:
    handler = _PublicWebRedirectHandler()
    req = urllib.request.Request(_PUBLIC_IP_URL)
    with pytest.raises(urllib.error.HTTPError, match="non-public"):
        handler.redirect_request(req, io.BytesIO(), 302, "Found", _headers(), "http://127.0.0.1/")


def test_redirect_handler_allows_public_target() -> None:
    handler = _PublicWebRedirectHandler()
    req = urllib.request.Request(_PUBLIC_IP_URL)
    with pin_host_to_ip("8.8.8.8", "8.8.8.8"):
        result = handler.redirect_request(
            req, io.BytesIO(), 302, "Found", _headers(), "https://93.184.216.34/"
        )
    assert isinstance(result, urllib.request.Request)


def test_redirect_handler_pins_the_validated_cross_host_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[str] = []

    def fake_getaddrinfo(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        lookups.append(host)
        address = "93.184.216.34" if host == "rebind.example" else host
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(net.socket, "getaddrinfo", fake_getaddrinfo)
    handler = _PublicWebRedirectHandler()
    request = urllib.request.Request("https://origin.example/feed")

    with pin_host_to_ip("origin.example", "8.8.8.8"):
        redirected = handler.redirect_request(
            request,
            io.BytesIO(),
            302,
            "Found",
            _headers(),
            "https://rebind.example/private",
        )
        socket.getaddrinfo("rebind.example", 443)

    assert isinstance(redirected, urllib.request.Request)
    assert lookups == ["rebind.example", "93.184.216.34"]


def test_redirect_handler_rejects_https_downgrade() -> None:
    handler = _PublicWebRedirectHandler()
    request = urllib.request.Request(_PUBLIC_IP_URL)

    with (
        pin_host_to_ip("8.8.8.8", "8.8.8.8"),
        pytest.raises(urllib.error.HTTPError, match="non-public"),
    ):
        handler.redirect_request(
            request,
            io.BytesIO(),
            302,
            "Found",
            _headers(),
            "http://93.184.216.34/private",
        )


def test_ssrf_safe_opener_disables_environment_proxies(monkeypatch) -> None:
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: {"https": "http://proxy.example:8080"},
    )
    opener = net._build_ssrf_safe_opener()
    proxy_handlers = [
        handler for handler in opener.handlers if isinstance(handler, urllib.request.ProxyHandler)
    ]

    assert proxy_handlers == []


# ---------------------------------------------------------------------------
# safe_urlopen — retry / backoff state machine (opener mocked, offline)
# ---------------------------------------------------------------------------


def test_safe_urlopen_returns_response_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", lambda *a, **k: sentinel)
    response = safe_urlopen(_PUBLIC_IP_URL)
    try:
        assert response._response is sentinel
    finally:
        response.close()


def test_safe_urlopen_accepts_request_object(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", lambda *a, **k: sentinel)
    response = safe_urlopen(urllib.request.Request(_PUBLIC_IP_URL))
    try:
        assert response._response is sentinel
    finally:
        response.close()


def test_safe_urlopen_refuses_preconfigured_request_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = urllib.request.Request(_PUBLIC_IP_URL)
    request.set_proxy("127.0.0.1:8080", "https")
    monkeypatch.setattr(
        net._SSRF_SAFE_OPENER,
        "open",
        lambda *args, **kwargs: pytest.fail("proxied request must not be opened"),
    )

    with pytest.raises(ValueError, match="preconfigured proxy"):
        safe_urlopen(request)


def test_safe_urlopen_retries_on_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(net.time, "sleep", lambda s: sleeps.append(s))
    sentinel = object()
    calls = {"n": 0}

    def _open(*a: Any, **k: Any) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(503)
        return sentinel

    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", _open)
    response = safe_urlopen(_PUBLIC_IP_URL, retries=2, backoff_base=1.0)
    response.close()
    assert response._response is sentinel
    assert calls["n"] == 2
    assert sleeps == [1.0]  # backoff_base * 2**0


def test_safe_urlopen_429_uses_longer_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(net.time, "sleep", lambda s: sleeps.append(s))
    sentinel = object()
    calls = {"n": 0}

    def _open(*a: Any, **k: Any) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429)
        return sentinel

    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", _open)
    response = safe_urlopen(_PUBLIC_IP_URL, retries=2, backoff_base=1.0)
    response.close()
    assert response._response is sentinel
    assert sleeps == [3.0]  # 429 uses backoff_base * 3


def test_safe_urlopen_4xx_raises_immediately_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def _open(*a: Any, **k: Any) -> object:
        calls["n"] += 1
        raise _http_error(404)

    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", _open)
    with pytest.raises(NetworkError) as ei:
        safe_urlopen(_PUBLIC_IP_URL, retries=3)
    assert calls["n"] == 1  # client error is not retried
    assert ei.value.status_code == 404
    assert ei.value.url == _PUBLIC_IP_URL


def test_safe_urlopen_5xx_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net.time, "sleep", lambda s: None)

    def _open(*a: Any, **k: Any) -> object:
        raise _http_error(500)

    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", _open)
    with pytest.raises(NetworkError) as ei:
        safe_urlopen(_PUBLIC_IP_URL, retries=1, backoff_base=0.0)
    assert ei.value.status_code == 500


def test_safe_urlopen_url_error_retries_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def _open(*a: Any, **k: Any) -> object:
        calls["n"] += 1
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", _open)
    with pytest.raises(NetworkError, match="Network error after 2 attempts"):
        safe_urlopen(_PUBLIC_IP_URL, retries=1, backoff_base=0.0)
    assert calls["n"] == 2


def test_safe_urlopen_timeout_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    sentinel = object()
    calls = {"n": 0}

    def _open(*a: Any, **k: Any) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("slow")
        return sentinel

    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", _open)
    response = safe_urlopen(_PUBLIC_IP_URL, retries=2, backoff_base=0.0)
    response.close()
    assert response._response is sentinel
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# _url_for_log
# ---------------------------------------------------------------------------


def test_url_for_log_clips_long_origin_and_removes_sensitive_components() -> None:
    long_url = "https://user:password@very-long-example.test:8443/private/token?key=secret#x"
    clipped = _url_for_log(long_url, max_len=20)
    assert clipped.endswith("...")
    assert len(clipped) == 23  # 20 + "..."
    assert "user" not in clipped
    assert "password" not in clipped
    assert "private" not in clipped
    assert "secret" not in clipped
    assert _url_for_log("https://x/path?q=secret", max_len=80) == "https://x"


def test_url_for_log_preserves_normalized_ipv6_origin_and_rejects_malformed() -> None:
    assert _url_for_log("HTTPS://[2001:4860:4860::8888]:443/a?b=c") == (
        "https://[2001:4860:4860::8888]:443"
    )
    assert _url_for_log("https://example.com:invalid/secret") == "<invalid-url>"


def test_url_views_omit_secret_bearing_components() -> None:
    raw = "HTTPS://alice:password@Example.COM:8443/private/report?token=canary#section"

    assert url_for_diagnostic(raw) == "https://example.com:8443"
    assert url_for_persistence(raw) == "https://example.com:8443/private/report"


def test_url_views_preserve_ipv6_authority_without_userinfo() -> None:
    raw = "https://alice:password@[2001:4860:4860::8888]:443/a?q=canary"

    assert url_for_diagnostic(raw) == "https://[2001:4860:4860::8888]:443"
    assert url_for_persistence(raw) == "https://[2001:4860:4860::8888]:443/a"


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com:invalid/private?token=canary",
        "not a URL?token=canary",
        "file:///private?token=canary",
    ],
)
def test_url_views_fail_closed_without_reflecting_malformed_input(raw: str) -> None:
    assert url_for_diagnostic(raw) == "<invalid-url>"
    assert url_for_persistence(raw) == "<invalid-url>"


def test_retry_log_never_contains_url_credentials_or_query_secrets(caplog) -> None:
    caplog.set_level("WARNING", logger="distill.ingestors.net")
    deadline = SimpleNamespace(sleep=lambda _wait: None)

    net._retry_delay(
        target_url=(
            "https://user:SENTINEL-USERINFO@example.test/private/SENTINEL-PATH?token=SENTINEL-QUERY"
        ),
        attempt=0,
        retries=1,
        wait=0,
        reason="HTTP 503",
        deadline=deadline,
    )

    rendered = caplog.text
    assert "https://example.test" in rendered
    assert "SENTINEL" not in rendered


@pytest.mark.parametrize("timeout", [True, 0, -1, float("nan"), float("inf"), "1"])
def test_network_deadline_rejects_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        NetworkDeadline(timeout)


def test_deadline_register_after_expiry_closes_resource() -> None:
    current = [0.0]
    deadline = NetworkDeadline(1, clock=lambda: current[0])
    resource = SimpleNamespace(closed=False)
    resource.close = lambda: setattr(resource, "closed", True)
    current[0] = 2.0

    with pytest.raises(NetworkError, match="deadline"):
        deadline.register(resource)

    assert resource.closed is True


def test_deadline_register_closes_resource_if_expiry_wins_registration_race(monkeypatch) -> None:
    resource = SimpleNamespace(closed=False)
    resource.close = lambda: setattr(resource, "closed", True)
    deadline = NetworkDeadline(5)

    def expire_during_registration() -> float:
        deadline._expire()
        return 1.0

    monkeypatch.setattr(deadline, "remaining", expire_during_registration)

    with pytest.raises(NetworkError, match="deadline"):
        deadline.register(resource)

    assert resource.closed is True


def test_deadline_sleep_refuses_an_interval_beyond_the_budget(monkeypatch) -> None:
    deadline = NetworkDeadline(1, clock=lambda: 0.0)
    monkeypatch.setattr(net.time, "sleep", lambda _seconds: None)

    with pytest.raises(NetworkError, match="deadline"):
        deadline.sleep(2)

    deadline.cancel()


def test_deadline_dns_resolution_reports_capacity_and_worker_failures(monkeypatch) -> None:
    class NoCapacity:
        def acquire(self, *, timeout):
            assert timeout > 0
            return False

    deadline = NetworkDeadline(1)
    monkeypatch.setattr(net, "_DNS_RESOLUTION_SLOTS", NoCapacity())
    with pytest.raises(NetworkError, match="deadline"):
        net._resolve_public_ip_before_deadline(_PUBLIC_IP_URL, deadline)
    deadline.cancel()

    class Slots:
        def acquire(self, *, timeout):
            assert timeout > 0
            return True

        def release(self):
            return None

    deadline = NetworkDeadline(1)
    monkeypatch.setattr(net, "_DNS_RESOLUTION_SLOTS", Slots())
    monkeypatch.setattr(
        net,
        "resolve_public_ip",
        lambda _url: (_ for _ in ()).throw(OSError("dns")),
    )
    with pytest.raises(NetworkError, match="DNS resolution failed"):
        net._resolve_public_ip_before_deadline(_PUBLIC_IP_URL, deadline)
    deadline.cancel()


def test_dns_resolution_queue_timeout_fails_closed(monkeypatch) -> None:
    class Slots:
        def acquire(self, *, timeout: float) -> bool:
            return timeout > 0

        def release(self) -> None:
            return None

    class NeverQueue:
        def get(self, *, timeout: float):
            raise net.Empty

        def put(self, _value) -> None:
            return None

    class DormantThread:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def start(self) -> None:
            return None

    deadline = NetworkDeadline(5)
    monkeypatch.setattr(net, "_DNS_RESOLUTION_SLOTS", Slots())
    monkeypatch.setattr(net, "Queue", lambda maxsize: NeverQueue())
    monkeypatch.setattr(net.threading, "Thread", DormantThread)

    with pytest.raises(NetworkError, match="deadline"):
        net._resolve_public_ip_before_deadline(_PUBLIC_IP_URL, deadline)

    deadline.cancel()


def test_redirect_pinning_rejects_malformed_and_unresolved_targets(monkeypatch) -> None:
    assert net._pin_public_redirect("https://[") is False
    monkeypatch.setattr(net, "_resolve_public_ip_before_deadline", lambda *_args: None)
    assert net._pin_public_redirect("https://example.com/docs") is False


def test_pin_host_to_ip_rejects_invalid_inputs_and_restores_nested_state() -> None:
    with (
        pytest.raises(TimeoutError, match="DNS pin lock"),
        pin_host_to_ip("example.com", "8.8.8.8", timeout_seconds=0),
    ):
        raise AssertionError("unreachable")

    with pytest.raises(ValueError, match="hostname"), pin_host_to_ip("bad\x00host", "8.8.8.8"):
        raise AssertionError("unreachable")

    with pytest.raises(ValueError, match="IP address"), pin_host_to_ip("example.com", "not-an-ip"):
        raise AssertionError("unreachable")

    previous = {"prior.example": "1.1.1.1"}
    net._PIN_STATE.pins = previous
    try:
        with pin_host_to_ip("example.com", "8.8.8.8"):
            assert net._PIN_STATE.pins["example.com"] == "8.8.8.8"
        assert net._PIN_STATE.pins == previous
    finally:
        delattr(net._PIN_STATE, "pins")


class _SocketDouble:
    def __init__(self) -> None:
        self.timeout: float | None = None
        self.closed = False
        self.sent: list[bytes] = []
        self.marker = "socket-marker"
        self._reads = 0

    def settimeout(self, value: float | None) -> None:
        self.timeout = value

    def gettimeout(self) -> float | None:
        return self.timeout

    def recv_into(self, buffer, *_args) -> int:
        if self._reads:
            return 0
        self._reads += 1
        buffer[:3] = b"abc"
        return 3

    def sendall(self, data: bytes, *_args) -> None:
        self.sent.append(data)

    def fileno(self) -> int:
        return 9

    def close(self) -> None:
        self.closed = True


def test_deadline_socket_applies_budget_to_io_and_file_views() -> None:
    deadline = NetworkDeadline(5)
    socket_double = _SocketDouble()
    deadline_socket = net._DeadlineSocket(socket_double, deadline)

    deadline_socket.settimeout(None)
    assert 0 < (socket_double.timeout or 0) <= 5
    deadline_socket.settimeout(2)
    assert 0 < (socket_double.timeout or 0) <= 2
    buffer = bytearray(3)
    assert deadline_socket.recv_into(buffer) == 3
    assert bytes(buffer) == b"abc"
    deadline_socket.sendall(b"payload")
    assert socket_double.sent == [b"payload"]
    assert deadline_socket.marker == "socket-marker"

    for kwargs in (
        {"mode": "w"},
        {"encoding": "utf-8"},
        {"errors": "replace"},
        {"newline": "\n"},
    ):
        with pytest.raises(ValueError, match="binary response"):
            deadline_socket.makefile(**kwargs)

    raw = deadline_socket.makefile("rb", buffering=0)
    assert raw.readable() is True
    assert raw.fileno() == 9
    raw.close()
    raw.close()
    assert socket_double.closed is True
    with pytest.raises(ValueError, match="closed"):
        raw.readinto(bytearray(1))
    deadline.cancel()

    deadline = NetworkDeadline(5)
    buffered_socket = _SocketDouble()
    buffered = net._DeadlineSocket(buffered_socket, deadline).makefile("rb")
    assert buffered.read() == b"abc"
    buffered.close()
    deadline.cancel()


def test_deadline_connection_and_handler_cover_deadline_and_plain_paths(monkeypatch) -> None:
    calls: list[str] = []
    response = object()
    monkeypatch.setattr(
        http.client.HTTPSConnection,
        "connect",
        lambda _self: calls.append("connect"),
    )
    monkeypatch.setattr(
        http.client.HTTPSConnection,
        "getresponse",
        lambda _self: calls.append("response") or response,
    )

    connection = net._DeadlineHTTPSConnection("example.com", timeout=10)
    connection.sock = _SocketDouble()  # type: ignore[assignment] - socket-compatible test double
    deadline = NetworkDeadline(5)
    net._PIN_STATE.deadline = deadline
    try:
        connection.connect()
        assert isinstance(connection.sock, net._DeadlineSocket)
        connection.sock = _SocketDouble()  # type: ignore[assignment] - socket-compatible test double
        assert connection.getresponse() is response
        assert isinstance(connection.sock, net._DeadlineSocket)
    finally:
        delattr(net._PIN_STATE, "deadline")
        deadline.cancel()

    plain = net._DeadlineHTTPSConnection("example.com")
    plain.connect()
    assert plain.getresponse() is response
    assert calls == ["connect", "response", "connect", "response"]

    handler = net._DeadlineHTTPSHandler()
    monkeypatch.setattr(
        handler,
        "do_open",
        lambda connection_type, request, **kwargs: (connection_type, request, kwargs),
    )
    request = urllib.request.Request(_PUBLIC_IP_URL)
    opened = handler.https_open(request)
    assert opened[0] is net._DeadlineHTTPSConnection
    assert opened[1] is request


def test_deadline_response_proxies_iteration_attributes_and_idempotent_close() -> None:
    class Response:
        marker = "response-marker"

        def __init__(self) -> None:
            self.closed = 0

        def __iter__(self):
            return iter((b"a", b"b"))

        def close(self) -> None:
            self.closed += 1

    response = Response()
    deadline = NetworkDeadline(5)
    wrapped = net._DeadlineResponse(response, deadline, owns_deadline=False)
    with wrapped as entered:
        assert entered is wrapped
        assert list(entered) == [b"a", b"b"]
        assert entered.marker == "response-marker"
    wrapped.close()
    assert response.closed == 1
    deadline.cancel()

    owned_response = Response()
    owned = net._DeadlineResponse(owned_response, NetworkDeadline(5), owns_deadline=True)
    owned.close()
    assert owned_response.closed == 1


@pytest.mark.parametrize(
    ("timeout", "retries", "backoff", "message"),
    [
        (0, 0, 0, "timeout"),
        (1, True, 0, "retries"),
        (1, 9, 0, "retries"),
        (1, 0, -1, "backoff"),
        (1, 0, float("nan"), "backoff"),
    ],
)
def test_fetch_option_validation_rejects_invalid_values(
    timeout: object,
    retries: object,
    backoff: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        net._validate_fetch_options(timeout, retries, backoff)


@pytest.mark.parametrize("target", ["https://[", "https://bad\x00host/"])
def test_fetch_target_rejects_malformed_or_invalid_hosts(target: str) -> None:
    with pytest.raises(ValueError, match=r"malformed|invalid host"):
        net._fetch_target(target)


def test_retry_loop_cancels_on_unexpected_error_and_deadline_during_backoff(monkeypatch) -> None:
    deadline = NetworkDeadline(5)
    monkeypatch.setattr(
        net,
        "_open_pinned_attempt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        net._open_with_retries(
            _PUBLIC_IP_URL,
            target_url=_PUBLIC_IP_URL,
            host="8.8.8.8",
            pinned_ip="8.8.8.8",
            timeout=1,
            retries=0,
            backoff_base=0,
            deadline=deadline,
            owns_deadline=True,
        )
    with pytest.raises(NetworkError, match="deadline"):
        deadline.remaining()

    deadline = NetworkDeadline(5)
    monkeypatch.setattr(
        net,
        "_open_pinned_attempt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(_http_error(500)),
    )
    monkeypatch.setattr(
        net,
        "_retry_delay",
        lambda **_kwargs: (_ for _ in ()).throw(NetworkError("budget")),
    )
    with pytest.raises(NetworkError, match="budget") as raised:
        net._open_with_retries(
            _PUBLIC_IP_URL,
            target_url=_PUBLIC_IP_URL,
            host="8.8.8.8",
            pinned_ip="8.8.8.8",
            timeout=1,
            retries=1,
            backoff_base=1,
            deadline=deadline,
            owns_deadline=False,
        )
    assert raised.value.url == _PUBLIC_IP_URL
    deadline.cancel()


def test_retry_loop_reports_deadline_during_network_error_backoff(monkeypatch) -> None:
    deadline = NetworkDeadline(5)
    monkeypatch.setattr(
        net,
        "_open_pinned_attempt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    monkeypatch.setattr(
        net,
        "_retry_delay",
        lambda **_kwargs: (_ for _ in ()).throw(NetworkError("budget")),
    )

    with pytest.raises(NetworkError, match="budget") as raised:
        net._open_with_retries(
            _PUBLIC_IP_URL,
            target_url=_PUBLIC_IP_URL,
            host="8.8.8.8",
            pinned_ip="8.8.8.8",
            timeout=1,
            retries=1,
            backoff_base=1,
            deadline=deadline,
            owns_deadline=False,
        )

    assert raised.value.url == _PUBLIC_IP_URL
    deadline.cancel()


def test_open_attempt_restores_a_nested_deadline(monkeypatch) -> None:
    previous = NetworkDeadline(5)
    active = NetworkDeadline(5)
    response = object()
    monkeypatch.setattr(net, "pin_host_to_ip", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(
        net,
        "_SSRF_SAFE_OPENER",
        SimpleNamespace(open=lambda *_args, **_kwargs: response),
    )
    net._PIN_STATE.deadline = previous
    try:
        assert (
            net._open_pinned_attempt(
                _PUBLIC_IP_URL,
                host="8.8.8.8",
                pinned_ip="8.8.8.8",
                timeout=1,
                deadline=active,
            )
            is response
        )
        assert net._PIN_STATE.deadline is previous
    finally:
        delattr(net._PIN_STATE, "deadline")
        active.cancel()
        previous.cancel()


def test_proxy_detection_rejects_a_malformed_request_authority() -> None:
    request = SimpleNamespace(
        has_proxy=lambda: False,
        _tunnel_host=None,
        host="[",
    )

    assert net._request_uses_proxy(request, "https://example.com/docs") is True


def test_https_handler_does_not_forward_check_hostname() -> None:
    """Python 3.12 dropped check_hostname from HTTPSConnection.__init__.

    Forwarding it raised TypeError on every supported interpreter, so the
    Playwright-less search fallback that uses this handler was dead as shipped.
    """
    captured: dict[str, Any] = {}

    class _Recorder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

    handler = net._DeadlineHTTPSHandler()
    handler._context = None
    handler._check_hostname = True

    def fake_do_open(conn_factory: Any, req: Any, **kwargs: Any) -> str:
        conn_factory(req.host, **kwargs)
        return "opened"

    handler.do_open = fake_do_open  # type: ignore[method-assign]
    request = urllib.request.Request("https://example.com/")
    request.timeout = 5

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(net, "_DeadlineHTTPSConnection", _Recorder)
        assert handler.https_open(request) == "opened"

    assert "check_hostname" not in captured
    assert "context" in captured
