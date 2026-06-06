"""Tests for distill.ingestors.net SSRF guards."""

from __future__ import annotations

import socket

import pytest

from distill.ingestors.net import (
    is_public_web_url,
    pin_host_to_ip,
    resolve_public_ip,
    safe_urlopen,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",  # loopback
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://localhost/",  # loopback name
        "https://10.0.0.5/",  # RFC1918
        "https://192.168.1.1/",  # RFC1918
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
