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
    dedupe_strings as _dedupe_strings,
)
from distill.ingestors.sites._site_urls import (
    link_is_crawlable_for_seed as _link_is_crawlable_for_seed,
)
from distill.ingestors.sites._site_urls import (
    prioritize_links as _prioritize_links,
)
from distill.ingestors.sites._site_urls import (
    validate_site_crawl_limits as _validate_site_crawl_limits,
)
from distill.ingestors.sites.batch import (
    load_site_batch,
    parse_site_batch_json,
)
from distill.ingestors.sites.browser_extract import (
    bounded_page_expression,
    evaluate_bounded_page,
)
from distill.ingestors.sites.capture import (
    CAPTURE_FAILURE_DETAIL_CHARS,
    CaptureFailure,
    capture_failure_from_worker,
    summarize_capture_failures,
)
from distill.ingestors.sites.pinned_proxy import PinnedBrowserProxy
from distill.ingestors.sites.records import SiteBatch, SitePage, SiteSeed
from distill.library.confined import read_confined_bytes
from distill.process_resources import (
    ProcessBudgetExceeded,
    assign_windows_memory_job,
    close_windows_job,
    start_bounded_pipe_drain,
    terminate_isolated_process_tree,
    wait_for_process_budget,
)
from distill.process_security import package_install_context

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_SITE_BATCH_PAGES",
    "MAX_SITE_CRAWL_DEPTH",
    "MAX_SITE_CRAWL_PAGES",
    "CaptureFailure",
    "SiteBatch",
    "SiteCrawlResult",
    "SitePage",
    "SiteSeed",
    "build_page_document",
    "canonicalize_url",
    "classify_page_type",
    "crawl_prefix_from_url",
    "crawl_site",
    "crawl_site_with_receipts",
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
# 2 adds the `failures` capture-receipt array alongside `pages`.
BROWSER_WORKER_SCHEMA_VERSION = 2
# Receipts are bounded independently of the visit ceiling below, so a worker
# that somehow reports more failures than it could have attempted still cannot
# grow the result without limit.
_MAX_WORKER_FAILURES = MAX_SITE_CRAWL_PAGES * 4
# Network quiescence budget before the bounded extractor runs. A hydrating
# single-page app is captured half-built without it; a static page should not
# pay the whole budget, so this is a ceiling, not a sleep.
_PAGE_NETWORK_IDLE_TIMEOUT_MS = 5_000
_PAGE_SETTLE_TIMEOUT_MS = 400
_PAGE_SCROLL_SETTLE_TIMEOUT_MS = 250
_PAGE_SCROLL_PASSES = 3
# ``max_pages`` bounds captured pages, but a page that fails to capture does not
# advance that count, so a crawl whose pages all fail would keep draining a
# frontier of up to _PAGE_LINK_LIMIT links per parent. That both exceeds the
# operator's stated bound and hammers the host, so attempted visits carry their
# own ceiling proportional to what the operator asked for.
_VISIT_CEILING_MULTIPLIER = 3
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


def _install_public_web_route(context):
    """Abort non-HTTPS or non-public requests before they reach the pinned proxy."""
    return install_public_web_route(context)


@dataclass(frozen=True)
class SiteCrawlResult:
    """Pages a crawl captured, plus a receipt for every URL it could not."""

    pages: list[SitePage] = field(default_factory=list)
    failures: list[CaptureFailure] = field(default_factory=list)

    @property
    def attempted(self) -> int:
        return len(self.pages) + len(self.failures)

    def failure_counts(self) -> dict[str, int]:
        return summarize_capture_failures(self.failures)

    def metadata(self) -> dict[str, Any]:
        """Render for the site manifest, with every receipt URL redacted."""
        return {
            "attempted_pages": self.attempted,
            "captured_pages": len(self.pages),
            "failed_pages": len(self.failures),
            "capture_failures": [failure.redacted().metadata() for failure in self.failures],
            "capture_failure_counts": self.failure_counts(),
        }


def _seed_is_crawlable(seed: SiteSeed) -> bool:
    from distill.ingestors.net import is_public_web_url

    _validate_site_crawl_limits(seed.max_depth, seed.max_pages)
    return not (
        urlparse(seed.url).scheme.lower() != "https"
        or not is_public_web_url(seed.url)
        or not is_crawlable_url(seed.url)
    )


