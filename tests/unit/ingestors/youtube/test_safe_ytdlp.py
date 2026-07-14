"""Security contracts for bounded, SSRF-safe yt-dlp acquisition."""

import contextlib
import io
import socket
import threading
import time
from unittest.mock import MagicMock

import pytest
import requests
from yt_dlp.networking._requests import RequestsHTTPAdapter, RequestsSession
from yt_dlp.networking.common import Response
from yt_dlp.networking.exceptions import RequestError

from distill.ingestors.youtube import safe_ytdlp as safe_mod
from distill.ingestors.youtube.safe_ytdlp import (
    RequestsRH,
    SafeYoutubeDL,
    _BoundedResponse,
    _OperationDeadline,
    _PinnedPublicHTTPSAdapter,
    _require_positive_limit,
    _ResponseByteBudget,
    _validated_public_https_target,
)


def _response(data: bytes, *, url: str = "https://www.youtube.com/data", length=True):
    headers = {"Content-Length": str(len(data))} if length else {}
    return Response(io.BytesIO(data), url, headers)


class _ExplodingRaw:
    """Raw response that records closes and fails if any body byte is read."""

    _original_response = None

    def __init__(self) -> None:
        self.closed = False
        self.read_calls = 0
        self.stream_calls = 0

    def read(self, *_args, **_kwargs):
        self.read_calls += 1
        raise AssertionError("response body was read")

    def stream(self, *_args, **_kwargs):
        self.stream_calls += 1
        raise AssertionError("response body was streamed")

    def close(self):
        self.closed = True

    def release_conn(self):
        return None


@pytest.mark.parametrize(
    ("payload", "limit", "expected"),
    ((b"1234", 5, b"1234"), (b"12345", 5, b"12345")),
)
def test_bounded_response_accepts_payloads_through_limit(payload, limit, expected):
    wrapped = _BoundedResponse(
        _response(payload),
        byte_limit=limit,
        budget=_ResponseByteBudget(limit),
        label="metadata",
    )

    assert wrapped.read() == expected


def test_bounded_response_rejects_declared_limit_plus_one_before_read():
    source = _response(b"123456")

    with pytest.raises(RequestError, match="metadata response exceeds"):
        _BoundedResponse(
            source,
            byte_limit=5,
            budget=_ResponseByteBudget(10),
            label="metadata",
        )

    assert source.closed is True


def test_bounded_response_rejects_chunked_limit_plus_one():
    wrapped = _BoundedResponse(
        _response(b"123456", length=False),
        byte_limit=5,
        budget=_ResponseByteBudget(10),
        label="metadata",
    )

    assert wrapped.read(3) == b"123"
    with pytest.raises(RequestError, match="metadata response exceeds"):
        wrapped.read(3)

    assert wrapped.closed is True


def test_bounded_response_never_issues_unbounded_source_read():
    class RecordingStream(io.BytesIO):
        def __init__(self, data):
            super().__init__(data)
            self.read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            return super().read(size)

    stream = RecordingStream(b"bounded metadata")
    source = Response(stream, "https://www.youtube.com/data", {})
    wrapped = _BoundedResponse(
        source,
        byte_limit=100,
        budget=_ResponseByteBudget(100),
        label="metadata",
    )

    assert wrapped.read() == b"bounded metadata"
    assert stream.read_sizes
    assert all(isinstance(size, int) and size > 0 for size in stream.read_sizes)


def test_response_budget_is_shared_across_missing_length_responses():
    budget = _ResponseByteBudget(6)
    first = _BoundedResponse(
        _response(b"1234", length=False),
        byte_limit=5,
        budget=budget,
        label="metadata",
    )
    second = _BoundedResponse(
        _response(b"567", length=False),
        byte_limit=5,
        budget=budget,
        label="metadata",
    )

    assert first.read() == b"1234"
    with pytest.raises(RequestError, match="total yt-dlp response budget"):
        second.read()


