"""Tests for distill.ingestors.net SSRF guards."""

from __future__ import annotations

import http.client
import io
import socket
import urllib.error
import urllib.request
from typing import Any

import pytest

from distill.ingestors import net
from distill.ingestors.net import (
    NetworkError,
    _PublicWebRedirectHandler,
    _truncate_url,
    is_public_web_url,
    pin_host_to_ip,
    resolve_public_ip,
    safe_urlopen,
)

_PUBLIC_IP_URL = "https://8.8.8.8/"  # literal public IP -> no DNS, passes the SSRF guard


def _http_error(code: int, url: str = _PUBLIC_IP_URL) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, f"status {code}", None, None)  # type: ignore[arg-type]


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
    result = handler.redirect_request(
        req, io.BytesIO(), 302, "Found", _headers(), "https://93.184.216.34/"
    )
    assert isinstance(result, urllib.request.Request)


# ---------------------------------------------------------------------------
# safe_urlopen — retry / backoff state machine (opener mocked, offline)
# ---------------------------------------------------------------------------


def test_safe_urlopen_returns_response_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", lambda *a, **k: sentinel)
    assert safe_urlopen(_PUBLIC_IP_URL) is sentinel


def test_safe_urlopen_accepts_request_object(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(net._SSRF_SAFE_OPENER, "open", lambda *a, **k: sentinel)
    assert safe_urlopen(urllib.request.Request(_PUBLIC_IP_URL)) is sentinel


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
    assert safe_urlopen(_PUBLIC_IP_URL, retries=2, backoff_base=1.0) is sentinel
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
    assert safe_urlopen(_PUBLIC_IP_URL, retries=2, backoff_base=1.0) is sentinel
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
    assert safe_urlopen(_PUBLIC_IP_URL, retries=2, backoff_base=0.0) is sentinel
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# _truncate_url
# ---------------------------------------------------------------------------


def test_truncate_url_clips_long_and_keeps_short() -> None:
    long_url = "https://example.com/" + "a" * 200
    clipped = _truncate_url(long_url, max_len=20)
    assert clipped.endswith("...")
    assert len(clipped) == 23  # 20 + "..."
    assert _truncate_url("https://x/", max_len=80) == "https://x/"
