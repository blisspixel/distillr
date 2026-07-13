"""Tests for the browser's exact-IP validating CONNECT proxy."""

from __future__ import annotations

import socket
import urllib.parse
from collections.abc import Iterator

import pytest

from distill.ingestors.sites import pinned_proxy
from distill.ingestors.sites.pinned_proxy import PinnedBrowserProxy, _parse_connect_authority


def _proxy_port(proxy_url: str) -> int:
    port = urllib.parse.urlsplit(proxy_url).port
    assert port is not None
    return port


def _connect_to_proxy(port: int) -> socket.socket:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(2)
    client.connect(("127.0.0.1", port))
    return client


@pytest.fixture
def socket_pair() -> Iterator[tuple[socket.socket, socket.socket]]:
    left, right = socket.socketpair()
    try:
        yield left, right
    finally:
        left.close()
        right.close()


def test_connect_tunnel_uses_the_validated_ip(monkeypatch, socket_pair) -> None:
    upstream, observer = socket_pair
    resolved: list[str] = []
    connected: list[tuple[tuple[str, int], float]] = []

    def resolve(url: str) -> str:
        resolved.append(url)
        return "93.184.216.34"

    def connect(address: tuple[str, int], *, timeout: float) -> socket.socket:
        connected.append((address, timeout))
        return upstream

    monkeypatch.setattr(pinned_proxy, "resolve_public_ip", resolve)
    monkeypatch.setattr(pinned_proxy.socket, "create_connection", connect)

    with (
        PinnedBrowserProxy() as proxy_url,
        _connect_to_proxy(_proxy_port(proxy_url)) as client,
    ):
        client.sendall(b"CONNECT rebind.example:443 HTTP/1.1\r\nHost: rebind.example:443\r\n\r\n")
        assert b"200 Connection Established" in client.recv(4096)
        client.sendall(b"browser bytes")
        assert observer.recv(4096) == b"browser bytes"
        observer.sendall(b"server bytes")
        assert client.recv(4096) == b"server bytes"

    assert resolved == ["https://rebind.example:443/"]
    assert connected == [(("93.184.216.34", 443), 10.0)]


def test_connect_tunnel_rejects_non_public_target(monkeypatch) -> None:
    attempted: list[object] = []
    monkeypatch.setattr(pinned_proxy, "resolve_public_ip", lambda url: None)
    monkeypatch.setattr(
        pinned_proxy.socket,
        "create_connection",
        lambda *args, **kwargs: attempted.append((args, kwargs)),
    )

    with (
        PinnedBrowserProxy() as proxy_url,
        _connect_to_proxy(_proxy_port(proxy_url)) as client,
    ):
        client.sendall(b"CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1:443\r\n\r\n")
        assert b"403 CONNECT target is not public" in client.recv(4096)

    assert attempted == []


@pytest.mark.parametrize(
    ("authority", "expected"),
    [
        ("example.com:8443", ("example.com", 8443)),
        ("[2001:4860:4860::8888]:443", ("2001:4860:4860::8888", 443)),
        ("user@example.com:443", None),
        ("example.com:not-a-port", None),
        ("example.com:0", None),
        ("", None),
    ],
)
def test_parse_connect_authority(authority, expected) -> None:
    assert _parse_connect_authority(authority) == expected


def test_proxy_rejects_plain_http_requests() -> None:
    with (
        PinnedBrowserProxy() as proxy_url,
        _connect_to_proxy(_proxy_port(proxy_url)) as client,
    ):
        client.sendall(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
        assert b"403 Plain HTTP browser requests are disabled" in client.recv(4096)


def test_connect_tunnel_reports_upstream_connection_failure(monkeypatch) -> None:
    monkeypatch.setattr(pinned_proxy, "resolve_public_ip", lambda url: "93.184.216.34")
    monkeypatch.setattr(
        pinned_proxy.socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unreachable")),
    )

    with (
        PinnedBrowserProxy() as proxy_url,
        _connect_to_proxy(_proxy_port(proxy_url)) as client,
    ):
        client.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
        assert b"502 Could not connect to validated target" in client.recv(4096)