def test_operation_deadline_closes_a_trickling_response():
    released = threading.Event()
    closed = threading.Event()

    class SlowResponse(Response):
        def __init__(self):
            super().__init__(io.BytesIO(), "https://www.youtube.com/data", {})

        def read(self, amt=None):
            del amt
            assert released.wait(timeout=1)
            return b"x"

        def close(self):
            closed.set()
            released.set()
            super().close()

    deadline = _OperationDeadline(0.05)
    wrapped = _BoundedResponse(
        SlowResponse(),
        byte_limit=10,
        budget=_ResponseByteBudget(10),
        label="metadata",
        deadline=deadline,
    )
    try:
        with pytest.raises(RequestError, match="operation exceeds"):
            wrapped.read(1)
        assert closed.is_set()
    finally:
        wrapped.close()
        deadline.cancel()


def test_operation_deadline_cancel_closes_resources_and_stays_terminal():
    deadline = _OperationDeadline(10)
    first = _response(b"first")
    second = _response(b"second")
    deadline.register(first)

    deadline.cancel()

    assert first.closed is True
    with pytest.raises(RequestError, match="operation exceeds"):
        deadline.remaining()
    with pytest.raises(RequestError, match="operation exceeds"):
        deadline.register(second)
    assert second.closed is True


@pytest.mark.parametrize("value", (0, -1, True, float("nan"), "invalid"))
def test_operation_deadline_requires_positive_finite_timeout(value):
    with pytest.raises(ValueError, match="positive finite"):
        _OperationDeadline(value)


def test_operation_deadline_tolerates_resource_close_failures():
    class ExplodingResource:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            raise OSError("simulated close failure")

    expiring_resource = ExplodingResource()
    expiring = _OperationDeadline(10)
    expiring.register(expiring_resource)
    expiring._expire()
    expiring.cancel()
    assert expiring_resource.close_calls == 1

    cancelled_resource = ExplodingResource()
    cancelling = _OperationDeadline(10)
    cancelling.register(cancelled_resource)
    cancelling.cancel()
    assert cancelled_resource.close_calls == 1


def test_operation_deadline_register_handles_expiry_race(monkeypatch):
    deadline = _OperationDeadline(10)
    resource = MagicMock()
    monkeypatch.setattr(deadline, "remaining", lambda: 1.0)
    deadline._expired = True

    with pytest.raises(RequestError, match="operation exceeds"):
        deadline.register(resource)

    resource.close.assert_called_once_with()
    deadline.cancel()


def test_deadline_socket_binary_io_contract():
    class SocketStub:
        def __init__(self):
            self.timeout = 2.0
            self.sent = b""

        def gettimeout(self):
            return self.timeout

        def settimeout(self, value):
            self.timeout = value

        def sendall(self, data, *_args):
            self.sent += data

        def recv_into(self, buffer, *_args):
            buffer[:1] = b"x"
            return 1

        def fileno(self):
            return 7

    deadline = _OperationDeadline(10)
    socket_stub = SocketStub()
    wrapped = safe_mod._DeadlineSocket(socket_stub, deadline)
    try:
        wrapped.sendall(b"payload")
        assert socket_stub.sent == b"payload"

        with pytest.raises(ValueError, match="binary response reads only"):
            wrapped.makefile("w")

        raw = wrapped.makefile("rb", buffering=0)
        assert raw.fileno() == 7
        raw.close()
        with pytest.raises(ValueError, match="closed deadline socket"):
            raw.readinto(bytearray(1))

        buffered = wrapped.makefile("rb", buffering=32)
        buffered.close()
    finally:
        deadline.cancel()


def test_dns_resolution_rejects_when_worker_capacity_is_exhausted(monkeypatch):
    class ExhaustedSlots:
        def acquire(self, *, timeout):
            assert timeout > 0
            return False

    deadline = _OperationDeadline(10)
    monkeypatch.setattr(safe_mod, "_DNS_RESOLUTION_SLOTS", ExhaustedSlots())
    try:
        with pytest.raises(RequestError, match="operation exceeds"):
            safe_mod._resolve_public_ip_before_deadline("https://www.youtube.com", deadline)
    finally:
        deadline.cancel()


