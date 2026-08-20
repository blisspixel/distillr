# pyright: strict
"""Fail closed if a replay sample tries to leave loopback."""

from __future__ import annotations

import socket
from collections.abc import Callable
from ipaddress import ip_address
from typing import Any, cast


def _is_loopback_host(value: object) -> bool:
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(value, str):
        return False
    host = value.strip().casefold().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _guarded[SocketResult](
    original: Callable[..., SocketResult],
    operation: str,
) -> Callable[..., SocketResult]:
    def guarded(sock: socket.socket, address: Any, *args: object, **kwargs: object) -> SocketResult:
        host: object = ""
        if isinstance(address, tuple) and address:
            host = cast(object, address[0])
        if isinstance(host, bytes | str) and not _is_loopback_host(host):
            raise OSError(
                f"public network disabled during workflow replay: {operation} to {host!r}"
            )
        return original(sock, address, *args, **kwargs)

    return guarded


def install_network_guard() -> None:
    socket.socket.connect = _guarded(socket.socket.connect, "connect")  # type: ignore[method-assign]
    socket.socket.connect_ex = _guarded(socket.socket.connect_ex, "connect_ex")  # type: ignore[method-assign]
