"""Trusted website candidate discovery for goal-aware mixed-source runs."""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser

from defusedxml.ElementTree import fromstring as xml_fromstring

from distill.ingestors.net import NetworkError, is_public_web_url, safe_urlopen
from distill.ingestors.sites.scraper import (
    SiteSeed,
    canonicalize_url,
    crawl_prefix_from_url,
    dedupe_urls,
    is_crawlable_url,
    normalize_host,
    site_section_key,
)
from distill.library.paths import site_name_from_url

__all__ = [
    "TrustedSiteDiscoveryResult",
    "discover_trusted_site_seeds",
]

FetchText = Callable[[str], str]
_TOC_SOURCE_HINT = "toc link"
_LANDING_SOURCE_HINT = "landing link"
_MAX_LANDING_PARSE_EVENTS = 100_000
_MAX_LANDING_NESTING = 512
_MAX_LANDING_ANCHORS = 4_096
_MAX_LANDING_ANCHOR_TEXT_CHARS = 1_024
_MAX_LANDING_ATTRIBUTES = 256
_MAX_LANDING_HREF_CHARS = 8_192


@dataclass(frozen=True)
class TrustedSiteDiscoveryResult:
    seeds: list[SiteSeed]
    source_count: int
    fetched_sitemaps: int
    fetched_landing_pages: int


class LandingParseLimit(ValueError):
    """Raised when untrusted landing-page HTML exceeds a parsing budget."""


class _AnchorParser(HTMLParser):
    def __init__(
        self,
        *,
        max_events: int = _MAX_LANDING_PARSE_EVENTS,
        max_depth: int = _MAX_LANDING_NESTING,
        max_anchors: int = _MAX_LANDING_ANCHORS,
        max_anchor_text_chars: int = _MAX_LANDING_ANCHOR_TEXT_CHARS,
        max_attributes: int = _MAX_LANDING_ATTRIBUTES,
        max_href_chars: int = _MAX_LANDING_HREF_CHARS,
    ) -> None:
        budgets = {
            "event": max_events,
            "nesting depth": max_depth,
            "anchor": max_anchors,
            "anchor text": max_anchor_text_chars,
            "attribute": max_attributes,
            "href": max_href_chars,
        }
        for name, value in budgets.items():
            if value <= 0:
                raise ValueError(f"landing page {name} budget must be positive")
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, bool]] = []
        self._element_stack: list[tuple[str, bool]] = []
        self._positions: dict[str, list[int]] = {}
        self._href_stack: list[str] = []
        self._toc_link_stack: list[bool] = []
        self._text_stack: list[list[str]] = []
        self._text_length_stack: list[int] = []
        self._events = 0
        self._anchor_count = 0
        self._max_events = max_events
        self._max_depth = max_depth
        self._max_anchors = max_anchors
        self._max_anchor_text_chars = max_anchor_text_chars
        self._max_attributes = max_attributes
        self._max_href_chars = max_href_chars

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record_event()
        if len(attrs) > self._max_attributes:
            raise LandingParseLimit("landing page attribute budget exceeded")
        if len(self._element_stack) + len(self._href_stack) >= self._max_depth:
            raise LandingParseLimit("landing page nesting depth budget exceeded")
        lowered = tag.lower()
        in_toc = self._in_toc_context() or _is_toc_container(lowered, attrs)
        if lowered != "a":
            position = len(self._element_stack)
            self._element_stack.append((lowered, in_toc))
            self._positions.setdefault(lowered, []).append(position)
            return
        if self._anchor_count >= self._max_anchors:
            raise LandingParseLimit("landing page anchor budget exceeded")
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value
                break
        if len(href) > self._max_href_chars:
            raise LandingParseLimit("landing page href budget exceeded")
        self._anchor_count += 1
        self._href_stack.append(href)
        self._toc_link_stack.append(in_toc)
        self._text_stack.append([])
        self._text_length_stack.append(0)

    def handle_data(self, data: str) -> None:
        self._record_event()
        if not self._text_stack:
            return
        retained = self._text_length_stack[-1]
        remaining = self._max_anchor_text_chars - retained
        if remaining <= 0:
            return
        fragment = data[:remaining]
        self._text_stack[-1].append(fragment)
        self._text_length_stack[-1] = retained + len(fragment)

    def handle_endtag(self, tag: str) -> None:
        self._record_event()
        lowered = tag.lower()
        if lowered != "a":
            self._pop_element(lowered)
            return
        if not self._href_stack:
            return
        href = self._href_stack.pop()
        in_toc = self._toc_link_stack.pop() if self._toc_link_stack else False
        text = " ".join("".join(self._text_stack.pop()).split())
        self._text_length_stack.pop()
        if href:
            self.links.append((href, text, in_toc))

    def _in_toc_context(self) -> bool:
        return self._element_stack[-1][1] if self._element_stack else False

    def _pop_element(self, tag: str) -> None:
        positions = self._positions.get(tag)
        if not positions:
            return
        matched_position = positions[-1]
        while len(self._element_stack) > matched_position:
            removed_tag, _ = self._element_stack.pop()
            removed_positions = self._positions[removed_tag]
            removed_positions.pop()
            if not removed_positions:
                del self._positions[removed_tag]

    def _record_event(self) -> None:
        self._events += 1
        if self._events > self._max_events:
            raise LandingParseLimit("landing page event budget exceeded")


