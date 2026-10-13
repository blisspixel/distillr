"""Exact-page HTTPS fallback stays inside the existing byte and text caps."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from distill.ingestors.sites import http_static
from distill.ingestors.sites.http_static import StaticFetchError, fetch_static_page


class _Response:
    def __init__(self, body: bytes, *, charset: str | None = "utf-8", final_url: str = "") -> None:
        self._body = body
        self._charset = charset
        self._final_url = final_url
        self.closed = False
        self.headers = SimpleNamespace(get_content_charset=lambda: charset)

    def read(self, amount: int) -> bytes:
        return self._body[:amount]

    def geturl(self) -> str:
        return self._final_url

    def close(self) -> None:
        self.closed = True


def test_fetch_static_page_marks_http_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    html = b"<html><head><title>  Hello <b>there</b> </title></head><body><p>Body text</p></body>"
    response = _Response(html, final_url="https://example.com/final")
    monkeypatch.setattr(http_static, "safe_urlopen", lambda url, timeout, retries: response)

    page = fetch_static_page("https://example.com/start")

    assert response.closed is True
    assert page.capture == "http-static"
    assert page.title == "Hello there"
    assert "Body text" in page.text
    assert page.final_url == "https://example.com/final"
    assert page.truncation_reasons == []
    assert page.metadata()["capture"] == "http-static"


def test_non_https_final_url_keeps_the_requested_url(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(b"<html><body>plain</body>", final_url="http://example.com/other")
    monkeypatch.setattr(http_static, "safe_urlopen", lambda url, timeout, retries: response)

    page = fetch_static_page("https://example.com/start")

    assert page.final_url == "https://example.com/start"
    assert page.title == "https://example.com/start"


def test_byte_and_text_caps_use_body_text_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_static, "_MAX_RESPONSE_BYTES", 8)
    monkeypatch.setattr(http_static, "_MAX_TEXT_CHARS", 5)
    response = _Response(b"<p>0123456789</p>")
    monkeypatch.setattr(http_static, "safe_urlopen", lambda url, timeout, retries: response)

    page = fetch_static_page("https://example.com/long")

    assert page.truncation_reasons == ["body_text"]
    assert len(page.text) <= 5


def test_fetch_errors_are_static_fetch_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(url: str, timeout: int, retries: int) -> object:
        raise TimeoutError("slow")

    monkeypatch.setattr(http_static, "safe_urlopen", fail)
    with pytest.raises(StaticFetchError, match="slow"):
        fetch_static_page("https://example.com/down")

    class NoBody:
        def close(self) -> None:
            return None

    monkeypatch.setattr(http_static, "safe_urlopen", lambda url, timeout, retries: NoBody())
    with pytest.raises(StaticFetchError, match="no body"):
        fetch_static_page("https://example.com/down")

    class TextBody:
        def read(self, amount: int) -> str:
            return "nope"

        def close(self) -> None:
            return None

    monkeypatch.setattr(http_static, "safe_urlopen", lambda url, timeout, retries: TextBody())
    with pytest.raises(StaticFetchError, match="not bytes"):
        fetch_static_page("https://example.com/down")