def crawl_site(seed: SiteSeed) -> list[SitePage]:
    """Crawl one seed in an isolated, memory-limited browser worker.

    Returns only the captured pages. Use :func:`crawl_site_with_receipts` when
    the caller needs to know why a URL is missing.
    """

    return crawl_site_with_receipts(seed).pages


def crawl_site_with_receipts(seed: SiteSeed) -> SiteCrawlResult:
    """Crawl one seed, returning captured pages and a receipt per failed URL."""

    if not _seed_is_crawlable(seed):
        return SiteCrawlResult()
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


def _read_browser_worker_result(path: Path, root: Path, max_pages: int) -> SiteCrawlResult:
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
        or not isinstance(payload.get("failures"), list)
        or len(payload["failures"]) > _MAX_WORKER_FAILURES
    ):
        raise ValueError("browser worker result has an invalid schema")
    return SiteCrawlResult(
        pages=[_site_page_from_worker(row) for row in payload["pages"]],
        failures=[capture_failure_from_worker(row) for row in payload["failures"]],
    )


def _seed_failure(seed: SiteSeed, outcome: str, detail: str) -> SiteCrawlResult:
    """Record a whole-seed capture failure so the crawl never fails silently."""
    return SiteCrawlResult(
        failures=[
            CaptureFailure(
                url=seed.url,
                outcome=outcome,
                detail=detail[:CAPTURE_FAILURE_DETAIL_CHARS],
            )
        ]
    )


def _run_browser_worker(seed: SiteSeed) -> SiteCrawlResult:
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
            terminate_isolated_process_tree(process)
            return _seed_failure(
                seed,
                "worker-failed",
                "browser worker did not expose a diagnostic pipe",
            )
        diagnostic_tail = None
        diagnostic_thread = None
        job_handle: int | None = None
        try:
            diagnostic_tail, diagnostic_thread = start_bounded_pipe_drain(
                stderr_stream,
                limit=_BROWSER_WORKER_DIAGNOSTIC_BYTES,
                thread_name="distill-browser-diagnostics",
            )
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
            return _seed_failure(seed, "budget-exhausted", f"{type(exc).__name__}: {exc}")
        finally:
            terminate_isolated_process_tree(process)
            close_windows_job(job_handle)
            if diagnostic_thread is not None:
                diagnostic_thread.join(timeout=1)
            with contextlib.suppress(OSError):
                stderr_stream.close()
            if diagnostic_thread is not None:
                diagnostic_thread.join(timeout=1)

        if process.returncode != 0:
            detail = (
                diagnostic_tail.bytes().decode("utf-8", errors="replace").strip()[-500:]
                if diagnostic_tail is not None
                else ""
            )
            if detail:
                logger.warning("Browser crawl worker failed: %s", detail)
            return _seed_failure(
                seed,
                "worker-failed",
                detail or f"browser worker exited with code {process.returncode}",
            )
        try:
            return _read_browser_worker_result(output_path, root, seed.max_pages)
        except ValueError as exc:
            logger.warning("Browser crawl worker returned an invalid result: %s", exc)
            return _seed_failure(seed, "worker-failed", str(exc))


def _visit_crawl_url(
    context: Any,
    url: str,
    *,
    seed: SiteSeed,
    root_host: str,
    source_url: str,
    depth: int,
) -> tuple[SitePage | None, CaptureFailure | None]:
    """Capture one URL in a fresh page, returning either a page or a receipt."""
    page = context.new_page()
    page.set_default_timeout(30_000)
    try:
        extracted, failure = _extract_page(
            page,
            url,
            seed.resolved_site_name(),
            source_url,
            depth,
        )
    finally:
        with contextlib.suppress(Exception):
            page.close()
    if extracted is None:
        return None, failure
    landed = extracted.final_url or extracted.url
    if _canonical_url_in_seed_scope(landed, seed=seed, root_host=root_host) is None:
        return None, CaptureFailure(
            url=url,
            outcome="out-of-scope",
            detail="redirected outside the seed's allowed scope",
            depth=depth,
        )
    return extracted, None


def _enqueue_crawlable_links(
    queue: deque[tuple[str, int, str]],
    links: list[str],
    *,
    seed: SiteSeed,
    root_host: str,
    visited: set[str],
    current_url: str,
    depth: int,
) -> None:
    """Queue the in-scope links found on a captured page, in priority order."""
    for link in _prioritize_links(links, seed.url, current_url):
        link_norm = _link_is_crawlable_for_seed(
            link,
            seed=seed,
            root_host=root_host,
            visited=visited,
        )
        if link_norm is not None:
            queue.append((link_norm, depth + 1, current_url))