def discover_trusted_site_seeds(
    sources: Sequence[str],
    *,
    topic: str,
    max_candidates: int = 40,
    max_sitemaps_per_source: int = 4,
    fetch_text: FetchText | None = None,
) -> TrustedSiteDiscoveryResult:
    """Enumerate page candidates from operator-trusted domains or sections.

    The operator supplies the trust boundary. This helper only enumerates public
    same-host URLs from sitemaps and landing-page links, then returns exact-page
    seeds for the existing model reranker to judge against the goal.
    """
    if max_candidates <= 0:
        return TrustedSiteDiscoveryResult([], 0, 0, 0)
    fetch = fetch_text or _fetch_text
    seeds: list[SiteSeed] = []
    seen: set[str] = set()
    fetched_sitemaps = 0
    fetched_landing_pages = 0
    normalized_sources = [src for src in (_normalize_source(s) for s in sources) if src]

    for source_url in normalized_sources:
        if len(seeds) >= max_candidates:
            break
        source_result = _collect_source_seeds(
            source_url,
            topic=topic,
            fetch_text=fetch,
            seen=seen,
            remaining=max_candidates - len(seeds),
            max_sitemaps=max_sitemaps_per_source,
        )
        seeds.extend(source_result.seeds)
        fetched_sitemaps += source_result.fetched_sitemaps
        fetched_landing_pages += source_result.fetched_landing_pages

    return TrustedSiteDiscoveryResult(
        seeds=seeds[:max_candidates],
        source_count=len(normalized_sources),
        fetched_sitemaps=fetched_sitemaps,
        fetched_landing_pages=fetched_landing_pages,
    )


@dataclass(frozen=True)
class _LandingPageCandidate:
    url: str
    label: str
    source_hint: str


@dataclass(frozen=True)
class _LandingCandidates:
    urls: list[_LandingPageCandidate]
    landing_fetches: int


@dataclass(frozen=True)
class _SitemapPageCandidate:
    url: str
    freshness_hint: str = ""


@dataclass(frozen=True)
class _SourceDiscovery:
    seeds: list[SiteSeed]
    fetched_sitemaps: int
    fetched_landing_pages: int


def _collect_source_seeds(
    source_url: str,
    *,
    topic: str,
    fetch_text: FetchText,
    seen: set[str],
    remaining: int,
    max_sitemaps: int,
) -> _SourceDiscovery:
    seeds: list[SiteSeed] = []
    sitemap_urls, sitemap_fetches = _candidate_urls_from_sitemaps(
        source_url,
        fetch_text=fetch_text,
        max_sitemaps=max_sitemaps,
    )
    for candidate in sitemap_urls:
        if (
            _add_seed(
                seeds,
                seen,
                candidate.url,
                _label_from_url(candidate.url),
                source_url,
                topic,
                source_hint="sitemap",
                freshness_hint=candidate.freshness_hint,
            )
            and len(seeds) >= remaining
        ):
            return _SourceDiscovery(seeds, sitemap_fetches, 0)

    landing = _candidate_urls_from_landing(source_url, fetch_text=fetch_text)
    for candidate in landing.urls:
        if (
            _add_seed(
                seeds,
                seen,
                candidate.url,
                candidate.label,
                source_url,
                topic,
                source_hint=candidate.source_hint,
            )
            and len(seeds) >= remaining
        ):
            return _SourceDiscovery(seeds, sitemap_fetches, landing.landing_fetches)

    if canonicalize_url(source_url) not in seen:
        _add_seed(
            seeds,
            seen,
            source_url,
            _label_from_url(source_url),
            source_url,
            topic,
            source_hint="trusted site",
        )
    return _SourceDiscovery(seeds, sitemap_fetches, landing.landing_fetches)


