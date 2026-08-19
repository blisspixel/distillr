"""SSRF-safe, byte-bounded yt-dlp transport for YouTube ingestion."""

from __future__ import annotations

import contextlib
import io
import math
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping
from queue import Empty, Queue
from typing import Any

import requests
import yt_dlp
from requests.structures import CaseInsensitiveDict
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.util import Retry
from yt_dlp.networking._requests import (
    RequestsHTTPAdapter,
    RequestsSession,
)
from yt_dlp.networking._requests import (
    RequestsRH as _YtDlpRequestsRH,
)
from yt_dlp.networking.common import Response
from yt_dlp.networking.exceptions import RequestError

from distill.ingestors.net import (
    _apply_socket_timeout,
    _is_windows_not_a_socket,
    pin_host_to_ip,
    resolve_public_ip,
)
from distill.ingestors.youtube._yt_dlp_boundary import ydl_params
from distill.parsing import parse_ascii_uint

YTDLP_METADATA_RESPONSE_BYTES = 20_000_000
YTDLP_METADATA_TOTAL_BYTES = 64_000_000
YTDLP_OPERATION_TIMEOUT_SECONDS = 300.0

_READ_CHUNK_BYTES = 64 * 1024
_MEDIA_CONTENT_TYPES = frozenset({"application/octet-stream"})
_DNS_RESOLUTION_SLOTS = threading.BoundedSemaphore(4)


