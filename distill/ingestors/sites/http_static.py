# pyright: strict
"""One-page HTTPS capture when no browser executable is available."""

from __future__ import annotations

import re
from html import unescape

from distill.ingestors.local.extract import html_to_text
from distill.ingestors.net import safe_urlopen
from distill.ingestors.sites.records import SitePage
from distill.library.paths import site_name_from_url

__all__ = ["StaticFetchError", "fetch_static_page"]

_MAX_RESPONSE_BYTES = 2_000_000
_MAX_TEXT_CHARS = 120_000
_TITLE_CHARS = 300
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


class StaticFetchError(Exception):
    """The static page could not be fetched or read."""


def _response_bytes(response: object) -> tuple[bytes, str, str]:
    read = getattr(response, "read", None)
    if not callable(read):
        raise StaticFetchError("response has no body")
    raw = read(_MAX_RESPONSE_BYTES + 1)
    if not isinstance(raw, bytes):
        raise StaticFetchError("response body was not bytes")
    charset = "utf-8"
    headers = getattr(response, "headers", None)
    get_charset = getattr(headers, "get_content_charset", None)
    if callable(get_charset):
        found = get_charset()
        if isinstance(found, str) and found:
            charset = found
    final_url = ""
    geturl = getattr(response, "geturl", None)
    if callable(geturl):
        found_url = geturl()
        if isinstance(found_url, str):
            final_url = found_url
    return raw, charset, final_url


def _title_from(html: str, fallback: str) -> str:
    match = _TITLE_RE.search(html)
    if match is None:
        return fallback[:_TITLE_CHARS]
    text = _SPACE_RE.sub(" ", unescape(_TAG_RE.sub("", match.group(1)))).strip()
    return (text or fallback)[:_TITLE_CHARS]


def fetch_static_page(url: str) -> SitePage:
    """Fetch one public HTTPS page and reduce it to text.

    The page is marked ``capture=http-static``. A body cut at the byte or text
    cap uses the existing ``body_text`` truncation reason.
    """

    try:
        response = safe_urlopen(url, timeout=20, retries=1)
    except Exception as exc:
        raise StaticFetchError(str(exc)[:500]) from exc
    try:
        raw, charset, final_url = _response_bytes(response)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    truncated = len(raw) > _MAX_RESPONSE_BYTES
    html = raw[:_MAX_RESPONSE_BYTES].decode(charset, errors="replace")
    text = html_to_text(html, max_chars=_MAX_TEXT_CHARS)
    if len(text) >= _MAX_TEXT_CHARS:
        truncated = True
    page_url = final_url if final_url.startswith("https://") else url
    return SitePage(
        url=url,
        title=_title_from(html, page_url),
        site_name=site_name_from_url(url),
        page_type="page",
        text=text,
        final_url=page_url,
        canonical_url=page_url,
        truncation_reasons=["body_text"] if truncated else [],
        source_url=url,
        capture="http-static",
    )
