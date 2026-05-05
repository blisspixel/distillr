"""MCP tools — sites: scrape and analyze pages from a site."""

from __future__ import annotations

import json

from mcp.server.fastmcp import Context

from distill.mcp import server as _server
from distill.pipeline.costs import CostTracker, save_run_log

__all__: list[str] = []


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
        page_urls = urls
    elif seed_file:
        from pathlib import Path

        seed_path = Path(seed_file)
        if not seed_path.exists():
            return json.dumps({"status": "error", "error": f"Seed file not found: {seed_file}"})
        page_urls = [
            line.strip()
            for line in seed_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        return json.dumps({"status": "error", "error": "Provide either 'urls' or 'seed_file'."})

    if not page_urls:
        return json.dumps({"status": "error", "error": "No URLs to process."})

    try:
        from distill.ingestors.sites.scraper import scrape_and_analyze_page
    except ImportError as e:
        return json.dumps({"status": "error", "error": f"Site dependencies missing: {e}"})

    tracker = CostTracker()
    results = []

    for i, url in enumerate(page_urls):
        if ctx:
            await ctx.report_progress(progress=i, total=len(page_urls))
        try:
            scrape_and_analyze_page(url, topic, config, tracker=tracker)
            results.append({"url": url, "status": "ok"})
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
