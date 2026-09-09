"""Current publisher receipts through Distill's bounded public-source fetchers."""

from __future__ import annotations

import hashlib
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from distill.editorial.perspective import EditorialModel, EditorialSources, Text
from distill.ingestors.local import html_to_text
from distill.ingestors.net import NetworkError, safe_urlopen
from distill.ingestors.podcasts.feed import PodcastFetchError, fetch_feed
from distill.library.paths import atomic_write_json


class SourceReceipt(EditorialModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    id: str = Field(pattern=r"^s[0-9a-f]{16}$")
    url: Text
    title: Text
    published_at: str = ""
    fetched_at: str
    kind: Literal["feed", "page"]
    text: str = Field(min_length=1, max_length=120000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    truncated: bool = False
    capture_method: Literal["distill-public-https", "supplied-receipt"] = "distill-public-https"


def receipt(*, url: str, title: str, text: str, published: str = "", kind: str) -> SourceReceipt:
    return SourceReceipt.model_validate(
        {
            "id": "s" + hashlib.sha256(url.encode()).hexdigest()[:16],
            "url": url,
            "title": title,
            "published_at": published,
            "fetched_at": datetime.now(UTC).isoformat(),
            "kind": kind,
            "text": text[:120000],
            "sha256": hashlib.sha256(text[:120000].encode()).hexdigest(),
            "truncated": len(text) > 120000,
        }
    )


def fetch_page(url: str) -> SourceReceipt:
    request = urllib.request.Request(url, headers={"User-Agent": "distillr"})
    with safe_urlopen(request, timeout=30, retries=0) as response:
        raw = response.read(4000001)
        if len(raw) > 4000000:
            raise ValueError("Page exceeds the 4 MB capture limit")
        final_url = response.geturl()
    text = html_to_text(raw.decode("utf-8", errors="replace"), max_chars=120001)
    return receipt(url=final_url, title=url, text=text, kind="page")


def _feed_items(url: str, cutoff: datetime, now: datetime) -> list[SourceReceipt]:
    items = []
    for item in fetch_feed(url).episodes:
        published = item.published_dt()
        if not published or not cutoff <= published <= now or not item.link.startswith("https://"):
            continue
        text = html_to_text(item.content_html or item.description, max_chars=120001)
        if text.strip():
            items.append(
                receipt(
                    url=item.link,
                    title=item.title,
                    text=text,
                    published=published.isoformat(),
                    kind="feed",
                )
            )
    return sorted(items, key=lambda item: item.published_at, reverse=True)


def _capture_pages(
    config: EditorialSources, failures: list[dict[str, str]]
) -> dict[str, SourceReceipt]:
    selected: dict[str, SourceReceipt] = {}
    for url in config.urls:
        if len(selected) >= config.max_sources:
            break
        try:
            item = fetch_page(url)
            selected.setdefault(item.url, item)
        except (NetworkError, ValueError, OSError) as exc:
            failures.append({"url": url, "error": type(exc).__name__})
    return selected


def collect_sources(
    config: EditorialSources, *, now: datetime | None = None
) -> tuple[list[SourceReceipt], list[dict[str, str]]]:
    """Capture current RSS items plus exact pages; preserve failures without inventing news.

    The date window is structural. Relevance, significance, and source diversity
    are judged by the reading and idea stages, not keyword scoring.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=config.lookback_days)
    sources: dict[str, SourceReceipt] = {}
    failures: list[dict[str, str]] = []
    groups: list[list[SourceReceipt]] = []
    for url in config.feeds:
        try:
            groups.append(_feed_items(url, cutoff, now))
        except (NetworkError, PodcastFetchError, ValueError, OSError) as exc:
            failures.append({"url": url, "error": type(exc).__name__})
    # Round-robin only allocates capture slots across operator-chosen feeds.
    for index in range(config.max_sources):
        for group in groups:
            if index < len(group):
                item = group[index]
                sources.setdefault(item.url, item)
    selected = _capture_pages(config, failures)
    for item in sources.values():
        if len(selected) >= config.max_sources:
            break
        if item.url in selected:
            continue
        try:
            page = fetch_page(item.url)
            item = item.model_copy(
                update={"text": page.text, "sha256": page.sha256, "truncated": page.truncated}
            )
        except (NetworkError, ValueError, OSError) as exc:
            failures.append({"url": item.url, "error": f"Summary only: {type(exc).__name__}"})
        selected[item.url] = item
    return list(selected.values()), failures


def save_receipts(directory: Path, sources: list[SourceReceipt]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for source in sources:
        atomic_write_json(directory / f"{source.id}.json", source.model_dump())


def load_receipts(directory: Path, config: EditorialSources) -> list[SourceReceipt]:
    """Admit bounded, recent receipts from another research run or an external agent.

    Digests prove file integrity, not publisher authenticity. The supplied
    provenance label remains explicit throughout the editorial workflow.
    """
    paths = sorted(directory.glob("*.json"))
    if not paths or len(paths) > config.max_sources:
        raise ValueError("Supply between one and max_sources receipt JSON files")
    now = datetime.now(UTC)
    result: dict[str, SourceReceipt] = {}
    for path in paths:
        with path.open("rb") as stream:
            raw = stream.read(600001)
        if len(raw) > 600000:
            raise ValueError("Supplied receipt exceeds the 600000-byte limit")
        source = SourceReceipt.model_validate_json(raw)
        EditorialSources(urls=[source.url])
        if hashlib.sha256(source.text.encode()).hexdigest() != source.sha256:
            raise ValueError("Supplied receipt content digest mismatch")
        expected_id = "s" + hashlib.sha256(source.url.encode()).hexdigest()[:16]
        if source.id != expected_id or source.url in result:
            raise ValueError("Supplied receipt identity mismatch or duplicate URL")
        fetched = datetime.fromisoformat(source.fetched_at)
        if (
            fetched.tzinfo is None
            or not now - timedelta(days=config.lookback_days) <= fetched <= now
        ):
            raise ValueError("Supplied receipts must have a recent, timezone-aware capture date")
        result[source.url] = source.model_copy(update={"capture_method": "supplied-receipt"})
    return list(result.values())


def evidence_packet(sources: list[SourceReceipt], excerpt_chars: int) -> list[dict[str, object]]:
    return [
        {
            **source.model_dump(exclude={"sha256"}),
            "text": source.text[:excerpt_chars],
            "excerpt_truncated": len(source.text) > excerpt_chars,
        }
        for source in sources
    ]