def _require_positive_limit(value: int, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_positive_timeout(value: float, *, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{label} must be a positive finite number")
    return float(value)


class _OperationDeadline:
    """Close active responses when one yt-dlp operation exceeds its deadline."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.timeout_seconds = _require_positive_timeout(
            timeout_seconds,
            label="operation timeout",
        )
        self._clock = time.monotonic if clock is None else clock
        self._expires_at = self._clock() + self.timeout_seconds
        self._lock = threading.Lock()
        self._resources: dict[int, Any] = {}
        self._expired = False
        self._timer = threading.Timer(self.timeout_seconds, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _expire(self) -> None:
        with self._lock:
            self._expired = True
            resources = list(self._resources.values())
            self._resources.clear()
        for resource in resources:
            try:
                resource.close()
            except Exception:
                continue

    def remaining(self) -> float:
        remaining = self._expires_at - self._clock()
        if remaining <= 0:
            self._expire()
            raise RequestError(
                f"yt-dlp operation exceeds the {self.timeout_seconds:g}-second deadline"
            )
        with self._lock:
            expired = self._expired
        if expired:
            raise RequestError(
                f"yt-dlp operation exceeds the {self.timeout_seconds:g}-second deadline"
            )
        return remaining

    def register(self, resource: Any) -> None:
        try:
            self.remaining()
        except RequestError:
            resource.close()
            raise
        with self._lock:
            if not self._expired:
                self._resources[id(resource)] = resource
                return
        resource.close()
        raise RequestError(f"yt-dlp operation exceeds the {self.timeout_seconds:g}-second deadline")

    def unregister(self, resource: Any) -> None:
        with self._lock:
            self._resources.pop(id(resource), None)

    def cancel(self) -> None:
        self._timer.cancel()
        with self._lock:
            self._expired = True
            resources = list(self._resources.values())
            self._resources.clear()
        for resource in resources:
            try:
                resource.close()
            except Exception:
                continue


class _DeadlineSocketIO(io.RawIOBase):
    """Unbuffered socket reader that reapplies an absolute deadline per receive."""

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
        self._deadline_socket._release_view()
        super().close()


class _DeadlineSocket:
    """Socket proxy whose every blocking operation is capped by one deadline."""

    def __init__(self, sock: Any, deadline: _OperationDeadline) -> None:
        self._socket = sock
        self._deadline = deadline
        self._live_views = 0
        self._closed = False

    def _cap_timeout(self, requested: float | None) -> None:
        remaining = self._deadline.remaining()
        effective = remaining if requested is None else min(float(requested), remaining)
        _apply_socket_timeout(self._socket, effective)

    def settimeout(self, value: float | None) -> None:
        self._cap_timeout(value)

    def recv_into(self, buffer: Any, *args: Any) -> int:
        current = self._socket.gettimeout()
        self._cap_timeout(current)
        try:
            received = self._socket.recv_into(buffer, *args)
        except OSError as exc:
            if _is_windows_not_a_socket(exc):
                return 0
            raise
        self._deadline.remaining()
        return int(received)

    def sendall(self, data: Any, *args: Any) -> None:
        current = self._socket.gettimeout()
        self._cap_timeout(current)
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
        self._live_views += 1
        raw = _DeadlineSocketIO(self)
        if buffering == 0:
            return raw
        if buffering in {None, -1}:
            buffer_size = io.DEFAULT_BUFFER_SIZE
        else:
            assert buffering is not None
            buffer_size = buffering
        return io.BufferedReader(raw, buffer_size)

    def _close_inner(self) -> None:
        close = getattr(self._socket, "close", None)
        if callable(close):
            with contextlib.suppress(OSError):
                close()

    def _release_view(self) -> None:
        if self._live_views > 0:
            self._live_views -= 1
        if self._live_views == 0:
            self._closed = True
            self._close_inner()

    def close(self) -> None:
        self._closed = True
        if self._live_views == 0:
            self._close_inner()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._socket, name)


def _resolve_public_ip_before_deadline(
    url: str,
    deadline: _OperationDeadline | None,
) -> str | None:
    """Resolve in a bounded daemon worker so DNS cannot overrun the operation."""

    if deadline is None:
        return resolve_public_ip(url)
    if not _DNS_RESOLUTION_SLOTS.acquire(timeout=deadline.remaining()):
        raise RequestError(
            f"yt-dlp operation exceeds the {deadline.timeout_seconds:g}-second deadline"
        )

    outcomes: Queue[str | None | Exception] = Queue(maxsize=1)

    def resolve() -> None:
        try:
            outcomes.put(resolve_public_ip(url))
        except Exception as exc:
            outcomes.put(exc)
        finally:
            _DNS_RESOLUTION_SLOTS.release()

    threading.Thread(target=resolve, daemon=True, name="distill-ytdlp-dns").start()
    try:
        outcome = outcomes.get(timeout=deadline.remaining())
    except Empty as exc:
        raise RequestError(
            f"yt-dlp operation exceeds the {deadline.timeout_seconds:g}-second deadline",
            cause=exc,
        ) from exc
    deadline.remaining()
    if isinstance(outcome, Exception):
        raise RequestError("yt-dlp DNS resolution failed", cause=outcome) from outcome
    return outcome


def _validated_public_https_target(
    url: object,
    deadline: _OperationDeadline | None = None,
) -> tuple[str, str]:
    if not isinstance(url, str) or not url:
        raise RequestError("refusing yt-dlp request outside public HTTPS")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise RequestError("refusing yt-dlp request outside public HTTPS", cause=exc) from exc
    host = parsed.hostname or ""
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise RequestError("refusing yt-dlp request outside public HTTPS")
    pinned_ip = _resolve_public_ip_before_deadline(url, deadline)
    if pinned_ip is None:
        raise RequestError("refusing yt-dlp request outside public HTTPS")
    return host, pinned_ip


class _PinnedPublicHTTPSAdapter(RequestsHTTPAdapter):
    """Validate and pin every prepared request, including redirect hops."""

    def __init__(
        self,
        *args: Any,
        operation_deadline: _OperationDeadline | None = None,
        **kwargs: Any,
    ) -> None:
        self._operation_deadline = operation_deadline
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        super().init_poolmanager(*args, **kwargs)
        deadline = self._operation_deadline
        if deadline is None:
            return

        class DeadlineHTTPConnection(HTTPConnection):
            def connect(self) -> None:
                deadline.register(self)
                try:
                    super().connect()
                    deadline.remaining()
                finally:
                    deadline.unregister(self)

            def getresponse(self) -> Any:
                if self.sock is not None and not isinstance(self.sock, _DeadlineSocket):
                    self.sock = _DeadlineSocket(self.sock, deadline)  # type: ignore[assignment]
                deadline.register(self)
                try:
                    return super().getresponse()
                finally:
                    deadline.unregister(self)

        class DeadlineHTTPSConnection(HTTPSConnection):
            def connect(self) -> None:
                deadline.register(self)
                try:
                    super().connect()
                    deadline.remaining()
                finally:
                    deadline.unregister(self)

            def getresponse(self) -> Any:
                if self.sock is not None and not isinstance(self.sock, _DeadlineSocket):
                    self.sock = _DeadlineSocket(self.sock, deadline)  # type: ignore[assignment]
                deadline.register(self)
                try:
                    return super().getresponse()
                finally:
                    deadline.unregister(self)

        class DeadlineHTTPConnectionPool(HTTPConnectionPool):
            ConnectionCls = DeadlineHTTPConnection  # pyright: ignore[reportAssignmentType]

        class DeadlineHTTPSConnectionPool(HTTPSConnectionPool):
            ConnectionCls = DeadlineHTTPSConnection  # pyright: ignore[reportAssignmentType]

        manager: Any = self.poolmanager
        pool_classes = dict(manager.pool_classes_by_scheme)
        pool_classes["http"] = DeadlineHTTPConnectionPool
        pool_classes["https"] = DeadlineHTTPSConnectionPool
        manager.pool_classes_by_scheme = pool_classes

    def send(
        self,
        request: Any,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        if isinstance(proxies, Mapping) and any(value for value in proxies.values()):
            raise RequestError("refusing proxied yt-dlp request")
        request.headers["Accept-Encoding"] = "identity"
        if self._operation_deadline is not None:
            remaining = self._operation_deadline.remaining()
            if timeout is None:
                timeout = remaining
            elif isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
                timeout = min(float(timeout), remaining)
        deadline = self._operation_deadline
        host, pinned_ip = _validated_public_https_target(
            getattr(request, "url", None),
            deadline,
        )
        pin_timeout = deadline.remaining() if deadline is not None else None
        pin_scope = (
            pin_host_to_ip(host, pinned_ip)
            if pin_timeout is None
            else pin_host_to_ip(host, pinned_ip, timeout_seconds=pin_timeout)
        )
        try:
            with pin_scope:
                response = super().send(
                    request,
                    stream=stream,
                    timeout=timeout,
                    verify=verify,
                    cert=cert,
                    proxies=proxies,
                )
        except TimeoutError as exc:
            raise RequestError(
                "yt-dlp operation exceeded its deadline while acquiring the DNS pin lock",
                cause=exc,
            ) from exc
        if response.is_redirect:
            response.close()
            response._content = b""
            response._content_consumed = True
            return response
        content_encoding = response.headers.get("Content-Encoding", "").strip().casefold()
        if content_encoding not in {"", "identity"}:
            response.close()
            raise RequestError(f"refusing yt-dlp response content encoding: {content_encoding}")
        if self._operation_deadline is not None:
            try:
                self._operation_deadline.remaining()
            except RequestError:
                response.close()
                raise
        return response


class RequestsRH(_YtDlpRequestsRH):
    """yt-dlp requests handler whose adapter enforces the public-web boundary."""

    def __init__(
        self,
        *args: Any,
        operation_deadline: _OperationDeadline | None = None,
        **kwargs: Any,
    ) -> None:
        self._operation_deadline = operation_deadline
        super().__init__(*args, **kwargs)

    def _prepare_headers(self, request: Any, headers: Any) -> None:
        super()._prepare_headers(request, headers)
        headers["Accept-Encoding"] = "identity"

    def _send(self, request: Any) -> Any:
        return super()._send(request)

    def _create_instance(self, cookiejar: Any, legacy_ssl_support: Any = None) -> RequestsSession:
        session = RequestsSession()
        adapter = _PinnedPublicHTTPSAdapter(
            ssl_context=self._make_sslcontext(legacy_ssl_support=legacy_ssl_support),
            source_address=self.source_address,
            max_retries=Retry(False),
            operation_deadline=self._operation_deadline,
        )
        session.adapters.clear()
        session.headers = CaseInsensitiveDict()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.cookies = cookiejar
        session.trust_env = False
        return session


class _ResponseByteBudget:
    """Track decoded response bytes across one yt-dlp operation."""

    def __init__(self, byte_limit: int) -> None:
        self.byte_limit = _require_positive_limit(byte_limit, label="total byte limit")
        self.consumed = 0

    @property
    def remaining(self) -> int:
        return self.byte_limit - self.consumed

    def consume(self, amount: int) -> None:
        if amount > self.remaining:
            raise RequestError(
                f"total yt-dlp response budget exceeds the {self.byte_limit:,}-byte cap"
            )
        self.consumed += amount


class _BoundedResponse(Response):
    """Response wrapper that never performs an unbounded underlying read."""

    def __init__(
        self,
        response: Response,
        *,
        byte_limit: int,
        budget: _ResponseByteBudget,
        label: str,
        deadline: _OperationDeadline | None = None,
    ) -> None:
        self._response = response
        self._byte_limit = _require_positive_limit(byte_limit, label=f"{label} byte limit")
        self._budget = budget
        self._label = label
        self._consumed = 0
        self._deadline = deadline
        self._deadline_registered = False
        super().__init__(
            response,
            response.url,
            dict(response.headers.items()),
            status=response.status,
            reason=response.reason,
            extensions=dict(response.extensions),
        )
        declared_header = response.get_header("Content-Length", "")
        declared_length = (
            parse_ascii_uint(declared_header) if isinstance(declared_header, str) else None
        )
        if declared_length is not None:
            if declared_length > self._byte_limit:
                self._fail_response_limit()
            if declared_length > self._budget.remaining:
                self._fail_total_limit()
        if self._deadline is not None:
            self._deadline.register(self._response)
            self._deadline_registered = True

    def close(self) -> None:
        if self._deadline is not None and self._deadline_registered:
            self._deadline.unregister(self._response)
            self._deadline_registered = False
        super().close()

    def _require_active(self) -> None:
        if self._deadline is not None:
            self._deadline.remaining()

    def _fail_response_limit(self) -> None:
        self.close()
        raise RequestError(f"{self._label} response exceeds the {self._byte_limit:,}-byte cap")

    def _fail_total_limit(self) -> None:
        self.close()
        raise RequestError(
            f"total yt-dlp response budget exceeds the {self._budget.byte_limit:,}-byte cap"
        )

    def _record(self, data: bytes) -> bytes:
        self._require_active()
        if len(data) > self._byte_limit - self._consumed:
            self._fail_response_limit()
        if len(data) > self._budget.remaining:
            self._fail_total_limit()
        self._consumed += len(data)
        self._budget.consume(len(data))
        return data

    def _read_all(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            remaining = min(
                self._byte_limit - self._consumed,
                self._budget.remaining,
            )
            chunk = self._response.read(min(_READ_CHUNK_BYTES, remaining + 1))
            self._require_active()
            if not chunk:
                break
            chunks.append(self._record(chunk))
        return b"".join(chunks)

    def read(self, amt: int | None = None) -> bytes:
        if amt == 0:
            return b""
        if amt is None or amt < 0:
            return self._read_all()
        remaining = min(
            self._byte_limit - self._consumed,
            self._budget.remaining,
        )
        self._require_active()
        data = self._response.read(min(amt, remaining + 1))
        return self._record(data)


class SafeYoutubeDL(yt_dlp.YoutubeDL):
    """YoutubeDL variant with one direct pinned transport and response budgets."""

    def __init__(
        self,
        params: Mapping[str, object] | None = None,
        *,
        metadata_byte_limit: int,
        total_byte_limit: int,
        media_byte_limit: int | None = None,
        operation_timeout_seconds: float = YTDLP_OPERATION_TIMEOUT_SECONDS,
    ) -> None:
        self._metadata_byte_limit = _require_positive_limit(
            metadata_byte_limit,
            label="metadata byte limit",
        )
        self._media_byte_limit = (
            _require_positive_limit(media_byte_limit, label="media byte limit")
            if media_byte_limit is not None
            else None
        )
        self._response_budget = _ResponseByteBudget(total_byte_limit)
        self._operation_deadline = _OperationDeadline(operation_timeout_seconds)
        safe_params = dict(params or {})
        safe_params["proxy"] = ""
        try:
            super().__init__(ydl_params(safe_params))
        except BaseException:
            self._operation_deadline.cancel()
            raise

    def build_request_director(self, handlers: Any, preferences: Any = None) -> Any:
        del handlers

        def request_handler(**kwargs: Any) -> RequestsRH:
            return RequestsRH(
                operation_deadline=self._operation_deadline,
                **kwargs,
            )

        safe_handlers: Any = (request_handler,)
        return super().build_request_director(safe_handlers, preferences)

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._operation_deadline.cancel()

    def _response_byte_limit(self, response: Response) -> int:
        if self._media_byte_limit is None:
            return self._metadata_byte_limit
        try:
            host = (urllib.parse.urlsplit(response.url).hostname or "").casefold().rstrip(".")
        except ValueError:
            return self._metadata_byte_limit
        content_type = (response.get_header("Content-Type", "") or "").partition(";")[0]
        normalized_type = content_type.strip().casefold()
        is_google_media_host = host == "googlevideo.com" or host.endswith(".googlevideo.com")
        is_media_type = normalized_type.startswith(("audio/", "video/")) or (
            normalized_type in _MEDIA_CONTENT_TYPES
        )
        if is_google_media_host and is_media_type:
            return self._media_byte_limit
        return self._metadata_byte_limit

    def urlopen(self, req: Any) -> _BoundedResponse:
        response = super().urlopen(req)
        byte_limit = self._response_byte_limit(response)
        label = "media" if byte_limit == self._media_byte_limit else "metadata"
        return _BoundedResponse(
            response,
            byte_limit=byte_limit,
            budget=self._response_budget,
            label=label,
            deadline=self._operation_deadline,
        )
