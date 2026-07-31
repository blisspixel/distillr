# pyright: strict
"""MCP tools -- sites: scrape and analyze pages from a site."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

import idna
from mcp.server.fastmcp import Context

from distill.commands._site_ingest import SiteIngestResult
from distill.library.confined import read_confined_text, validate_confined_path
from distill.llm.availability import model_available
from distill.mcp.server import (
    capped_tracker,
    cost_summary,
    load_config,
    mcp,
    refuse_if_host_not_allowed,
    write_tool,
    write_tool_annotations,
)
from distill.pipeline.costs import BudgetExceededError

__all__: list[str] = []

_MAX_SEED_FILE_BYTES = 1_000_000
_MAX_SITE_BATCH_URLS = 50
_MAX_SITE_URL_CHARS = 2_048
_SITE_SEED_NAMESPACE = "site-seeds"

type SiteBatchPageRow = dict[str, str | int]


def _resolve_seed_file(library_dir: Path, seed_file: str) -> Path | None:
    if not seed_file or "\x00" in seed_file or "\\" in seed_file:
        return None
    windows_path = PureWindowsPath(seed_file)
    posix_path = PurePosixPath(seed_file)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or len(posix_path.parts) < 2
        or posix_path.parts[0] != _SITE_SEED_NAMESPACE
        or any(part in {"", ".", ".."} for part in posix_path.parts)
        or posix_path.suffix.casefold() != ".json"
    ):
        return None
    try:
        root = (library_dir / _SITE_SEED_NAMESPACE).resolve(strict=True)
        candidate = root.joinpath(*posix_path.parts[1:])
    except (OSError, ValueError):
        return None
    validated = validate_confined_path(candidate, root, expect_directory=False)
    if validated is None or validated[1].st_size > _MAX_SEED_FILE_BYTES:
        return None
    return validated[0]


def _is_public_https_seed_url(url: object) -> bool:
    """Validate the non-network portion of the MCP seed URL contract."""

    if not isinstance(url, str) or not url or len(url) > _MAX_SITE_URL_CHARS:
        return False
    if any(ord(char) < 32 for char in url) or "\\" in url:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").rstrip(".")
        _ = parsed.port
    except ValueError:
        return False
    if parsed.scheme.casefold() != "https" or not host or parsed.username or parsed.password:
        return False
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        try:
            ascii_host = idna.encode(host, uts46=True, std3_rules=True).decode("ascii").casefold()
        except (UnicodeError, idna.IDNAError):
            return False
    else:
        return literal.is_global
    if ascii_host in {"localhost", "ip6-localhost", "ip6-loopback"} or ascii_host.endswith(
        (".localhost", ".local", ".internal", ".home.arpa")
    ):
        return False
    return "." in ascii_host


def _site_result_parts(
    site_result: SiteIngestResult | tuple[str, int],
) -> tuple[str, int, int | None, int | None]:
    if isinstance(site_result, SiteIngestResult):
        return (
            site_result.site_name,
            site_result.page_count,
            site_result.analyzed_pages,
            site_result.skipped_pages,
        )

    site_name, page_count = site_result
    return site_name, page_count, None, None


@mcp.tool(annotations=write_tool_annotations(destructive=False, idempotent=False, open_world=True))
@write_tool("site_batch", allow_preview=True, ledger_command="site-batch")
async def site_batch(  # noqa: C901 - legacy site workflow
    topic: str,
    urls: list[str] | None = None,
    seed_file: str | None = None,
    seed_only: bool = False,
    same_section_only: bool = False,
    preview: bool = False,
    ctx: Context[Any, Any, Any] | None = None,
) -> str:
    """Scrape and analyze pages from a site seed file or URL list.

    Args:
        topic: Topic to file pages under
        urls: List of URLs to process
        seed_file: Path to a seed file with URLs
        seed_only: Force exact-page processing for seed-file entries
        same_section_only: Keep shallow crawls within the seed section
        preview: Return the resolved plan without model checks, crawling, or writes
    """
    config = load_config()

    try:
        from distill.commands._site_batch import (
            resolve_site_batch_seeds,
            site_batch_plan_payload,
        )
        from distill.commands._site_ingest import process_site_seed
        from distill.ingestors.sites.scraper import SiteSeed, parse_site_batch_json
        from distill.pipeline.summary import RunSummary
    except ImportError as e:
        return json.dumps({"status": "error", "error": f"Site dependencies missing: {e}"})

    seeds: list[SiteSeed] = []
    if urls:
        if len(urls) > _MAX_SITE_BATCH_URLS:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"urls must contain at most {_MAX_SITE_BATCH_URLS} entries.",
                }
            )
        if any(not _is_public_https_seed_url(url) for url in urls):
            return json.dumps(
                {"status": "error", "error": "Every URL must be a bounded public HTTPS URL."}
            )
        seeds = [SiteSeed(url=url, topic=topic, max_depth=0, max_pages=1) for url in urls]
    elif seed_file:
        seed_path = _resolve_seed_file(config.library_dir, seed_file)
        if seed_path is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": (
                        "seed_file must be a bounded JSON file inside the "
                        "library/site-seeds namespace."
                    ),
                }
            )
        manifest_root = config.library_dir / _SITE_SEED_NAMESPACE
        manifest = read_confined_text(seed_path, manifest_root, max_bytes=_MAX_SEED_FILE_BYTES)
        if manifest is None:
            return json.dumps({"status": "error", "error": "Seed manifest is unavailable."})
        try:
            parsed_seeds = parse_site_batch_json(manifest, topic_override=topic).seeds
            if len(parsed_seeds) > _MAX_SITE_BATCH_URLS:
                return json.dumps(
                    {
                        "status": "error",
                        "error": f"Seed manifest must contain at most {_MAX_SITE_BATCH_URLS} entries.",
                    }
                )
            if any(not _is_public_https_seed_url(seed.url) for seed in parsed_seeds):
                return json.dumps(
                    {
                        "status": "error",
                        "error": "Seed manifest contains an invalid or non-public HTTPS URL.",
                    }
                )
            seeds = [
                SiteSeed(
                    url=seed.url,
                    topic=topic,
                    site_name=seed.site_name,
                    label=seed.label,
                    section_label=seed.section_label,
                    source_hint=seed.source_hint,
                    freshness_hint=seed.freshness_hint,
                    crawl_prefix=seed.crawl_prefix,
                    discover_crawl=seed.discover_crawl,
                    max_depth=seed.max_depth,
                    max_pages=seed.max_pages,
                    same_section_only=seed.same_section_only,
                )
                for seed in parsed_seeds
            ]
        except (TypeError, ValueError) as e:
            return json.dumps({"status": "error", "error": str(e)})
    else:
        return json.dumps({"status": "error", "error": "Provide either 'urls' or 'seed_file'."})

    try:
        seeds = resolve_site_batch_seeds(
            seeds,
            seed_only=seed_only,
            same_section_only=same_section_only,
        )
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)})

    if not seeds:
        return json.dumps({"status": "error", "error": "No URLs to process."})

    for seed in seeds:
        refusal = refuse_if_host_not_allowed(seed.url)
        if refusal is not None:
            return refusal

    if preview:
        return json.dumps(
            {
                "status": "preview",
                "plan": site_batch_plan_payload(topic=topic, seeds=seeds),
            },
            indent=2,
        )

    if not model_available():
        return json.dumps(
            {
                "status": "error",
                "error": "No model configured (set a cloud key or DISTILL_PROVIDER).",
            }
        )

    tracker = capped_tracker()
    summary = RunSummary(command="site-batch")
    results: list[SiteBatchPageRow] = []

    for i, seed in enumerate(seeds):
        if ctx:
            await ctx.report_progress(progress=i, total=len(seeds))
        try:
            site_result: SiteIngestResult | tuple[str, int] = process_site_seed(
                seed, config, tracker, summary
            )
            site_name, page_count, analyzed_pages, skipped_pages = _site_result_parts(site_result)
            page_result: SiteBatchPageRow = {
                "url": seed.url,
                "site": site_name,
                "pages": page_count,
                "status": "ok" if page_count else "skipped",
            }
            if isinstance(analyzed_pages, int) and isinstance(skipped_pages, int):
                page_result["analyzed_pages"] = analyzed_pages
                page_result["skipped_pages"] = skipped_pages
                if page_count and skipped_pages == page_count and not analyzed_pages:
                    page_result["status"] = "unchanged"
            results.append(page_result)
        except BudgetExceededError:
            raise  # the per-call spend cap is a hard stop; write_tool answers
        except Exception as e:
            results.append({"url": seed.url, "status": "error", "error": str(e)})

    if ctx:
        await ctx.report_progress(progress=len(seeds), total=len(seeds))

    return json.dumps(
        {
            "status": "complete",
            "pages": results,
            "count": len(results),
            "cost": cost_summary(tracker),
        },
        indent=2,
    )
