# pyright: strict
"""Loopback CONNECT proxy that pins browser traffic to validated public IPs."""

from __future__ import annotations

import select
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import cast

from distill.ingestors.net import resolve_public_ip

_CONNECT_TIMEOUT_SECONDS = 10.0
_TUNNEL_IDLE_TIMEOUT_SECONDS = 45.0
_TUNNEL_WRITE_TIMEOUT_SECONDS = 10.0
_MAX_CONNECTIONS = 32
_BUFFER_BYTES = 64 * 1024


def _parse_connect_authority(authority: str) -> tuple[str, int] | None:
    """Parse a CONNECT authority without accepting credentials or URL syntax."""

    try:
        parsed = urllib.parse.urlsplit(f"//{authority}")
        port = 443 if parsed.port is None else parsed.port
    except ValueError:
        return None
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not 1 <= port <= 65535
    ):
        return None
    return parsed.hostname, port


def _validation_url(host: str, port: int) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    return f"https://{rendered_host}:{port}/"


def _relay(left: socket.socket, right: socket.socket) -> None:
    """Relay one TLS tunnel until either endpoint closes or becomes idle."""

    left.settimeout(_TUNNEL_WRITE_TIMEOUT_SECONDS)
    right.settimeout(_TUNNEL_WRITE_TIMEOUT_SECONDS)
    peers = {left: right, right: left}
    deadline = time.monotonic() + _TUNNEL_IDLE_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        readable, _, _ = select.select(tuple(peers), (), (), min(1.0, remaining))
        if not readable:
            continue
        for source in readable:
            try:
                data = source.recv(_BUFFER_BYTES)
            except (BlockingIOError, InterruptedError):
                continue
            if not data:
                return
            peers[source].sendall(data)
            deadline = time.monotonic() + _TUNNEL_IDLE_TIMEOUT_SECONDS


class _PinnedProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = _MAX_CONNECTIONS

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _PinnedProxyHandler)
        self.connection_slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)


class _PinnedProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DistillPinnedProxy"
    sys_version = ""

    def do_CONNECT(self) -> None:
        server = cast(_PinnedProxyServer, self.server)
        if not server.connection_slots.acquire(blocking=False):
            self.send_error(503, "Browser proxy connection limit reached")
            return
        try:
            self._open_tunnel()
        finally:
            server.connection_slots.release()

    def _open_tunnel(self) -> None:
        target = _parse_connect_authority(self.path)
        if target is None:
            self.send_error(400, "Invalid CONNECT target")
            return
        host, port = target
        pinned_ip = resolve_public_ip(_validation_url(host, port))
        if pinned_ip is None:
            self.send_error(403, "CONNECT target is not public")
            return
        try:
            upstream = socket.create_connection(
                (pinned_ip, port),
                timeout=_CONNECT_TIMEOUT_SECONDS,
            )
        except OSError:
            self.send_error(502, "Could not connect to validated target")
            return
        self.send_response(200, "Connection Established")
        self.end_headers()
        self.close_connection = True
        try:
            with upstream:
                _relay(self.connection, upstream)
        except OSError:
            return

    def do_GET(self) -> None:
        self.send_error(403, "Plain HTTP browser requests are disabled")

    do_HEAD = do_GET
    do_POST = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET
    do_OPTIONS = do_GET
    do_PATCH = do_GET

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return None


class PinnedBrowserProxy:
    """Manage an ephemeral loopback proxy for one browser crawl."""

    def __init__(self) -> None:
        self._server = _PinnedProxyServer()
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="distill-pinned-browser-proxy",
            daemon=True,
        )

    def __enter__(self) -> str:
        self._thread.start()
        port = int(self._server.server_address[1])
        return f"http://127.0.0.1:{port}"

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
