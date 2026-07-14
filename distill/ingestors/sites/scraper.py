"""Browser-first website crawling and page extraction for Distill."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from distill.ingestors.browser_network import install_public_web_route
from distill.ingestors.sites.browser_extract import (
    bounded_page_expression,
    evaluate_bounded_page,
)
from distill.ingestors.sites.pinned_proxy import PinnedBrowserProxy
from distill.library.paths import site_name_from_url, slugify_title

__all__ = [
    "MAX_SITE_BATCH_PAGES",
    "MAX_SITE_CRAWL_DEPTH",
    "MAX_SITE_CRAWL_PAGES",
    "SiteBatch",
    "SitePage",
    "SiteSeed",
    "build_page_document",
    "canonicalize_url",
    "classify_page_type",
    "crawl_prefix_from_url",
    "crawl_site",
    "dedupe_urls",
    "is_crawlable_url",
    "is_same_section",
    "load_site_batch",
    "normalize_host",
    "page_id_from_url",
    "site_page_id",
    "site_section_key",
]

_TEXT_LIMIT = 120_000
_TRANSCRIPT_LIMIT = 120_000
_PAGE_EXTRACTION_TIMEOUT_MS = 2_000
_PAGE_DOM_NODE_LIMIT = 50_000
_PAGE_LINK_LIMIT = 512
_PAGE_PDF_LINK_LIMIT = 512
_PAGE_VIDEO_LINK_LIMIT = 64
_PAGE_AUTHOR_LIMIT = 5
_PAGE_TAG_LIMIT = 12
_PAGE_URL_CHAR_LIMIT = 2_048
_PAGE_TITLE_CHAR_LIMIT = 512
_PAGE_DESCRIPTION_CHAR_LIMIT = 4_096
_PAGE_PUBLISHED_AT_CHAR_LIMIT = 128
_PAGE_METADATA_CHAR_LIMIT = 4_096
_PAGE_ATTRIBUTE_CHAR_LIMIT = 2_048
_PAGE_LOCAL_TEXT_NODE_LIMIT = 512
_PAGE_METADATA_ELEMENT_LIMIT = 256
_EXTRACTION_TRUNCATION_REASONS = frozenset(
    {
        "authors",
        "body_text",
        "description",
        "dom_nodes",
        "links",
        "metadata",
        "pdf_links",
        "tags",
        "title",
        "transcript",
        "video_links",
    }
)
MAX_SITE_CRAWL_DEPTH = 4
MAX_SITE_CRAWL_PAGES = 100
MAX_SITE_BATCH_PAGES = 500

_BOUNDED_PAGE_LIMITS = {
    "maxDomNodes": _PAGE_DOM_NODE_LIMIT,
    "maxBodyTextChars": _TEXT_LIMIT,
    "maxTranscriptChars": _TRANSCRIPT_LIMIT,
    "maxLinks": _PAGE_LINK_LIMIT,
    "maxPdfLinks": _PAGE_PDF_LINK_LIMIT,
    "maxVideoLinks": _PAGE_VIDEO_LINK_LIMIT,
    "maxAuthors": _PAGE_AUTHOR_LIMIT,
    "maxTags": _PAGE_TAG_LIMIT,
    "maxURLChars": _PAGE_URL_CHAR_LIMIT,
    "maxTitleChars": _PAGE_TITLE_CHAR_LIMIT,
    "maxDescriptionChars": _PAGE_DESCRIPTION_CHAR_LIMIT,
    "maxPublishedAtChars": _PAGE_PUBLISHED_AT_CHAR_LIMIT,
    "maxMetadataChars": _PAGE_METADATA_CHAR_LIMIT,
    "maxAttributeChars": _PAGE_ATTRIBUTE_CHAR_LIMIT,
    "maxLocalTextNodes": _PAGE_LOCAL_TEXT_NODE_LIMIT,
    "maxMetadataElements": _PAGE_METADATA_ELEMENT_LIMIT,
    "maxAuthorChars": 512,
    "maxTagChars": 256,
}
_BOUNDED_PAGE_EXPRESSION = bounded_page_expression(_BOUNDED_PAGE_LIMITS)


@dataclass
class SitePage:
    url: str
    title: str
    site_name: str
    page_type: str
    text: str
    final_url: str = ""
    canonical_url: str = ""
    description: str = ""
    published_at: str = ""
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    pdf_links: list[str] = field(default_factory=list)
    video_links: list[str] = field(default_factory=list)
    has_video: bool = False
    transcript: str = ""
    attachment_context: str = ""
    truncation_reasons: list[str] = field(default_factory=list)
    source_url: str = ""
    depth: int = 0

    @property
    def page_id(self) -> str:
        return site_page_id(self.final_url or self.url)

    def metadata(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url or self.url,
            "canonical_url": self.canonical_url or self.final_url or self.url,
            "title": self.title,
            "site_name": self.site_name,
            "page_type": self.page_type,
            "section": site_section_key(self.final_url or self.url),
            "description": self.description,
            "published_at": self.published_at,
            "authors": self.authors,
            "tags": self.tags,
            "links": self.links,
            "pdf_links": self.pdf_links,
            "video_links": self.video_links,
            "has_video": self.has_video,
            "has_transcript": bool(self.transcript.strip()),
            "has_attachment_context": bool(self.attachment_context.strip()),
            "extraction_truncated": bool(self.truncation_reasons),
            "truncation_reasons": self.truncation_reasons,
            "source_url": self.source_url,
            "depth": self.depth,
        }


@dataclass
class SiteSeed:
    url: str
    topic: str
    site_name: str = ""
    label: str = ""
    section_label: str = ""
    source_hint: str = ""
    freshness_hint: str = ""
    crawl_prefix: str = ""
    discover_crawl: bool = False
    max_depth: int = 1
    max_pages: int = 8
    same_section_only: bool = False

    def __post_init__(self) -> None:
        self.crawl_prefix = _normalize_crawl_prefix(self.crawl_prefix)
        _validate_site_crawl_limits(self.max_depth, self.max_pages)

    def resolved_site_name(self) -> str:
        return self.site_name or site_name_from_url(self.url)


@dataclass
class SiteBatch:
    topic: str
    seeds: list[SiteSeed]


def load_site_batch(path: Path, topic_override: str = "") -> SiteBatch:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return _batch_from_json(data, topic_override)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    urls = [line for line in lines if line and not line.startswith("#")]
    topic = topic_override or "web"
    return SiteBatch(topic=topic, seeds=[SiteSeed(url=url, topic=topic) for url in urls])


def _batch_from_json(data: Any, topic_override: str) -> SiteBatch:
    topic = (
        topic_override or data.get("topic", "web")
        if isinstance(data, dict)
        else topic_override or "web"
    )
    seeds: list[SiteSeed] = []
    crawl_config = data.get("crawl", {}) if isinstance(data, dict) else {}
    global_crawl_prefix = str(crawl_config.get("crawl_prefix", crawl_config.get("path_prefix", "")))
    global_max_depth = crawl_config.get("max_depth", 1) if isinstance(crawl_config, dict) else 1
    global_max_pages = (
        crawl_config.get("max_pages_per_seed", 8) if isinstance(crawl_config, dict) else 8
    )

    if isinstance(data, list):
        iterable = data
    else:
        collections = data.get("collections", []) if isinstance(data, dict) else []
        if collections:
            for collection in collections:
                for url in collection.get("seeds", []):
                    seeds.append(
                        SiteSeed(
                            url=url,
                            topic=collection.get("topic", topic),
                            site_name=collection.get("site_name", ""),
                            label=collection.get("label", collection.get("name", "")),
                            section_label=collection.get("section_label", ""),
                            source_hint=collection.get("source_hint", ""),
                            freshness_hint=collection.get("freshness_hint", ""),
                            crawl_prefix=_crawl_prefix_from_mapping(
                                collection,
                                fallback=global_crawl_prefix,
                            ),
                            discover_crawl=bool(collection.get("discover_crawl", False)),
                            max_depth=_crawl_max_depth(collection, default=global_max_depth),
                            max_pages=_crawl_max_pages(collection, default=global_max_pages),
                            same_section_only=bool(
                                collection.get(
                                    "same_section_only",
                                    data.get("crawl", {}).get("same_section_only", False),
                                )
                            ),
                        )
                    )
            return SiteBatch(topic=topic, seeds=seeds)
        iterable = data.get("urls", []) if isinstance(data, dict) else []

    for item in iterable:
        if isinstance(item, str):
            seeds.append(SiteSeed(url=item, topic=topic))
        elif isinstance(item, dict) and item.get("url"):
            seeds.append(
                SiteSeed(
                    url=item["url"],
                    topic=item.get("topic", topic),
                    site_name=item.get("site_name", ""),
                    label=item.get("label", item.get("name", "")),
                    section_label=item.get("section_label", ""),
                    source_hint=item.get("source_hint", ""),
                    freshness_hint=item.get("freshness_hint", ""),
                    crawl_prefix=_crawl_prefix_from_mapping(item, fallback=global_crawl_prefix),
                    discover_crawl=bool(item.get("discover_crawl", False)),
                    max_depth=_crawl_max_depth(item, default=global_max_depth),
                    max_pages=_crawl_max_pages(item, default=global_max_pages),
                    same_section_only=bool(item.get("same_section_only", False)),
                )
            )
    return SiteBatch(topic=topic, seeds=seeds)


def _link_is_crawlable_for_seed(
    link: str,
    *,
    seed: SiteSeed,
    root_host: str,
    visited: set[str],
) -> str | None:
    """Return the canonicalized link if it should be crawled, else ``None``.

    Extracted from ``crawl_site`` to keep that function under ruff's
    mccabe complexity budget. Mirrors the same-host / scheme / public-IP /
    section / dedupe filters that protect the crawler from SSRF and runaway
    cross-site recursion.
    """
    link_norm = _canonical_url_in_seed_scope(link, seed=seed, root_host=root_host)
    if link_norm is None:
        return None
    if link_norm in visited:
        return None
    return link_norm


def _canonical_url_in_seed_scope(
    url: str,
    *,
    seed: SiteSeed,
    root_host: str,
) -> str | None:
    """Return a canonical public HTTPS URL confined to the seed's crawl scope."""
    from distill.ingestors.net import is_public_web_url

    if urlparse(url).scheme.lower() != "https":
        return None
    if normalize_host(url) != root_host or not is_public_web_url(url):
        return None
    if not is_crawlable_url(url):
        return None
    normalized = canonicalize_url(url)
    if seed.crawl_prefix and not _is_within_crawl_prefix(normalized, seed.crawl_prefix):
        return None
    if seed.same_section_only and not is_same_section(normalized, seed.url):
        return None
    return normalized


