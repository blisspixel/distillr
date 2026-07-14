"""Tests for distill.ingestors.x.media."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from distill.ingestors.x import media
from distill.ingestors.x.media import download_video


class _FakeStream:
    def __init__(self, chunks: list[bytes], *, redirect_to: str = "") -> None:
        self._chunks = chunks
        self.is_redirect = bool(redirect_to)
        self.headers: dict[str, str] = {"location": redirect_to} if redirect_to else {}

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int) -> list[bytes]:
        return self._chunks


def test_download_video_writes_chunks_and_creates_parent(tmp_path: Path) -> None:
    dest = tmp_path / "subdir" / "media.mp4"
    chunks = [b"abc", b"def", b"ghi"]

    def _fake_stream(method: str, url: str, **kwargs: Any) -> _FakeStream:
        return _FakeStream(chunks)

    with (
        patch("distill.ingestors.x.media.httpx.stream", side_effect=_fake_stream),
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value="93.184.216.34"),
    ):
        out = download_video("https://video.twimg.com/test.mp4", dest)

    assert out == dest
    assert dest.read_bytes() == b"abcdefghi"
    assert dest.parent.exists()


def test_download_video_sends_referer_header(tmp_path: Path) -> None:
    dest = tmp_path / "media.mp4"
    captured: dict[str, Any] = {}

    def _fake_stream(method: str, url: str, **kwargs: Any) -> _FakeStream:
        captured["headers"] = kwargs.get("headers", {})
        captured["trust_env"] = kwargs.get("trust_env")
        return _FakeStream([b"x"])

    with (
        patch("distill.ingestors.x.media.httpx.stream", side_effect=_fake_stream),
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value="93.184.216.34"),
    ):
        download_video("https://video.twimg.com/test.mp4", dest)

    assert captured["headers"].get("Referer") == "https://platform.twitter.com/"
    assert "User-Agent" in captured["headers"]
    assert captured["trust_env"] is False


def test_download_video_pins_connection_to_resolved_ip(tmp_path: Path) -> None:
    """The connection is pinned to the validated public IP -- a DNS rebind between
    the is_public_web_url check and httpx's connect can't flip it to an internal
    address. Regression guard for the missing pin the harden pass added."""
    import contextlib

    pinned: dict[str, str] = {}

    @contextlib.contextmanager
    def _fake_pin(host: str, ip: str):
        pinned["host"], pinned["ip"] = host, ip
        yield

    with (
        patch(
            "distill.ingestors.x.media.httpx.stream",
            side_effect=lambda *a, **k: _FakeStream([b"x"]),
        ),
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value="93.184.216.34"),
        patch("distill.ingestors.x.media.pin_host_to_ip", side_effect=_fake_pin),
    ):
        download_video("https://video.twimg.com/test.mp4", tmp_path / "m.mp4")

    assert pinned == {"host": "video.twimg.com", "ip": "93.184.216.34"}


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/x.mp4",  # cloud metadata
        "http://127.0.0.1/x.mp4",  # loopback
        "https://evil.example.com/x.mp4",  # arbitrary non-twimg host
        "file:///etc/passwd",  # non-http scheme
    ],
)
def test_download_video_rejects_non_twimg_url(tmp_path: Path, url: str) -> None:
    # SSRF guard: the video URL comes from attacker-influenced syndication JSON,
    # so anything not on *.twimg.com must be refused without any fetch. (Host
    # pinning short-circuits before any DNS lookup.)
    with patch("distill.ingestors.x.media.httpx.stream") as mock_stream:
        with pytest.raises(ValueError, match="refusing non-allowlisted"):
            download_video(url, tmp_path / "media.mp4")
        mock_stream.assert_not_called()


def test_download_video_rejects_malformed_url_without_fetch(tmp_path: Path) -> None:
    with patch("distill.ingestors.x.media.httpx.stream") as mock_stream:
        with pytest.raises(ValueError, match="refusing non-allowlisted"):
            download_video("https://[::1/video.mp4", tmp_path / "media.mp4")
        mock_stream.assert_not_called()


def test_download_video_rejects_non_public_resolved_ip(tmp_path: Path) -> None:
    with (
        patch("distill.ingestors.x.media.httpx.stream") as mock_stream,
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value=None),
    ):
        with pytest.raises(ValueError, match="refusing non-public"):
            download_video("https://video.twimg.com/test.mp4", tmp_path / "media.mp4")
        mock_stream.assert_not_called()


def test_download_video_follows_allowed_redirect(tmp_path: Path) -> None:
    dest = tmp_path / "media.mp4"
    streams = [_FakeStream([], redirect_to="/next.mp4"), _FakeStream([b"ok"])]
    requested: list[str] = []

    def _fake_stream(method: str, url: str, **kwargs: Any) -> _FakeStream:
        requested.append(url)
        return streams.pop(0)

    with (
        patch("distill.ingestors.x.media.httpx.stream", side_effect=_fake_stream),
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value="93.184.216.34"),
    ):
        out = download_video("https://video.twimg.com/start.mp4", dest)

    assert out == dest
    assert requested == [
        "https://video.twimg.com/start.mp4",
        "https://video.twimg.com/next.mp4",
    ]
    assert dest.read_bytes() == b"ok"


def test_download_video_rejects_https_redirect_downgrade(tmp_path: Path) -> None:
    requested: list[str] = []

    def _fake_stream(method: str, url: str, **kwargs: Any) -> _FakeStream:
        requested.append(url)
        return _FakeStream([], redirect_to="http://video.twimg.com/cleartext.mp4")

    with (
        patch("distill.ingestors.x.media.httpx.stream", side_effect=_fake_stream),
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value="93.184.216.34"),
        pytest.raises(ValueError, match="refusing non-allowlisted"),
    ):
        download_video("https://video.twimg.com/start.mp4", tmp_path / "media.mp4")

    assert requested == ["https://video.twimg.com/start.mp4"]


def test_download_video_rejects_too_many_redirects(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(media, "_MAX_REDIRECTS", 1)

    with (
        patch(
            "distill.ingestors.x.media.httpx.stream",
            side_effect=lambda *a, **k: _FakeStream([], redirect_to="/again.mp4"),
        ),
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value="93.184.216.34"),
        pytest.raises(ValueError, match="too many redirects"),
    ):
        download_video("https://video.twimg.com/start.mp4", tmp_path / "media.mp4")


def test_download_video_enforces_size_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(media, "_MAX_VIDEO_BYTES", 4)
    dest = tmp_path / "media.mp4"
    with (
        patch(
            "distill.ingestors.x.media.httpx.stream",
            side_effect=lambda *a, **k: _FakeStream([b"aa", b"bb", b"cc"]),
        ),
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value="93.184.216.34"),
        pytest.raises(ValueError, match="exceeds"),
    ):
        download_video("https://video.twimg.com/big.mp4", dest)

    assert not dest.exists()
    assert list(tmp_path.glob(".media.mp4.*.tmp")) == []


def test_download_video_cleans_partial_file_and_subsequent_retry_succeeds(tmp_path: Path) -> None:
    dest = tmp_path / "media.mp4"
    attempts = 0

    class FailingStream(_FakeStream):
        def iter_bytes(self, chunk_size: int):
            yield b"partial"
            raise httpx.ReadTimeout("stream stopped")

    def _fake_stream(method: str, url: str, **kwargs: Any) -> _FakeStream:
        nonlocal attempts
        attempts += 1
        return FailingStream([]) if attempts == 1 else _FakeStream([b"complete"])

    with (
        patch("distill.ingestors.x.media.httpx.stream", side_effect=_fake_stream),
        patch("distill.ingestors.x.media.is_public_web_url", return_value=True),
        patch("distill.ingestors.x.media.resolve_public_ip", return_value="93.184.216.34"),
    ):
        with pytest.raises(httpx.ReadTimeout):
            download_video("https://video.twimg.com/test.mp4", dest)
        assert not dest.exists()
        assert list(tmp_path.glob(".media.mp4.*.tmp")) == []

        assert download_video("https://video.twimg.com/test.mp4", dest) == dest

    assert dest.read_bytes() == b"complete"