def _add_seed(
    seeds: list[SiteSeed],
    seen: set[str],
    url: str,
    label: str,
    source_url: str,
    topic: str,
    source_hint: str = "",
    freshness_hint: str = "",
) -> bool:
    normalized = _trusted_candidate_url(url, source_url)
    if not normalized or normalized in seen:
        return False
    seen.add(normalized)
    seeds.append(
        SiteSeed(
            url=normalized,
            topic=topic,
            site_name=site_name_from_url(source_url),
            label=label or _label_from_url(normalized),
            section_label=site_section_key(normalized),
            source_hint=source_hint,
            freshness_hint=freshness_hint,
            crawl_prefix=crawl_prefix_from_url(source_url),
            discover_crawl=False,
            max_depth=0,
            max_pages=1,
            same_section_only=True,
        )
    )
    return True


def _candidate_urls_from_sitemaps(
    source_url: str,
    *,
    fetch_text: FetchText,
    max_sitemaps: int,
) -> tuple[list[_SitemapPageCandidate], int]:
    queue: deque[str] = deque(_default_sitemap_urls(source_url))
    seen_sitemaps: set[str] = set()
    fetched = 0
    found_urls: list[_SitemapPageCandidate] = []
    while queue and fetched < max_sitemaps:
        sitemap_url = queue.popleft()
        normalized_sitemap = _trusted_same_host_url(sitemap_url, source_url)
        if not normalized_sitemap or normalized_sitemap in seen_sitemaps:
            continue
        seen_sitemaps.add(normalized_sitemap)
        text = _try_fetch(fetch_text, normalized_sitemap)
        if not text:
            continue
        fetched += 1
        nested, sitemap_page_urls = _parse_sitemap(text)
        for nested_url in nested:
            if _trusted_same_host_url(nested_url, source_url):
                queue.append(nested_url)
        found_urls.extend(sitemap_page_urls)
    return found_urls, fetched


def _candidate_urls_from_landing(source_url: str, *, fetch_text: FetchText) -> _LandingCandidates:
    html = _try_fetch(fetch_text, source_url)
    if not html:
        return _LandingCandidates([], 0)
    parser = _AnchorParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return _LandingCandidates([], 1)
    candidates: list[_LandingPageCandidate] = []
    for href, text, in_toc in parser.links:
        absolute = urllib.parse.urljoin(source_url, href)
        candidates.append(
            _LandingPageCandidate(
                url=absolute,
                label=_clean_label(text) or _label_from_url(absolute),
                source_hint=_TOC_SOURCE_HINT if in_toc else _LANDING_SOURCE_HINT,
            )
        )
    deduped = _dedupe_landing_candidates(candidates)
    return _LandingCandidates(deduped, 1)


def _dedupe_landing_candidates(
    candidates: list[_LandingPageCandidate],
) -> list[_LandingPageCandidate]:
    by_url: dict[str, _LandingPageCandidate] = {}
    for candidate in candidates:
        normalized = canonicalize_url(candidate.url)
        current = by_url.get(normalized)
        if current is None:
            by_url[normalized] = candidate
            continue
        if current.source_hint != _TOC_SOURCE_HINT and candidate.source_hint == _TOC_SOURCE_HINT:
            del by_url[normalized]
            by_url[normalized] = candidate
    ordered = list(by_url.values())
    toc = [candidate for candidate in ordered if candidate.source_hint == _TOC_SOURCE_HINT]
    landing = [candidate for candidate in ordered if candidate.source_hint != _TOC_SOURCE_HINT]
    return toc + landing


def _parse_sitemap(text: str) -> tuple[list[str], list[_SitemapPageCandidate]]:
    try:
        root = xml_fromstring(text.encode("utf-8"))
    except Exception:
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", text, flags=re.IGNORECASE)
        return [], [_SitemapPageCandidate(url=loc) for loc in locs]
    root_name = _strip_namespace(root.tag).lower()
    if root_name == "sitemapindex":
        return _sitemap_locs(root), []
    entries = _sitemap_page_candidates(root)
    if entries:
        return [], entries
    return [], [_SitemapPageCandidate(url=loc) for loc in _sitemap_locs(root)]


