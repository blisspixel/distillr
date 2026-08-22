# pyright: strict
"""URL identity, crawl-scope, and bounded crawl-option helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import urlparse

from distill.ingestors.net import is_public_web_url, url_for_persistence
from distill.library.paths import slugify_title
from distill.youtube_urls import normalize_youtube_video_url

MAX_SITE_CRAWL_DEPTH = 4
MAX_SITE_CRAWL_PAGES = 100
MAX_SITE_BATCH_PAGES = 500


class CrawlSeedScope(Protocol):
    """Minimum seed fields required to evaluate a candidate crawl URL."""

    url: str
    crawl_prefix: str
    same_section_only: bool


def page_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    base = parsed.path.strip("/") or (parsed.hostname or "page")
    return slugify_title(base, max_len=20)


def site_page_id(url: str) -> str:
    """Return a stable allocator key for a landed page URL."""

    canonical_url = canonicalize_url(url)
    return sha256(canonical_url.encode("utf-8")).hexdigest()


def crawl_prefix_from_url(url: str) -> str:
    return normalized_crawl_prefix(urlparse(url).path)


def crawl_prefix_from_mapping(data: Mapping[str, Any], fallback: str = "") -> str:
    raw = data.get("crawl_prefix", data.get("path_prefix", fallback))
    return normalized_crawl_prefix(str(raw or ""))


def crawl_mode(data: Mapping[str, Any]) -> str:
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


def crawl_max_depth(data: Mapping[str, Any], *, default: object) -> int:
    if crawl_mode(data) == "exact-page":
        return 0
    return validated_crawl_limit(
        "max_depth",
        data.get("max_depth", default),
        minimum=0,
        maximum=MAX_SITE_CRAWL_DEPTH,
    )


def crawl_max_pages(data: Mapping[str, Any], *, default: object) -> int:
    if crawl_mode(data) == "exact-page":
        return 1
    return validated_crawl_limit(
        "max_pages",
        data.get("max_pages", data.get("max_pages_per_seed", default)),
        minimum=1,
        maximum=MAX_SITE_CRAWL_PAGES,
    )


def validate_site_crawl_limits(max_depth: object, max_pages: object) -> None:
    validated_crawl_limit(
        "max_depth",
        max_depth,
        minimum=0,
        maximum=MAX_SITE_CRAWL_DEPTH,
    )
    validated_crawl_limit(
        "max_pages",
        max_pages,
        minimum=1,
        maximum=MAX_SITE_CRAWL_PAGES,
    )


def validated_crawl_limit(
    name: str,
    value: object,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def normalized_crawl_prefix(value: str) -> str:
    raw = value.strip()
    if "://" in raw:
        raw = urlparse(raw).path
    tokens = [token for token in raw.strip("/").split("/") if token]
    if not tokens:
        return ""
    return "/" + "/".join(tokens)


def is_within_crawl_prefix(url: str, crawl_prefix: str) -> bool:
    prefix = normalized_crawl_prefix(crawl_prefix)
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
        query = "&".join(filter(None, keep))
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        fragment="",
        query=query,
        path=path,
    )
    return normalized.geturl()


def site_url_for_persistence(url: str) -> str:
    """Return the query-free site URL view used by storage and model boundaries."""

    if not url:
        return ""
    return url_for_persistence(canonicalize_url(url))


def site_embedded_url_for_persistence(url: str) -> str:
    """Preserve only a validated YouTube video identity in an embedded URL."""

    return normalize_youtube_video_url(url) or site_url_for_persistence(url)


def site_url_list_for_persistence(urls: Sequence[str]) -> list[str]:
    """Sanitize and order-dedupe a page's embedded URL inventory."""

    sanitized: list[str] = []
    seen: set[str] = set()
    for url in urls:
        safe_url = site_embedded_url_for_persistence(url)
        if not safe_url or safe_url == "<invalid-url>" or safe_url in seen:
            continue
        seen.add(safe_url)
        sanitized.append(safe_url)
    return sanitized


def site_attachment_context_for_persistence(
    context: str,
    urls: Sequence[str],
) -> str:
    """Replace attachment header URLs with their safe embedded identities."""

    replacements: dict[str, str] = {}
    for raw_url in urls:
        replacements[raw_url] = site_embedded_url_for_persistence(raw_url)
        normalized_video = normalize_youtube_video_url(raw_url)
        if normalized_video:
            replacements[normalized_video] = normalized_video
    for raw_url in sorted(replacements, key=len, reverse=True):
        if raw_url:
            context = context.replace(raw_url, replacements[raw_url])
    return context


def normalize_host(url: str) -> str:
    host = urlparse(site_url_for_persistence(url)).netloc.lower()
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


def canonical_url_in_seed_scope(
    url: str,
    *,
    seed: CrawlSeedScope,
    root_host: str,
) -> str | None:
    """Return a canonical public HTTPS URL confined to the seed's crawl scope."""

    if urlparse(url).scheme.lower() != "https":
        return None
    if normalize_host(url) != root_host or not is_public_web_url(url):
        return None
    if not is_crawlable_url(url):
        return None
    normalized = canonicalize_url(url)
    if seed.crawl_prefix and not is_within_crawl_prefix(normalized, seed.crawl_prefix):
        return None
    if seed.same_section_only and not is_same_section(normalized, seed.url):
        return None
    return normalized


def link_is_crawlable_for_seed(
    link: str,
    *,
    seed: CrawlSeedScope,
    root_host: str,
    visited: set[str],
) -> str | None:
    """Return a new canonical URL when a link stays inside the crawl scope."""

    normalized = canonical_url_in_seed_scope(link, seed=seed, root_host=root_host)
    if normalized is None or normalized in visited:
        return None
    return normalized


def prioritize_links(links: list[str], seed_url: str, current_url: str) -> list[str]:
    return sorted(
        dedupe_urls(links),
        key=lambda link: (
            -link_relevance_score(link, seed_url, current_url),
            len(urlparse(link).path),
            link,
        ),
    )


def link_relevance_score(link: str, seed_url: str, current_url: str) -> int:
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


def dedupe_strings(values: list[str]) -> list[str]:
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