def crawl_site_in_browser_worker(seed: SiteSeed) -> SiteCrawlResult:
    """Browser-worker implementation; callers should use :func:`crawl_site`."""

    if not _seed_is_crawlable(seed):
        return SiteCrawlResult()

    from playwright.sync_api import sync_playwright

    root_host = normalize_host(seed.url)
    queue: deque[tuple[str, int, str]] = deque([(seed.url, 0, seed.url)])
    visited: set[str] = set()
    pages: list[SitePage] = []
    failures: list[CaptureFailure] = []

    def record_failure(failure: CaptureFailure) -> None:
        if len(failures) < _MAX_WORKER_FAILURES:
            failures.append(failure)

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
                visit_ceiling = seed.max_pages * _VISIT_CEILING_MULTIPLIER
                while queue and len(pages) < seed.max_pages:
                    if len(visited) >= visit_ceiling:
                        record_failure(
                            CaptureFailure(
                                url=seed.url,
                                outcome="budget-exhausted",
                                detail=(
                                    f"stopped after {len(visited)} attempted pages "
                                    f"for a {seed.max_pages} page budget"
                                ),
                            )
                        )
                        break
                    current_url, depth, source_url = queue.popleft()
                    normalized = canonicalize_url(current_url)
                    if normalized in visited:
                        continue
                    visited.add(normalized)
                    request_budget.reset()
                    extracted, failure = _visit_crawl_url(
                        context,
                        normalized,
                        seed=seed,
                        root_host=root_host,
                        source_url=source_url,
                        depth=depth,
                    )
                    if extracted is None:
                        if failure is not None:
                            record_failure(failure)
                        continue
                    pages.append(extracted)

                    if depth < seed.max_depth:
                        _enqueue_crawlable_links(
                            queue,
                            extracted.links,
                            seed=seed,
                            root_host=root_host,
                            visited=visited,
                            current_url=normalized,
                            depth=depth,
                        )
            finally:
                context.close()
        finally:
            browser.close()

    return SiteCrawlResult(pages=pages, failures=failures)


def _extract_bounded_page_payload(page: Any) -> dict[str, Any] | None:
    """Extract a bounded payload in a clean Chromium world with a hard deadline."""
    return evaluate_bounded_page(
        page,
        expression=_BOUNDED_PAGE_EXPRESSION,
        timeout_ms=_PAGE_EXTRACTION_TIMEOUT_MS,
    )


def _navigation_status(response: object) -> int:
    """Read an HTTP status from a navigation response without trusting it."""
    status = getattr(response, "status", None)
    if isinstance(status, bool) or not isinstance(status, int) or not 0 <= status <= 599:
        return 0
    return status


def _await_page_ready(page: Any) -> None:
    """Wait on observed network quiescence, not a fixed guess.

    ``domcontentloaded`` fires before a client-rendered page has its content, so
    a flat sleep either truncates a slow single-page app or taxes a static page.
    Network idle is the observed signal; it is bounded by a ceiling because some
    pages hold a connection open forever and would otherwise never settle.
    """
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=_PAGE_NETWORK_IDLE_TIMEOUT_MS)
    page.wait_for_timeout(_PAGE_SETTLE_TIMEOUT_MS)
    for _ in range(_PAGE_SCROLL_PASSES):
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(_PAGE_SCROLL_SETTLE_TIMEOUT_MS)


def _extract_page(
    page,
    url: str,
    site_name: str,
    source_url: str,
    depth: int,
) -> tuple[SitePage | None, CaptureFailure | None]:
    status = 0
    try:
        response = page.goto(url, wait_until="domcontentloaded")
        status = _navigation_status(response)
        _await_page_ready(page)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ")
        return None, CaptureFailure(
            url=url,
            outcome="navigation-failed",
            detail=detail[:CAPTURE_FAILURE_DETAIL_CHARS],
            status=status,
            depth=depth,
        )

    payload = _extract_bounded_page_payload(page)
    if payload is None:
        return None, CaptureFailure(
            url=url,
            outcome="extraction-failed",
            detail="the bounded page extractor did not return a result",
            status=status,
            depth=depth,
        )

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
        return None, CaptureFailure(
            url=url,
            outcome="empty",
            detail="the page rendered with no usable body text",
            status=status,
            depth=depth,
        )

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
    captured = SitePage(
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
    return captured, None


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
