"""Regression tests for the default suite's zero-spend network boundary."""

from __future__ import annotations

import os
import socket

import pytest


@pytest.mark.parametrize("name", ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"])
def test_default_suite_does_not_inherit_forwarding_proxies(name: str) -> None:
    assert name not in os.environ
    assert name.lower() not in os.environ


def test_default_suite_also_removes_prefixed_proxy_variables() -> None:
    assert not any(name.upper().endswith("_PROXY") for name in os.environ)


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_default_suite_refuses_public_socket_connections(method: str) -> None:
    with socket.socket() as client, pytest.raises(OSError, match="public network disabled"):
        getattr(client, method)(("example.com", 443))


def test_default_suite_allows_loopback_socket_connections() -> None:
    with socket.socket() as server:
        server.settimeout(2)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.socket() as client:
            client.settimeout(2)
            client.connect(server.getsockname())
            connection, _address = server.accept()
            with connection:
                pass
