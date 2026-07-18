"""Browser-first website crawling and page extraction for Distill."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from distill.ingestors.browser_network import install_public_web_route
from distill.ingestors.sites._site_render import build_page_document, classify_page_type
from distill.ingestors.sites._site_urls import (
    MAX_SITE_BATCH_PAGES,
    MAX_SITE_CRAWL_DEPTH,
    MAX_SITE_CRAWL_PAGES,
    canonicalize_url,
    crawl_prefix_from_url,
    dedupe_urls,
    is_crawlable_url,
    is_same_section,
    normalize_host,
    page_id_from_url,
    site_page_id,
    site_section_key,
)
from distill.ingestors.sites._site_urls import (
    canonical_url_in_seed_scope as _canonical_url_in_seed_scope,
)
from distill.ingestors.sites._site_urls import (
    crawl_max_depth as _crawl_max_depth,
)
from distill.ingestors.sites._site_urls import (
    crawl_max_pages as _crawl_max_pages,
)
from distill.ingestors.sites._site_urls import (
    crawl_prefix_from_mapping as _crawl_prefix_from_mapping,
)
from distill.ingestors.sites._site_urls import (
    dedupe_strings as _dedupe_strings,
)
from distill.ingestors.sites._site_urls import (
    link_is_crawlable_for_seed as _link_is_crawlable_for_seed,
)
from distill.ingestors.sites._site_urls import (
    normalized_crawl_prefix as _normalize_crawl_prefix,
)
from distill.ingestors.sites._site_urls import (
    prioritize_links as _prioritize_links,
)
from distill.ingestors.sites._site_urls import (
    validate_site_crawl_limits as _validate_site_crawl_limits,
)
from distill.ingestors.sites.browser_extract import (
    bounded_page_expression,
    evaluate_bounded_page,
)
from distill.ingestors.sites.pinned_proxy import PinnedBrowserProxy
from distill.library.confined import read_confined_bytes
from distill.library.paths import site_name_from_url
from distill.process_resources import (
    ProcessBudgetExceeded,
    assign_windows_memory_job,
    close_windows_job,
    start_bounded_pipe_drain,
    terminate_process_tree,
    wait_for_process_budget,
)
from distill.process_security import package_install_context

logger = logging.getLogger(__name__)

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
    "parse_site_batch_json",
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
_BROWSER_TREE_MEMORY_BYTES = 768 * 1024 * 1024
_BROWSER_WORKER_TIMEOUT_SECONDS = 180.0
BROWSER_WORKER_RESULT_BYTES = 64 * 1024 * 1024
_BROWSER_WORKER_DIAGNOSTIC_BYTES = 8_192
BROWSER_WORKER_SCHEMA_VERSION = 1
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
_MAX_SITE_BATCH_MANIFEST_SEEDS = 500
_MAX_SITE_BATCH_MANIFEST_TEXT_CHARS = 4_096

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
        return parse_site_batch_json(path.read_text(encoding="utf-8"), topic_override)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    urls = [line for line in lines if line and not line.startswith("#")]
    topic = topic_override or "web"
    return SiteBatch(topic=topic, seeds=[SiteSeed(url=url, topic=topic) for url in urls])


def parse_site_batch_json(content: str, topic_override: str = "") -> SiteBatch:
    """Parse one bounded-shape JSON site manifest from already-read text."""

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Site seed manifest must contain valid JSON.") from exc
    _validate_site_batch_manifest(data)
    return _batch_from_json(data, topic_override)


def _validate_site_batch_manifest(data: object) -> None:
    if isinstance(data, list):
        _validate_manifest_items(data, context="urls")
        return
    if not isinstance(data, dict):
        raise ValueError("Site seed manifest must be a JSON object or array.")

    _validate_site_batch_object(data)


def _validate_site_batch_object(data: dict[object, object]) -> None:
    _validate_manifest_text(data.get("topic", "web"), field_name="topic")
    crawl = data.get("crawl", {})
    if not isinstance(crawl, dict):
        raise ValueError("Site seed manifest field 'crawl' must be an object.")
    _validate_manifest_mapping(crawl, context="crawl")

    raw_urls = data.get("urls", [])
    raw_collections = data.get("collections", [])
    if not isinstance(raw_urls, list):
        raise ValueError("Site seed manifest field 'urls' must be an array.")
    if not isinstance(raw_collections, list):
        raise ValueError("Site seed manifest field 'collections' must be an array.")
    if raw_urls and raw_collections:
        raise ValueError("Site seed manifest must use either 'urls' or 'collections', not both.")
    if len(raw_collections) > _MAX_SITE_BATCH_MANIFEST_SEEDS:
        raise ValueError("Site seed manifest has too many collections.")
    _validate_manifest_items(raw_urls, context="urls")
    _validate_manifest_collections(raw_collections, initial_seed_count=len(raw_urls))


def _validate_manifest_collections(
    raw_collections: list[object],
    *,
    initial_seed_count: int,
) -> None:
    total_seeds = initial_seed_count
    for index, raw_collection in enumerate(raw_collections):
        if not isinstance(raw_collection, dict):
            raise ValueError(f"Site seed collection {index + 1} must be an object.")
        _validate_manifest_mapping(raw_collection, context=f"collection {index + 1}")
        seeds = raw_collection.get("seeds", [])
        if not isinstance(seeds, list):
            raise ValueError(f"Site seed collection {index + 1} field 'seeds' must be an array.")
        total_seeds += len(seeds)
        if total_seeds > _MAX_SITE_BATCH_MANIFEST_SEEDS:
            raise ValueError("Site seed manifest has too many seeds.")
        for seed_index, seed in enumerate(seeds):
            if not isinstance(seed, str) or not seed:
                raise ValueError(
                    f"Site seed collection {index + 1} entry {seed_index + 1} must be a URL string."
                )
            _validate_manifest_text(seed, field_name="url")


def _validate_manifest_items(items: list[object], *, context: str) -> None:
    if len(items) > _MAX_SITE_BATCH_MANIFEST_SEEDS:
        raise ValueError("Site seed manifest has too many seeds.")
    for index, item in enumerate(items):
        if isinstance(item, str):
            if not item:
                raise ValueError(f"Site seed {context} entry {index + 1} must not be empty.")
            _validate_manifest_text(item, field_name="url")
            continue
        if not isinstance(item, dict):
            raise ValueError(f"Site seed {context} entry {index + 1} must be a URL or object.")
        _validate_manifest_mapping(item, context=f"{context} entry {index + 1}")
        url = item.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError(f"Site seed {context} entry {index + 1} requires a URL string.")
        _validate_manifest_text(url, field_name="url")


def _validate_manifest_mapping(data: dict[object, object], *, context: str) -> None:
    text_fields = {
        "topic",
        "site_name",
        "label",
        "name",
        "section_label",
        "source_hint",
        "freshness_hint",
        "crawl_prefix",
        "path_prefix",
        "mode",
        "crawl_mode",
    }
    boolean_fields = {"discover_crawl", "same_section_only"}
    integer_fields = {"max_depth", "max_pages", "max_pages_per_seed"}
    for field_name in text_fields:
        if field_name in data:
            _validate_manifest_text(data[field_name], field_name=field_name)
    for field_name in boolean_fields:
        if field_name in data and not isinstance(data[field_name], bool):
            raise ValueError(f"Site seed {context} field '{field_name}' must be a boolean.")
    if "crawl" in data and not isinstance(data["crawl"], bool):
        raise ValueError(f"Site seed {context} field 'crawl' must be a boolean.")
    for field_name in integer_fields:
        if field_name in data and (
            not isinstance(data[field_name], int) or isinstance(data[field_name], bool)
        ):
            raise ValueError(f"Site seed {context} field '{field_name}' must be an integer.")


def _validate_manifest_text(value: object, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"Site seed manifest field '{field_name}' must be a string.")
    if len(value) > _MAX_SITE_BATCH_MANIFEST_TEXT_CHARS:
        raise ValueError(f"Site seed manifest field '{field_name}' is too long.")


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


def _install_public_web_route(context):
    """Abort non-HTTPS or non-public requests before they reach the pinned proxy."""
    return install_public_web_route(context)


def _seed_is_crawlable(seed: SiteSeed) -> bool:
    from distill.ingestors.net import is_public_web_url

    _validate_site_crawl_limits(seed.max_depth, seed.max_pages)
    return not (
        urlparse(seed.url).scheme.lower() != "https"
        or not is_public_web_url(seed.url)
        or not is_crawlable_url(seed.url)
    )


def crawl_site(seed: SiteSeed) -> list[SitePage]:
    """Crawl one seed in an isolated, memory-limited browser worker."""

    if not _seed_is_crawlable(seed):
        return []
    return _run_browser_worker(seed)


def _worker_string(row: dict[str, Any], key: str, maximum: int) -> str:
    value = row.get(key, "")
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"browser worker returned invalid {key}")
    return value


def _worker_strings(
    row: dict[str, Any],
    key: str,
    *,
    maximum_items: int,
    maximum_chars: int,
) -> list[str]:
    values = row.get(key, [])
    if not isinstance(values, list) or len(values) > maximum_items:
        raise ValueError(f"browser worker returned invalid {key}")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or len(value) > maximum_chars:
            raise ValueError(f"browser worker returned invalid {key}")
        result.append(value)
    return result


def _site_page_from_worker(row: object) -> SitePage:
    if not isinstance(row, dict):
        raise ValueError("browser worker returned a malformed page")
    typed = {str(key): value for key, value in row.items()}
    has_video = typed.get("has_video", False)
    depth = typed.get("depth", 0)
    if not isinstance(has_video, bool):
        raise ValueError("browser worker returned invalid has_video")
    if isinstance(depth, bool) or not isinstance(depth, int) or not 0 <= depth <= 4:
        raise ValueError("browser worker returned invalid depth")
    reasons = _worker_strings(
        typed,
        "truncation_reasons",
        maximum_items=len(_EXTRACTION_TRUNCATION_REASONS),
        maximum_chars=32,
    )
    if any(reason not in _EXTRACTION_TRUNCATION_REASONS for reason in reasons):
        raise ValueError("browser worker returned invalid truncation reasons")
    return SitePage(
        url=_worker_string(typed, "url", _PAGE_URL_CHAR_LIMIT),
        title=_worker_string(typed, "title", _PAGE_TITLE_CHAR_LIMIT),
        site_name=_worker_string(typed, "site_name", 253),
        page_type=_worker_string(typed, "page_type", 64),
        text=_worker_string(typed, "text", _TEXT_LIMIT),
        final_url=_worker_string(typed, "final_url", _PAGE_URL_CHAR_LIMIT),
        canonical_url=_worker_string(typed, "canonical_url", _PAGE_URL_CHAR_LIMIT),
        description=_worker_string(typed, "description", _PAGE_DESCRIPTION_CHAR_LIMIT),
        published_at=_worker_string(typed, "published_at", _PAGE_PUBLISHED_AT_CHAR_LIMIT),
        authors=_worker_strings(
            typed,
            "authors",
            maximum_items=_PAGE_AUTHOR_LIMIT,
            maximum_chars=512,
        ),
        tags=_worker_strings(
            typed,
            "tags",
            maximum_items=_PAGE_TAG_LIMIT,
            maximum_chars=256,
        ),
        links=_worker_strings(
            typed,
            "links",
            maximum_items=_PAGE_LINK_LIMIT,
            maximum_chars=_PAGE_URL_CHAR_LIMIT,
        ),
        pdf_links=_worker_strings(
            typed,
            "pdf_links",
            maximum_items=_PAGE_PDF_LINK_LIMIT,
            maximum_chars=_PAGE_URL_CHAR_LIMIT,
        ),
        video_links=_worker_strings(
            typed,
            "video_links",
            maximum_items=_PAGE_VIDEO_LINK_LIMIT,
            maximum_chars=_PAGE_URL_CHAR_LIMIT,
        ),
        has_video=has_video,
        transcript=_worker_string(typed, "transcript", _TRANSCRIPT_LIMIT),
        attachment_context=_worker_string(typed, "attachment_context", _TEXT_LIMIT),
        truncation_reasons=reasons,
        source_url=_worker_string(typed, "source_url", _PAGE_URL_CHAR_LIMIT),
        depth=depth,
    )


def _read_browser_worker_result(path: Path, root: Path, max_pages: int) -> list[SitePage]:
    raw = read_confined_bytes(path, root, max_bytes=BROWSER_WORKER_RESULT_BYTES)
    if raw is None:
        raise ValueError("browser worker result is missing or unsafe")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("browser worker result is not valid JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != BROWSER_WORKER_SCHEMA_VERSION
        or not isinstance(payload.get("pages"), list)
        or len(payload["pages"]) > max_pages
    ):
        raise ValueError("browser worker result has an invalid schema")
    return [_site_page_from_worker(row) for row in payload["pages"]]


def _run_browser_worker(seed: SiteSeed) -> list[SitePage]:
    with tempfile.TemporaryDirectory(prefix="distill-browser-") as temp_dir:
        root = Path(temp_dir)
        input_path = root / "seed.json"
        output_path = root / "pages.json"
        input_path.write_text(
            json.dumps(asdict(seed), ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        trusted_cwd, child_env = package_install_context()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                sys.executable,
                "-P",
                "-m",
                "distill.ingestors.sites._browser_worker",
                str(input_path),
                str(output_path),
            ],
            cwd=trusted_cwd,
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        stderr_stream = process.stderr
        if stderr_stream is None:
            terminate_process_tree(process)
            return []
        diagnostic_tail, diagnostic_thread = start_bounded_pipe_drain(
            stderr_stream,
            limit=_BROWSER_WORKER_DIAGNOSTIC_BYTES,
            thread_name="distill-browser-diagnostics",
        )
        job_handle: int | None = None
        try:
            job_handle = assign_windows_memory_job(
                process,
                job_memory_bytes=_BROWSER_TREE_MEMORY_BYTES,
            )
            worker_stdin = process.stdin
            if worker_stdin is None:
                raise RuntimeError("browser worker did not expose a control pipe")
            worker_stdin.write(b"1")
            worker_stdin.close()
            process.stdin = None
            wait_for_process_budget(
                process,
                timeout_seconds=_BROWSER_WORKER_TIMEOUT_SECONDS,
                memory_limit_bytes=_BROWSER_TREE_MEMORY_BYTES,
            )
        except (ProcessBudgetExceeded, OSError, RuntimeError) as exc:
            logger.warning("Browser crawl stopped at its resource boundary: %s", exc)
            terminate_process_tree(process)
            return []
        finally:
            close_windows_job(job_handle)
            diagnostic_thread.join(timeout=1)
            with contextlib.suppress(OSError):
                stderr_stream.close()
            diagnostic_thread.join(timeout=1)

        if process.returncode != 0:
            detail = diagnostic_tail.bytes().decode("utf-8", errors="replace").strip()[-500:]
            if detail:
                logger.warning("Browser crawl worker failed: %s", detail)
            return []
        try:
            return _read_browser_worker_result(output_path, root, seed.max_pages)
        except ValueError as exc:
            logger.warning("Browser crawl worker returned an invalid result: %s", exc)
            return []


def crawl_site_in_browser_worker(seed: SiteSeed) -> list[SitePage]:
    """Browser-worker implementation; callers should use :func:`crawl_site`."""

    if not _seed_is_crawlable(seed):
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
                "--disable-background-networking",
                "--disable-extensions",
                "--disable-quic",
                "--disable-sync",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--metrics-recording-only",
                "--no-first-run",
            ],
        )
        try:
            context = browser.new_context(
                proxy={"server": proxy_server},
                service_workers="block",
                accept_downloads=False,
                extra_http_headers={"Accept-Encoding": "identity"},
            )
            try:
                request_budget = _install_public_web_route(context)
                while queue and len(pages) < seed.max_pages:
                    current_url, depth, source_url = queue.popleft()
                    normalized = canonicalize_url(current_url)
                    if normalized in visited:
                        continue
                    visited.add(normalized)
                    request_budget.reset()
                    page = context.new_page()
                    page.set_default_timeout(30_000)
                    try:
                        extracted = _extract_page(
                            page,
                            normalized,
                            seed.resolved_site_name(),
                            source_url,
                            depth,
                        )
                    finally:
                        with contextlib.suppress(Exception):
                            page.close()
                    if extracted is None:
                        continue
                    landed = extracted.final_url or extracted.url
                    if (
                        _canonical_url_in_seed_scope(
                            landed,
                            seed=seed,
                            root_host=root_host,
                        )
                        is None
                    ):
                        continue
                    pages.append(extracted)

                    if depth >= seed.max_depth:
                        continue

                    for link in _prioritize_links(extracted.links, seed.url, normalized):
                        link_norm = _link_is_crawlable_for_seed(
                            link,
                            seed=seed,
                            root_host=root_host,
                            visited=visited,
                        )
                        if link_norm is not None:
                            queue.append((link_norm, depth + 1, normalized))
            finally:
                context.close()
        finally:
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


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().strip("-|")


def _clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    filtered = [line for line in lines if line and len(line) > 1]
    return "\n".join(filtered)[:_TEXT_LIMIT].strip()
