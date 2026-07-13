"""Browser-first website crawling and page extraction for Distill."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from distill.ingestors.sites.pinned_proxy import PinnedBrowserProxy
from distill.library.paths import site_name_from_url, slugify_title

__all__ = [
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
    "site_section_key",
]

_TEXT_LIMIT = 120_000


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
    source_url: str = ""
    depth: int = 0

    @property
    def page_id(self) -> str:
        return slugify_title(
            self.title or self.url,
            page_id_from_url(self.final_url or self.url),
            max_len=70,
        )

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
    global_max_depth = (
        int(crawl_config.get("max_depth", 1)) if isinstance(crawl_config, dict) else 1
    )
    global_max_pages = (
        int(crawl_config.get("max_pages_per_seed", 8)) if isinstance(crawl_config, dict) else 8
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
    from distill.ingestors.net import is_public_web_url

    if normalize_host(link) != root_host:
        return None
    if not is_crawlable_url(link) or not is_public_web_url(link):
        return None
    link_norm = canonicalize_url(link)
    if seed.crawl_prefix and not _is_within_crawl_prefix(link_norm, seed.crawl_prefix):
        return None
    if seed.same_section_only and not is_same_section(link_norm, seed.url):
        return None
    if link_norm in visited:
        return None
    return link_norm


def _install_public_web_route(context) -> None:
    """Abort non-HTTPS or non-public requests before they reach the pinned proxy."""
    from distill.ingestors.net import is_public_web_url

    def guard(route, request) -> None:
        if urlparse(request.url).scheme.lower() == "https" and is_public_web_url(request.url):
            route.continue_()
        else:
            route.abort()

    context.route("**/*", guard)


def crawl_site(seed: SiteSeed) -> list[SitePage]:
    from distill.ingestors.net import is_public_web_url

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
            # Confine redirect targets to the seed host, the same invariant
            # _link_is_crawlable_for_seed enforces on followed links. A page.goto
            # redirect can otherwise land off-host and be ingested, escaping the
            # crawl scope and any MCP ingest allowlist that only checked the seed.
            if not is_public_web_url(landed) or normalize_host(landed) != root_host:
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

    payload = page.evaluate(
        """
        () => {
          const textOf = (el) => (el && el.textContent ? el.textContent.trim() : '');
          const metas = Array.from(document.querySelectorAll('meta'));
          const meta = (key) => {
            const found = metas.find((m) => m.getAttribute('property') === key || m.getAttribute('name') === key);
            return found ? (found.getAttribute('content') || '').trim() : '';
          };
          const titleText =
            meta('og:title') ||
            textOf(document.querySelector('main h1')) ||
            textOf(document.querySelector('h1')) ||
            document.title ||
            '';
          const transcriptNodes = Array.from(document.querySelectorAll('[class*="transcript"], [id*="transcript"], [data-testid*="transcript"]'));
          const hrefs = Array.from(document.querySelectorAll('a[href]')).map((a) => a.href).filter(Boolean);
          const videoLinks = [
            ...Array.from(document.querySelectorAll('iframe[src]')).map((el) => el.src).filter(Boolean),
            ...Array.from(document.querySelectorAll('video source[src], video[src]')).map((el) => el.src).filter(Boolean),
          ];
          const canonical = document.querySelector('link[rel="canonical"]');
          return {
            title: titleText,
            final_url: window.location.href || '',
            canonical_url: canonical ? (canonical.href || '').trim() : '',
            description: meta('description') || meta('og:description') || '',
            published_at: meta('article:published_time') || meta('og:updated_time') || '',
            authors: Array.from(document.querySelectorAll('[rel="author"], [class*="author"], [data-testid*="author"]')).map((el) => textOf(el)).filter(Boolean).slice(0, 5),
            tags: Array.from(document.querySelectorAll('[class*="tag"], [data-testid*="tag"], a[href*="/topic/"]')).map((el) => textOf(el)).filter(Boolean).slice(0, 12),
            transcript: transcriptNodes.map((n) => textOf(n)).filter(Boolean).join('\\n\\n'),
            text: document.body && document.body.innerText ? document.body.innerText.trim() : '',
            links: hrefs,
            pdf_links: hrefs.filter((href) => href.toLowerCase().includes('.pdf')),
            video_links: videoLinks,
            has_video: !!document.querySelector('video, iframe[src*="youtube"], iframe[src*="vimeo"], [class*="video"]'),
          };
        }
        """
    )

    text = _clean_text(payload.get("text", ""))
    if not text:
        return None

    final_url = canonicalize_url(payload.get("final_url", "").strip() or page.url)
    canonical_url = canonicalize_url(payload.get("canonical_url", "").strip() or final_url)
    title = _clean_title(payload.get("title", "").strip()) or url
    return SitePage(
        url=url,
        final_url=final_url,
        canonical_url=canonical_url,
        title=title,
        site_name=site_name,
        page_type=classify_page_type(
            final_url,
            title,
            payload.get("description", ""),
            payload.get("has_video", False),
        ),
        text=text,
        description=payload.get("description", "").strip(),
        published_at=payload.get("published_at", "").strip(),
        authors=_dedupe_strings(payload.get("authors", [])),
        tags=_dedupe_strings(payload.get("tags", [])),
        links=dedupe_urls(payload.get("links", [])),
        pdf_links=dedupe_urls(payload.get("pdf_links", [])),
        video_links=dedupe_urls(payload.get("video_links", [])),
        has_video=bool(payload.get("has_video")),
        transcript=_clean_text(payload.get("transcript", "")),
        source_url=source_url,
        depth=depth,
    )


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


def _crawl_max_depth(data: dict[str, Any], *, default: int) -> int:
    if _crawl_mode(data) == "exact-page":
        return 0
    return int(data.get("max_depth", default))


def _crawl_max_pages(data: dict[str, Any], *, default: int) -> int:
    if _crawl_mode(data) == "exact-page":
        return 1
    return int(data.get("max_pages", data.get("max_pages_per_seed", default)))


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
    normalized = parsed._replace(fragment="", query=query, path=path)
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