def _install_public_web_route(context) -> None:
    """Abort non-HTTPS or non-public requests before they reach the pinned proxy."""
    install_public_web_route(context)


def crawl_site(seed: SiteSeed) -> list[SitePage]:
    from distill.ingestors.net import is_public_web_url

    _validate_site_crawl_limits(seed.max_depth, seed.max_pages)

    # Reject seeds that point at the local browser host, RFC1918 networks, the
    # cloud-metadata link-local range, or non-http(s) schemes such as
    # ``file://``. Without this gate, Playwright would dutifully ``page.goto``
    # whatever the user/agent supplied and surface the response as page text.
    if (
        urlparse(seed.url).scheme.lower() != "https"
        or not is_public_web_url(seed.url)
        or not is_crawlable_url(seed.url)
    ):
        return []

    from playwright.sync_api import sync_playwright

    root_host = normalize_host(seed.url)
    queue: deque[tuple[str, int, str]] = deque([(seed.url, 0, seed.url)])
    visited: set[str] = set()
    pages: list[SitePage] = []

    with PinnedBrowserProxy() as proxy_server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-quic",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            ],
        )
        context = browser.new_context(
            proxy={"server": proxy_server},
            service_workers="block",
        )
        _install_public_web_route(context)
        page = context.new_page()
        page.set_default_timeout(30_000)

        while queue and len(pages) < seed.max_pages:
            current_url, depth, source_url = queue.popleft()
            normalized = canonicalize_url(current_url)
            if normalized in visited:
                continue
            visited.add(normalized)

            extracted = _extract_page(
                page,
                normalized,
                seed.resolved_site_name(),
                source_url,
                depth,
            )
            if extracted is None:
                continue
            landed = extracted.final_url or extracted.url
            # Reapply the complete crawl boundary after navigation because an
            # allowed seed can redirect outside its configured path or section.
            if _canonical_url_in_seed_scope(landed, seed=seed, root_host=root_host) is None:
                continue
            pages.append(extracted)

            if depth >= seed.max_depth:
                continue

            for link in _prioritize_links(extracted.links, seed.url, normalized):
                link_norm = _link_is_crawlable_for_seed(
                    link, seed=seed, root_host=root_host, visited=visited
                )
                if link_norm is None:
                    continue
                queue.append((link_norm, depth + 1, normalized))

        context.close()
        browser.close()

    return pages


