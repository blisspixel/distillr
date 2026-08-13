"""Regression tests for the default suite's zero-spend network boundary."""

from __future__ import annotations

import socket

import pytest


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