def _sitemap_locs(root) -> list[str]:
    return [
        (node.text or "").strip()
        for node in root.iter()
        if _strip_namespace(node.tag).lower() == "loc" and (node.text or "").strip()
    ]


def _sitemap_page_candidates(root) -> list[_SitemapPageCandidate]:
    entries: list[_SitemapPageCandidate] = []
    for child in root:
        if _strip_namespace(child.tag).lower() != "url":
            continue
        loc = ""
        lastmod = ""
        for node in child:
            name = _strip_namespace(node.tag).lower()
            text = (node.text or "").strip()
            if name == "loc":
                loc = text
            elif name == "lastmod":
                lastmod = text
        if loc:
            entries.append(_SitemapPageCandidate(loc, _clean_lastmod(lastmod)))
    return entries


def _clean_lastmod(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    match = re.match(r"^\d{4}-\d{2}-\d{2}", cleaned)
    if match:
        return match.group(0)
    return cleaned[:32]


def _strip_namespace(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _trusted_candidate_url(url: str, source_url: str) -> str:
    normalized = _trusted_same_host_url(url, source_url)
    if not normalized or not _within_source_scope(normalized, source_url):
        return ""
    return normalized


def _trusted_same_host_url(url: str, source_url: str) -> str:
    normalized = canonicalize_url(url)
    if normalize_host(normalized) != normalize_host(source_url):
        return ""
    if not is_crawlable_url(normalized) or not is_public_web_url(normalized):
        return ""
    return normalized


def _within_source_scope(url: str, source_url: str) -> bool:
    source_path = urllib.parse.urlparse(source_url).path.rstrip("/")
    if not source_path or source_path == "/":
        return True
    candidate_path = urllib.parse.urlparse(url).path.rstrip("/")
    return candidate_path == source_path or candidate_path.startswith(source_path + "/")


def _default_sitemap_urls(source_url: str) -> list[str]:
    parsed = urllib.parse.urlparse(source_url)
    origin = parsed._replace(path="", params="", query="", fragment="").geturl().rstrip("/")
    return dedupe_urls([f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"])


def _normalize_source(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if not parsed.scheme:
        raw = f"https://{raw}"
        parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.scheme == "http":
        parsed = parsed._replace(scheme="https")
    normalized = canonicalize_url(parsed.geturl())
    return normalized if is_public_web_url(normalized) else ""


def _label_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return site_name_from_url(url)
    leaf = path.split("/")[-1] or path
    label = re.sub(r"[-_]+", " ", leaf).strip()
    return _clean_label(label) or path


def _clean_label(value: str) -> str:
    return " ".join(value.split())[:120]


def _is_toc_container(tag: str, attrs: list[tuple[str, str | None]]) -> bool:
    if tag in {"nav", "aside"}:
        return True
    values = {
        key.lower(): value.lower()
        for key, value in attrs
        if value and key.lower() in {"aria-label", "class", "id", "role", "data-testid"}
    }
    if values.get("role") == "navigation":
        return True
    normalized = " ".join(values.values())
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    phrases = {
        "table of contents",
        "side nav",
        "side navigation",
        "docs nav",
        "docs navigation",
        "doc nav",
        "doc navigation",
    }
    phrase_source = re.sub(r"[-_]+", " ", normalized)
    return "toc" in tokens or any(phrase in phrase_source for phrase in phrases)


# Cap untrusted response bodies (sitemaps, nested sitemaps, landing HTML) so a
# hostile or compromised trusted-source host cannot drive a multi-GB read into
# memory. Mirrors the 5 MB feed cap in podcasts/feed.py. _try_fetch turns the
# ValueError into a clean empty-string degrade.
_MAX_FETCH_BYTES = 5_000_000


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with safe_urlopen(req, timeout=20, retries=1) as resp:
        data = resp.read(_MAX_FETCH_BYTES + 1)
    if len(data) > _MAX_FETCH_BYTES:
        raise ValueError(f"response from {url} exceeds the {_MAX_FETCH_BYTES:,}-byte cap")
    return data.decode("utf-8", "ignore")


def _try_fetch(fetch_text: FetchText, url: str) -> str:
    try:
        return fetch_text(url)
    except (NetworkError, OSError, UnicodeError, ValueError):
        return ""