def _extract_bounded_page_payload(page: Any) -> dict[str, Any] | None:
    """Extract a bounded payload in a clean Chromium world with a hard deadline."""
    return evaluate_bounded_page(
        page,
        expression=_BOUNDED_PAGE_EXPRESSION,
        timeout_ms=_PAGE_EXTRACTION_TIMEOUT_MS,
    )


def _extract_page(
    page,
    url: str,
    site_name: str,
    source_url: str,
    depth: int,
) -> SitePage | None:
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        for _ in range(3):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(250)
    except Exception:
        return None

    payload = _extract_bounded_page_payload(page)
    if payload is None:
        return None

    truncation_reasons = _payload_truncation_reasons(payload)
    text = _clean_text(
        _bounded_payload_string(
            payload,
            "text",
            _TEXT_LIMIT,
            truncation_reasons,
            "body_text",
        )
    )
    if not text:
        return None

    final_url_value = _bounded_payload_string(
        payload,
        "final_url",
        _PAGE_URL_CHAR_LIMIT,
        truncation_reasons,
        "metadata",
    )
    final_url = canonicalize_url(final_url_value.strip() or page.url)
    canonical_url_value = _bounded_payload_string(
        payload,
        "canonical_url",
        _PAGE_URL_CHAR_LIMIT,
        truncation_reasons,
        "metadata",
    )
    canonical_url = canonicalize_url(canonical_url_value.strip() or final_url)
    title = (
        _clean_title(
            _bounded_payload_string(
                payload,
                "title",
                _PAGE_TITLE_CHAR_LIMIT,
                truncation_reasons,
                "title",
            )
        )
        or url
    )
    description = _bounded_payload_string(
        payload,
        "description",
        _PAGE_DESCRIPTION_CHAR_LIMIT,
        truncation_reasons,
        "description",
    ).strip()
    published_at = _bounded_payload_string(
        payload,
        "published_at",
        _PAGE_PUBLISHED_AT_CHAR_LIMIT,
        truncation_reasons,
        "metadata",
    ).strip()
    has_video = payload.get("has_video") is True
    return SitePage(
        url=url,
        final_url=final_url,
        canonical_url=canonical_url,
        title=title,
        site_name=site_name,
        page_type=classify_page_type(
            final_url,
            title,
            description,
            has_video,
        ),
        text=text,
        description=description,
        published_at=published_at,
        authors=_dedupe_strings(
            _bounded_payload_strings(
                payload,
                "authors",
                _PAGE_AUTHOR_LIMIT,
                512,
                truncation_reasons,
                "authors",
            )
        ),
        tags=_dedupe_strings(
            _bounded_payload_strings(
                payload,
                "tags",
                _PAGE_TAG_LIMIT,
                256,
                truncation_reasons,
                "tags",
            )
        ),
        links=dedupe_urls(
            _bounded_payload_strings(
                payload,
                "links",
                _PAGE_LINK_LIMIT,
                _PAGE_URL_CHAR_LIMIT,
                truncation_reasons,
                "links",
            )
        ),
        pdf_links=dedupe_urls(
            _bounded_payload_strings(
                payload,
                "pdf_links",
                _PAGE_PDF_LINK_LIMIT,
                _PAGE_URL_CHAR_LIMIT,
                truncation_reasons,
                "pdf_links",
            )
        ),
        video_links=dedupe_urls(
            _bounded_payload_strings(
                payload,
                "video_links",
                _PAGE_VIDEO_LINK_LIMIT,
                _PAGE_URL_CHAR_LIMIT,
                truncation_reasons,
                "video_links",
            )
        ),
        has_video=has_video,
        transcript=_clean_text(
            _bounded_payload_string(
                payload,
                "transcript",
                _TRANSCRIPT_LIMIT,
                truncation_reasons,
                "transcript",
            )
        ),
        truncation_reasons=sorted(truncation_reasons),
        source_url=source_url,
        depth=depth,
    )


