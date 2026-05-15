"""MCP tools — sites: scrape and analyze pages from a site."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from mcp.server.fastmcp import Context

from distill.mcp import server as _server
from distill.pipeline.costs import CostTracker, save_run_log

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
async def site_batch(  # noqa: C901
    topic: str,
    urls: list[str] | None = None,
    seed_file: str | None = None,
    ctx: Context = None,
) -> str:
    """Scrape and analyze pages from a site seed file or URL list.

    Args:
        topic: Topic to file pages under
        urls: List of URLs to process
        seed_file: Path to a seed file with URLs
    """
    config = _server._config()
    if not config.xai_api_key:
        return json.dumps({"status": "error", "error": "XAI_API_KEY not configured."})

    # Resolve URLs from seed file or direct list
    page_urls: list[str] = []
    if urls:
        page_urls = urls[:_MAX_SITE_BATCH_URLS]
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
        page_urls = [
            line.strip()
            for line in seed_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ][:_MAX_SITE_BATCH_URLS]
    else:
        return json.dumps({"status": "error", "error": "Provide either 'urls' or 'seed_file'."})

    if not page_urls:
        return json.dumps({"status": "error", "error": "No URLs to process."})

    try:
        from distill.commands._logic import _process_site_seed
        from distill.ingestors.sites.scraper import SiteSeed
        from distill.pipeline.summary import RunSummary
    except ImportError as e:
        return json.dumps({"status": "error", "error": f"Site dependencies missing: {e}"})

    tracker = CostTracker()
    summary = RunSummary(command="site-batch")
    results = []

    for i, url in enumerate(page_urls):
        if ctx:
            await ctx.report_progress(progress=i, total=len(page_urls))
        try:
            seed = SiteSeed(url=url, topic=topic, max_depth=0, max_pages=1)
            site_name, page_count = _process_site_seed(seed, config, tracker, summary)
            results.append(
                {
                    "url": url,
                    "site": site_name,
                    "pages": page_count,
                    "status": "ok" if page_count else "skipped",
                }
            )
        except Exception as e:
            results.append({"url": url, "status": "error", "error": str(e)})

    if ctx:
        await ctx.report_progress(progress=len(page_urls), total=len(page_urls))

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