def test_dns_resolution_wraps_resolver_failure(monkeypatch):
    def fail_resolution(_url):
        raise OSError("simulated resolver failure")

    deadline = _OperationDeadline(10)
    monkeypatch.setattr(safe_mod, "resolve_public_ip", fail_resolution)
    try:
        with pytest.raises(RequestError, match="DNS resolution failed"):
            safe_mod._resolve_public_ip_before_deadline("https://www.youtube.com", deadline)
    finally:
        deadline.cancel()


def test_adapter_enforces_deadline_while_response_headers_trickle(monkeypatch):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    host, port = listener.getsockname()
    server_done = threading.Event()

    def serve() -> None:
        try:
            connection, _address = listener.accept()
            with connection:
                connection.recv(4096)
                payload = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
                for byte in payload:
                    connection.sendall(bytes((byte,)))
                    time.sleep(0.02)
        except OSError:
            pass
        finally:
            listener.close()
            server_done.set()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp._validated_public_https_target",
        lambda _url, _deadline=None: (host, host),
    )
    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.pin_host_to_ip",
        lambda _host, _ip, **_kwargs: contextlib.nullcontext(),
    )
    deadline = _OperationDeadline(0.1)
    adapter = _PinnedPublicHTTPSAdapter(operation_deadline=deadline)
    request = requests.Request("GET", f"http://{host}:{port}/slow").prepare()
    started = time.monotonic()
    try:
        with pytest.raises((RequestError, requests.RequestException)):
            adapter.send(request, timeout=1, proxies={})
        assert time.monotonic() - started < 0.35
    finally:
        adapter.close()
        deadline.cancel()
        server_done.wait(timeout=1)


def test_adapter_enforces_deadline_during_dns_resolution(monkeypatch):
    release_resolver = threading.Event()

    def blocked_resolver(_url):
        release_resolver.wait(timeout=1)
        return "203.0.113.10"

    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.resolve_public_ip",
        blocked_resolver,
    )
    deadline = _OperationDeadline(0.05)
    adapter = _PinnedPublicHTTPSAdapter(operation_deadline=deadline)
    request = requests.Request("GET", "https://www.youtube.com/data").prepare()
    started = time.monotonic()
    try:
        with pytest.raises(RequestError, match="operation exceeds"):
            adapter.send(request, timeout=1, proxies={})
        assert time.monotonic() - started < 0.5
        assert not release_resolver.is_set()
    finally:
        release_resolver.set()
        adapter.close()
        deadline.cancel()


@pytest.mark.parametrize("value", (0, -1, True))
def test_response_budget_requires_a_positive_integer(value):
    with pytest.raises(ValueError, match="positive integer"):
        _require_positive_limit(value, label="test limit")


@pytest.mark.parametrize("url", (None, "", "https://www.youtube.com:bad/watch"))
def test_target_validation_rejects_missing_and_malformed_urls(url):
    with pytest.raises(RequestError, match="public HTTPS"):
        _validated_public_https_target(url)


def test_response_budget_rejects_direct_overconsumption():
    budget = _ResponseByteBudget(5)

    with pytest.raises(RequestError, match="total yt-dlp response budget"):
        budget.consume(6)

    assert budget.consumed == 0


def test_bounded_response_rejects_declared_total_budget_before_read():
    source = _response(b"123456")

    with pytest.raises(RequestError, match="total yt-dlp response budget"):
        _BoundedResponse(
            source,
            byte_limit=10,
            budget=_ResponseByteBudget(5),
            label="metadata",
        )

    assert source.closed is True


