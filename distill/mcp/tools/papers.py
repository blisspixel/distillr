"""MCP tools — papers: search arXiv, download, and analyze papers."""

from __future__ import annotations

import json

from mcp.server.fastmcp import Context

from distill.mcp import server as _server
from distill.pipeline.costs import CostTracker, save_run_log

__all__: list[str] = []


@_server.mcp.tool()
async def papers(topic: str, query: str, limit: int = 5, ctx: Context = None) -> str:
    """Search arXiv, download, and analyze papers for a topic.

    Args:
        topic: Topic to file papers under
        query: Search query for arXiv
        limit: Max papers to process
    """
    config = _server._config()
    if not config.xai_api_key:
        return json.dumps({"status": "error", "error": "XAI_API_KEY not configured."})

    try:
        from distill.commands._logic import _write_paper_artifacts
        from distill.ingestors.papers.arxiv import search_arxiv
        from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
        from distill.pipeline.synthesis.corpus import synthesize_corpus
    except ImportError as e:
        return json.dumps({"status": "error", "error": f"Paper dependencies missing: {e}"})

    tracker = CostTracker()
    results = []

    try:
        found = search_arxiv(query, max_results=limit * 2)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"arXiv search failed: {e}"})

    selected = found[:limit]

    for i, paper in enumerate(selected):
        if ctx:
            await ctx.report_progress(progress=i, total=len(selected))
        try:
            insights, document = analyze_paper(paper, config, tracker=tracker)
            _write_paper_artifacts(topic, paper, config, insights, document)
            results.append({"title": paper.title, "status": "ok"})
        except Exception as e:
            results.append({"title": paper.title, "status": "error", "error": str(e)})

    if ctx:
        await ctx.report_progress(progress=len(selected), total=len(selected))

    try:
        synthesize_papers(topic, config, tracker=tracker)
        synthesize_corpus(topic, config, tracker=tracker)
    except Exception:
        pass

    save_run_log(config.library_dir, "papers", tracker)
    return json.dumps(
        {
            "status": "complete",
            "papers": results,
            "count": len(results),
            "cost": _server._cost_summary(tracker),
        },
        indent=2,
    )