def _payload_truncation_reasons(payload: dict[str, Any]) -> set[str]:
    raw = payload.get("truncation_reasons")
    if not isinstance(raw, list):
        return set()
    return {
        reason
        for reason in raw
        if isinstance(reason, str) and reason in _EXTRACTION_TRUNCATION_REASONS
    }


def _bounded_payload_string(
    payload: dict[str, Any],
    key: str,
    maximum: int,
    truncation_reasons: set[str],
    reason: str,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        return ""
    if len(value) > maximum:
        truncation_reasons.add(reason)
    return value[:maximum]


def _bounded_payload_strings(
    payload: dict[str, Any],
    key: str,
    maximum_items: int,
    maximum_chars: int,
    truncation_reasons: set[str],
    reason: str,
) -> list[str]:
    raw_values = payload.get(key)
    if not isinstance(raw_values, list):
        return []
    if len(raw_values) > maximum_items:
        truncation_reasons.add(reason)
    result: list[str] = []
    for value in raw_values[:maximum_items]:
        if not isinstance(value, str):
            continue
        if len(value) > maximum_chars:
            truncation_reasons.add(reason)
        result.append(value[:maximum_chars])
    return result


def classify_page_type(url: str, title: str, description: str, has_video: bool) -> str:
    lowered = f"{url} {title} {description}".lower()
    if "/video/" in lowered or has_video:
        return "video"
    if "/partner/" in lowered:
        return "partner"
    if "/topic/" in lowered:
        return "topic"
    if "/lab/" in lowered:
        return "lab"
    if "/research/" in lowered or "/research-and-insights/" in lowered or "/insights/" in lowered:
        return "research"
    if "/category/" in lowered:
        return "category"
    if "/overview" in lowered:
        return "overview"
    if "/explore" in lowered:
        return "explore"
    if "/ecosystem" in lowered:
        return "ecosystem"
    return "page"


def build_page_document(page: SitePage) -> str:
    transcript_block = f"\n\n## Transcript\n{page.transcript}" if page.transcript.strip() else ""
    video_block = (
        "\n\n## Video Links\n" + "\n".join(f"- {link}" for link in page.video_links)
        if page.video_links
        else ""
    )
    pdf_block = (
        "\n\n## PDF Links\n" + "\n".join(f"- {link}" for link in page.pdf_links)
        if page.pdf_links
        else ""
    )
    attachment_block = (
        f"\n\n## Attachment Extracts\n{page.attachment_context}"
        if page.attachment_context.strip()
        else ""
    )
    return f"""# {page.title}

- URL: {page.url}
- Final URL: {page.final_url or page.url}
- Canonical URL: {page.canonical_url or page.final_url or page.url}
- Site: {page.site_name}
- Page Type: {page.page_type}
- Published: {page.published_at or "Unknown"}
- Authors: {", ".join(page.authors) or "Unknown"}
- Tags: {", ".join(page.tags) or "None"}
- Has Video: {"yes" if page.has_video else "no"}
- Discovered From: {page.source_url or page.url}
- Crawl Depth: {page.depth}

## Description
{page.description or "None"}

## Content
{page.text}{transcript_block}{video_block}{pdf_block}{attachment_block}
"""


def page_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    base = parsed.path.strip("/") or parsed.netloc
    return slugify_title(base, max_len=20)


def site_page_id(url: str) -> str:
    """Return a stable, collision-resistant identity for a landed page URL."""

    canonical_url = canonicalize_url(url)
    return sha256(canonical_url.encode("utf-8")).hexdigest()


def crawl_prefix_from_url(url: str) -> str:
    return _normalize_crawl_prefix(urlparse(url).path)


def _crawl_prefix_from_mapping(data: dict[str, Any], fallback: str = "") -> str:
    raw = data.get("crawl_prefix", data.get("path_prefix", fallback))
    return _normalize_crawl_prefix(str(raw or ""))


def _crawl_mode(data: dict[str, Any]) -> str:
    raw_value = data.get("mode", data.get("crawl_mode", ""))
    raw = str(raw_value).strip().lower()
    aliases = {
        "exact": "exact-page",
        "seed": "exact-page",
        "seed-only": "exact-page",
        "seed_only": "exact-page",
        "page": "exact-page",
        "exact-page": "exact-page",
        "exact_page": "exact-page",
        "crawl": "shallow-crawl",
        "shallow": "shallow-crawl",
        "shallow-crawl": "shallow-crawl",
        "shallow_crawl": "shallow-crawl",
    }
    mode = aliases.get(raw, raw)
    crawl_flag = data.get("crawl")
    if isinstance(crawl_flag, bool):
        return "shallow-crawl" if crawl_flag else "exact-page"
    if mode and mode not in {"exact-page", "shallow-crawl"}:
        raise ValueError(
            f"Unsupported site crawl mode {raw_value!r}. Use exact-page or shallow-crawl."
        )
    return mode


def _crawl_max_depth(data: dict[str, Any], *, default: object) -> int:
    if _crawl_mode(data) == "exact-page":
        return 0
    return _validated_crawl_limit(
        "max_depth",
        data.get("max_depth", default),
        minimum=0,
        maximum=MAX_SITE_CRAWL_DEPTH,
    )


def _crawl_max_pages(data: dict[str, Any], *, default: object) -> int:
    if _crawl_mode(data) == "exact-page":
        return 1
    return _validated_crawl_limit(
        "max_pages",
        data.get("max_pages", data.get("max_pages_per_seed", default)),
        minimum=1,
        maximum=MAX_SITE_CRAWL_PAGES,
    )


def _validate_site_crawl_limits(max_depth: object, max_pages: object) -> None:
    _validated_crawl_limit(
        "max_depth",
        max_depth,
        minimum=0,
        maximum=MAX_SITE_CRAWL_DEPTH,
    )
    _validated_crawl_limit(
        "max_pages",
        max_pages,
        minimum=1,
        maximum=MAX_SITE_CRAWL_PAGES,
    )


def _validated_crawl_limit(name: str, value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _normalize_crawl_prefix(value: str) -> str:
    raw = value.strip()
    if "://" in raw:
        raw = urlparse(raw).path
    tokens = [token for token in raw.strip("/").split("/") if token]
    if not tokens:
        return ""
    return "/" + "/".join(tokens)


def _is_within_crawl_prefix(url: str, crawl_prefix: str) -> bool:
    prefix = _normalize_crawl_prefix(crawl_prefix)
    if not prefix:
        return True
    path = urlparse(url).path.rstrip("/") or "/"
    return path == prefix or path.startswith(prefix + "/")


def site_section_key(url: str) -> str:
    tokens = [token for token in urlparse(url).path.strip("/").split("/") if token]
    if not tokens:
        return "root"
    if len(tokens) == 1:
        return tokens[0]
    return "/".join(tokens[:2])


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc
    if parsed.hostname:
        try:
            host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
            if ":" in host:
                host = f"[{host}]"
            port = parsed.port
            if (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)}:
                port = None
            host_port = f"{host}:{port}" if port is not None else host
            userinfo, separator, _authority = parsed.netloc.rpartition("@")
            netloc = f"{userinfo}@{host_port}" if separator else host_port
        except (UnicodeError, ValueError):
            netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query = ""
    if parsed.query:
        keep = [
            part
            for part in parsed.query.split("&")
            if not part.startswith(("utm_", "fbclid=", "gclid="))
        ]
        query = "&".join(sorted(filter(None, keep)))
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        fragment="",
        query=query,
        path=path,
    )
    return normalized.geturl()