def test_bounded_response_zero_length_read_is_a_noop():
    wrapped = _BoundedResponse(
        _response(b"payload"),
        byte_limit=10,
        budget=_ResponseByteBudget(10),
        label="metadata",
    )

    assert wrapped.read(0) == b""
    assert wrapped.read() == b"payload"


@pytest.mark.parametrize(
    "url",
    (
        "http://www.youtube.com/watch?v=abc",
        "https://127.0.0.1/internal",
        "https://user:pass@www.youtube.com/watch?v=abc",
        "https://www.youtube.com:444/watch?v=abc",
    ),
)
def test_pinned_adapter_rejects_unsafe_request_hops(monkeypatch, url):
    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.resolve_public_ip",
        lambda _url: None,
    )
    adapter = _PinnedPublicHTTPSAdapter()
    request = requests.Request("GET", url).prepare()

    with pytest.raises(RequestError, match="public HTTPS"):
        adapter.send(request)


def test_pinned_adapter_connects_each_validated_request_to_selected_ip(monkeypatch):
    pins = []
    sends = []

    def fake_pin(host, ip):
        pins.append((host, ip))
        return contextlib.nullcontext()

    def fake_send(_self, request, *args, **kwargs):
        sends.append(request.url)
        return requests.Response()

    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.resolve_public_ip",
        lambda _url: "203.0.113.10",
    )
    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.pin_host_to_ip",
        fake_pin,
    )
    monkeypatch.setattr(RequestsHTTPAdapter, "send", fake_send)
    adapter = _PinnedPublicHTTPSAdapter()
    request = requests.Request("GET", "https://www.youtube.com/watch?v=abc").prepare()

    adapter.send(request)

    assert pins == [("www.youtube.com", "203.0.113.10")]
    assert sends == ["https://www.youtube.com/watch?v=abc"]


def test_pinned_adapter_rejects_internal_redirect_before_second_send(monkeypatch):
    sends = []
    redirect_raw = _ExplodingRaw()

    def fake_send(_self, request, *args, **kwargs):
        sends.append(request.url)
        response = requests.Response()
        response.status_code = 302
        response.url = request.url
        response.request = request
        response.headers["Location"] = "http://127.0.0.1:8080/admin"
        response.raw = redirect_raw
        return response

    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.resolve_public_ip",
        lambda url: "203.0.113.10" if url.startswith("https://www.youtube.com/") else None,
    )
    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.pin_host_to_ip",
        lambda _host, _ip: contextlib.nullcontext(),
    )
    monkeypatch.setattr(RequestsHTTPAdapter, "send", fake_send)
    session = RequestsSession()
    session.trust_env = False
    adapter = _PinnedPublicHTTPSAdapter()
    session.adapters.clear()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    with pytest.raises(RequestError, match="public HTTPS"):
        session.get(
            "https://www.youtube.com/watch?v=abc",
            allow_redirects=True,
        )

    assert sends == ["https://www.youtube.com/watch?v=abc"]
    assert redirect_raw.closed is True
    assert redirect_raw.read_calls == 0
    assert redirect_raw.stream_calls == 0


def test_pinned_adapter_rejects_encoded_response_before_body_read(monkeypatch):
    raw = _ExplodingRaw()

    def fake_send(_self, request, *args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response.headers["Content-Encoding"] = "gzip"
        response.raw = raw
        return response

    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.resolve_public_ip",
        lambda _url: "203.0.113.10",
    )
    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.pin_host_to_ip",
        lambda _host, _ip: contextlib.nullcontext(),
    )
    monkeypatch.setattr(RequestsHTTPAdapter, "send", fake_send)
    adapter = _PinnedPublicHTTPSAdapter()
    request = requests.Request("GET", "https://www.youtube.com/data").prepare()

    with pytest.raises(RequestError, match="content encoding"):
        adapter.send(request)

    assert raw.closed is True
    assert raw.read_calls == 0
    assert raw.stream_calls == 0


