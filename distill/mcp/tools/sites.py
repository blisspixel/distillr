"""MCP tools — sites: scrape and analyze pages from a site."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from mcp.server.fastmcp import Context

from distill.llm.availability import model_available
from distill.mcp import server as _server
from distill.pipeline.costs import BudgetExceededError, save_run_log

__all__: list[str] = []

_MAX_SEED_FILE_BYTES = 1_000_000
_MAX_SITE_BATCH_URLS = 50


def _resolve_seed_file(library_dir: Path, seed_file: str) -> Path | None:
    if not seed_file or "\x00" in seed_file:
        return None
    windows_path = PureWindowsPath(seed_file)
    if (
        PurePosixPath(seed_file).is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
    ):
        return None
    try:
        root = library_dir.resolve(strict=False)
        candidate = (root / seed_file).resolve(strict=False)
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None


@_server.mcp.tool()
@_server.write_tool("site_batch")
async def site_batch(  # noqa: C901
    topic: str,
    urls: list[str] | None = None,
    seed_file: str | None = None,
    seed_only: bool = False,
    same_section_only: bool = False,
    ctx: Context = None,
) -> str:
    """Scrape and analyze pages from a site seed file or URL list.

    Args:
        topic: Topic to file pages under
        urls: List of URLs to process
        seed_file: Path to a seed file with URLs
        seed_only: Force exact-page processing for seed-file entries
        same_section_only: Keep shallow crawls within the seed section
    """
    config = _server._config()
    if not model_available():
        return json.dumps(
            {
                "status": "error",
                "error": "No model configured (set a cloud key or DISTILL_PROVIDER).",
            }
        )

    try:
        from distill.commands._site_batch import resolve_site_batch_seeds
        from distill.commands._site_ingest import process_site_seed
        from distill.ingestors.sites.scraper import SiteSeed, load_site_batch
        from distill.pipeline.summary import RunSummary
    except ImportError as e:
        return json.dumps({"status": "error", "error": f"Site dependencies missing: {e}"})

    seeds: list[SiteSeed] = []
    if urls:
        seeds = [
            SiteSeed(url=url, topic=topic, max_depth=0, max_pages=1)
            for url in urls[:_MAX_SITE_BATCH_URLS]
        ]
    elif seed_file:
        seed_path = _resolve_seed_file(config.library_dir, seed_file)
        if seed_path is None:
            return json.dumps(
                {
                    "status": "error",
                    "error": "seed_file must be a relative file path inside the library root.",
                }
            )
        if seed_path.stat().st_size > _MAX_SEED_FILE_BYTES:
            return json.dumps({"status": "error", "error": "Seed file is too large."})
        try:
            if seed_path.suffix.lower() == ".json":
                seeds = load_site_batch(seed_path, topic_override=topic).seeds[
                    :_MAX_SITE_BATCH_URLS
                ]
            else:
                seeds = [
                    SiteSeed(url=line, topic=topic, max_depth=0, max_pages=1)
                    for line in (
                        raw.strip() for raw in seed_path.read_text(encoding="utf-8").splitlines()
                    )
                    if line and not line.startswith("#")
                ][:_MAX_SITE_BATCH_URLS]
        except ValueError as e:
            return json.dumps({"status": "error", "error": str(e)})
    else:
        return json.dumps({"status": "error", "error": "Provide either 'urls' or 'seed_file'."})

    seeds = resolve_site_batch_seeds(
        seeds,
        seed_only=seed_only,
        same_section_only=same_section_only,
    )

    if not seeds:
        return json.dumps({"status": "error", "error": "No URLs to process."})

    for seed in seeds:
        refusal = _server.refuse_if_host_not_allowed(seed.url)
        if refusal is not None:
            return refusal

    tracker = _server.capped_tracker()
    summary = RunSummary(command="site-batch")
    results = []

    for i, seed in enumerate(seeds):
        if ctx:
            await ctx.report_progress(progress=i, total=len(seeds))
        try:
            site_result = process_site_seed(seed, config, tracker, summary)
            site_name, page_count = site_result
            page_result = {
                "url": seed.url,
                "site": site_name,
                "pages": page_count,
                "status": "ok" if page_count else "skipped",
            }
            analyzed_pages = getattr(site_result, "analyzed_pages", None)
            skipped_pages = getattr(site_result, "skipped_pages", None)
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

    save_run_log(config.library_dir, "site-batch", tracker)
    return json.dumps(
        {
            "status": "complete",
            "pages": results,
            "count": len(results),
            "cost": _server._cost_summary(tracker),
        },
        indent=2,
    )