def normalize_host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def is_crawlable_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    lowered = url.lower()
    blocked = ("/login", "/search", ".pdf", ".jpg", ".png", ".gif", ".svg", ".zip")
    return not any(token in lowered for token in blocked)


def dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        normalized = canonicalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def is_same_section(url: str, seed_url: str) -> bool:
    url_path = [token for token in urlparse(url).path.strip("/").split("/") if token]
    seed_path = [token for token in urlparse(seed_url).path.strip("/").split("/") if token]
    if not url_path or not seed_path:
        return False
    return url_path[0] == seed_path[0]


def _prioritize_links(links: list[str], seed_url: str, current_url: str) -> list[str]:
    return sorted(
        dedupe_urls(links),
        key=lambda link: (
            -_link_relevance_score(link, seed_url, current_url),
            len(urlparse(link).path),
            link,
        ),
    )


def _link_relevance_score(link: str, seed_url: str, current_url: str) -> int:
    link_path = urlparse(link).path.strip("/")
    seed_path = urlparse(seed_url).path.strip("/")
    current_path = urlparse(current_url).path.strip("/")
    score = 0
    if not link_path:
        return score
    if link_path == seed_path:
        score += 100
    if seed_path and link_path.startswith(seed_path):
        score += 40
    seed_tokens = [token for token in seed_path.split("/") if token]
    current_tokens = [token for token in current_path.split("/") if token]
    link_tokens = {token for token in link_path.split("/") if token}
    score += sum(8 for token in seed_tokens if token in link_tokens)
    score += sum(4 for token in current_tokens if token in link_tokens)
    if any(
        segment in link_path
        for segment in (
            "video",
            "topic",
            "partner",
            "lab",
            "research",
            "insights",
            "docs",
        )
    ):
        score += 8
    if link_path in {"", "/", "home"} or link_path.count("/") < 1:
        score -= 20
    if any(
        token in link_path
        for token in (
            "contact",
            "careers",
            "about",
            "news",
            "press",
            "privacy",
            "cookies",
            "locations",
        )
    ):
        score -= 12
    return score


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().strip("-|")


def _clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    filtered = [line for line in lines if line and len(line) > 1]
    return "\n".join(filtered)[:_TEXT_LIMIT].strip()