def test_pinned_adapter_rejects_nonempty_proxy_configuration(monkeypatch):
    monkeypatch.setattr(
        "distill.ingestors.youtube.safe_ytdlp.resolve_public_ip",
        lambda _url: "203.0.113.10",
    )
    adapter = _PinnedPublicHTTPSAdapter()
    request = requests.Request("GET", "https://www.youtube.com/watch?v=abc").prepare()

    with pytest.raises(RequestError, match="proxied"):
        adapter.send(request, proxies={"https": "http://proxy.example:8080"})


def test_request_handler_builds_environment_independent_pinned_session():
    cookiejar = MagicMock()
    handler = RequestsRH(logger=MagicMock())

    session = handler._create_instance(cookiejar)
    try:
        assert session.trust_env is False
        assert session.cookies is cookiejar
        assert isinstance(session.adapters["https://"], _PinnedPublicHTTPSAdapter)
        assert isinstance(session.adapters["http://"], _PinnedPublicHTTPSAdapter)
    finally:
        session.close()


def test_request_handler_forces_identity_content_encoding():
    handler = RequestsRH(logger=MagicMock())
    headers = {"Accept-Encoding": "gzip, deflate"}

    handler._prepare_headers(None, headers)

    assert headers["Accept-Encoding"] == "identity"


def test_safe_youtube_dl_uses_only_pinned_direct_requests():
    with SafeYoutubeDL(
        {"quiet": True},
        metadata_byte_limit=1_000,
        total_byte_limit=2_000,
    ) as ydl:
        assert ydl.params["proxy"] == ""
        assert set(ydl._request_director.handlers) == {"Requests"}
        assert isinstance(ydl._request_director.handlers["Requests"], RequestsRH)


@pytest.mark.parametrize(
    ("url", "content_type", "expected"),
    (
        ("https://r1.googlevideo.com/videoplayback", "audio/mp4", 10_000),
        ("https://r1.googlevideo.com/data", "application/json", 1_000),
        ("https://googlevideo.com.evil.example/media", "audio/mp4", 1_000),
    ),
)
def test_safe_youtube_dl_reserves_large_budget_only_for_google_media(url, content_type, expected):
    with SafeYoutubeDL(
        {"quiet": True},
        metadata_byte_limit=1_000,
        media_byte_limit=10_000,
        total_byte_limit=20_000,
    ) as ydl:
        response = Response(
            io.BytesIO(),
            url,
            {"Content-Type": content_type, "Content-Length": "0"},
        )

        assert ydl._response_byte_limit(response) == expected


def test_safe_youtube_dl_without_media_budget_uses_metadata_limit():
    with SafeYoutubeDL(
        {"quiet": True},
        metadata_byte_limit=1_000,
        total_byte_limit=2_000,
    ) as ydl:
        response = Response(
            io.BytesIO(),
            "https://r1.googlevideo.com/videoplayback",
            {"Content-Type": "video/mp4", "Content-Length": "0"},
        )

        assert ydl._response_byte_limit(response) == 1_000


def test_safe_youtube_dl_malformed_response_url_uses_metadata_limit():
    with SafeYoutubeDL(
        {"quiet": True},
        metadata_byte_limit=1_000,
        media_byte_limit=10_000,
        total_byte_limit=20_000,
    ) as ydl:
        response = Response(
            io.BytesIO(),
            "https://[malformed/video",
            {"Content-Type": "video/mp4", "Content-Length": "0"},
        )

        assert ydl._response_byte_limit(response) == 1_000


def test_safe_youtube_dl_urlopen_wraps_the_direct_response(monkeypatch):
    source = _response(b"metadata", length=False)
    monkeypatch.setattr("yt_dlp.YoutubeDL.urlopen", lambda _self, _req: source)

    with SafeYoutubeDL(
        {"quiet": True},
        metadata_byte_limit=1_000,
        total_byte_limit=2_000,
    ) as ydl:
        response = ydl.urlopen(object())

        assert isinstance(response, _BoundedResponse)
        assert response.read() == b"metadata"
