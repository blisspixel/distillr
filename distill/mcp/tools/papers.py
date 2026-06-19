"""MCP tools — papers: search arXiv, download, and analyze papers."""

from __future__ import annotations

import json

from mcp.server.fastmcp import Context

from distill.llm.availability import model_available
from distill.mcp import server as _server
from distill.pipeline.costs import BudgetExceededError, save_run_log

__all__: list[str] = []

# Each paper triggers a download + an LLM analysis call, so cap how many a single
# (possibly prompt-injected) MCP call can process to bound cloud spend.
_MAX_PAPERS = 25


def _analyze_one(paper, topic, config, tracker, intent, *, analyze_paper) -> dict:
    """Analyze one paper into its result row; budget aborts re-raise."""
    from distill.commands._paper_artifacts import write_paper_artifacts

    try:
        insights, document = analyze_paper(paper, config, tracker=tracker, intent=intent)
        write_paper_artifacts(topic, paper, config, insights, document)
        return {"title": paper.title, "status": "ok"}
    except BudgetExceededError:
        raise  # the per-call spend cap is a hard stop; write_tool answers
    except Exception as e:
        return {"title": paper.title, "status": "error", "error": str(e)}


@_server.mcp.tool()
@_server.write_tool("papers")
async def papers(topic: str, query: str, limit: int = 5, ctx: Context = None) -> str:
    """Search arXiv, download, and analyze papers for a topic.

    Args:
        topic: Topic to file papers under
        query: Search query for arXiv
        limit: Max papers to process
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
        limit = max(1, min(int(limit), _MAX_PAPERS))
    except (TypeError, ValueError):
        limit = 5

    try:
        from distill.ingestors.papers.arxiv import search_arxiv
        from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
        from distill.pipeline.synthesis.corpus import synthesize_corpus
    except ImportError as e:
        return json.dumps({"status": "error", "error": f"Paper dependencies missing: {e}"})

    tracker = _server.capped_tracker()
    results = []

    try:
        found = search_arxiv(query, max_results=limit * 2)
    except Exception as e:
        return json.dumps({"status": "error", "error": f"arXiv search failed: {e}"})

    selected = found[:limit]

    from distill.library.intent import load_intent

    intent = load_intent(config.topic_dir(topic))

    for i, paper in enumerate(selected):
        if ctx:
            await ctx.report_progress(progress=i, total=len(selected))
        results.append(
            _analyze_one(paper, topic, config, tracker, intent, analyze_paper=analyze_paper)
        )

    if ctx:
        await ctx.report_progress(progress=len(selected), total=len(selected))

    try:
        synthesize_papers(topic, config, tracker=tracker)
        synthesize_corpus(topic, config, tracker=tracker)
    except BudgetExceededError:
        raise  # the per-call spend cap is a hard stop; write_tool answers
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
