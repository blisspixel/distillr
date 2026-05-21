"""Tests for distill.ingestors.x.media."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from distill.ingestors.x.media import download_video


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.headers_seen: dict[str, str] | None = None
        self.url_seen: str | None = None

    def __enter__(self) -> _FakeStream:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def raise_for_status(self) -> None:
        pass

    def iter_bytes(self, chunk_size: int) -> list[bytes]:
        return self._chunks


def test_download_video_writes_chunks_and_creates_parent(tmp_path: Path) -> None:
    dest = tmp_path / "subdir" / "media.mp4"
    chunks = [b"abc", b"def", b"ghi"]

    def _fake_stream(method: str, url: str, **kwargs: Any) -> _FakeStream:
        stream = _FakeStream(chunks)
        stream.url_seen = url
        stream.headers_seen = kwargs.get("headers")
        return stream

    with patch("distill.ingestors.x.media.httpx.stream", side_effect=_fake_stream):
        out = download_video("https://video.twimg.com/test.mp4", dest)

    assert out == dest
    assert dest.exists()
    assert dest.read_bytes() == b"abcdefghi"
    assert dest.parent.exists()


def test_download_video_sends_referer_header(tmp_path: Path) -> None:
    dest = tmp_path / "media.mp4"
    captured: dict[str, Any] = {}

    def _fake_stream(method: str, url: str, **kwargs: Any) -> _FakeStream:
        captured["headers"] = kwargs.get("headers", {})
        return _FakeStream([b"x"])

    with patch("distill.ingestors.x.media.httpx.stream", side_effect=_fake_stream):
        download_video("https://video.twimg.com/test.mp4", dest)

    assert captured["headers"].get("Referer") == "https://platform.twitter.com/"
    assert "User-Agent" in captured["headers"]
