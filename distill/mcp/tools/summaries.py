# pyright: strict
"""MCP tools -- sub-agent surface: list_topics and bounded summaries.

The bounded half of the JIT read layer (roadmap 0.12 "Sub-agent-friendly MCP
surface"): `find_insights` returns ranked paths for drill-down; these return
*content sized to a budget*. `find_insights_summary` spends one compression
call (cached by corpus revision, so repeats are free) and is therefore gated in
read-only mode. `list_topics` and `list_topic_summary` are deterministic and
free, for a sub-agent choosing which topic to query at all.
"""

from __future__ import annotations

import json
from pathlib import Path

from distill.library.claude_md import count_topic_sources, topic_summary_line
from distill.llm.availability import model_available
from distill.mcp.server import capped_tracker, cost_summary, load_config, mcp, write_tool

__all__: list[str] = []


def _has_synthesis(topic_dir: Path) -> bool:
    return any(
        any(topic_dir.glob(pattern))
        for pattern in ("*_Corpus_Synthesis.md", "*_Topic_Synthesis.md", "*_Paper_Synthesis.md")
    )


@mcp.tool()
def list_topics(limit: int = 50) -> str:
    """List available corpus topics (free, no model call).

    Use this before topic-scoped tools such as find_insights,
    list_topic_summary, research_gaps, or ask. Returned paths are relative to
    the library root.

    Args:
        limit: Maximum topics to return, sorted by name. Clamped to 1..200.
    """
    config = load_config()
    topics_dir = config.topics_dir()
    limit = max(1, min(int(limit), 200))
    if not topics_dir.is_dir():
        return json.dumps(
            {
                "topics": [],
                "count": 0,
                "message": "No topics directory found. Ingest sources first or set DISTILL_OUTPUT_DIR to the corpus library.",
            },
            indent=2,
        )

    rows: list[dict[str, object]] = []
    for topic_dir in sorted(
        (p for p in topics_dir.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name.lower(),
    ):
        counts = count_topic_sources(topic_dir)
        has_synthesis = _has_synthesis(topic_dir)
        if counts["total"] == 0 and not has_synthesis:
            continue
        rows.append(
            {
                "topic": topic_dir.name,
                "path": f"topics/{topic_dir.name}",
                "sources": counts,
                "has_synthesis": has_synthesis,
                "summary": topic_summary_line(topic_dir, topic_dir.name),
            }
        )
        if len(rows) >= limit:
            break

    response: dict[str, object] = {"topics": rows, "count": len(rows)}
    if not rows:
        response["message"] = (
            "No populated topics found. Ingest sources first or set DISTILL_OUTPUT_DIR to the corpus library."
        )
    return json.dumps(response, indent=2)


@mcp.tool()
@write_tool("find_insights_summary")
def find_insights_summary(topic: str, query: str, max_tokens: int = 4000) -> str:
    """Summarize a topic's best-matching insights, focused on a query, within a token budget.

    Built for sub-agents: one bounded brief with bracketed source-stem
    citations (drill into any stem with read_insight). Cached by corpus
    revision -- repeated calls cost nothing until the matching artifacts
    change.

    Args:
        topic: Topic whose corpus to summarize from.
        query: The question the brief should be organized around.
        max_tokens: Approximate context budget for the brief (default 4000).
    """
    from distill.pipeline.summary_query import summarize_query

    config = load_config()
    if not model_available():
        return json.dumps(
            {
                "status": "error",
                "error": "No model configured (set a cloud key or DISTILL_PROVIDER).",
            },
            indent=2,
        )
    if not config.topic_dir(topic).exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)
    max_tokens = max(500, min(int(max_tokens), 16_000))

    tracker = capped_tracker()
    result = summarize_query(config, topic, query, max_tokens=max_tokens, tracker=tracker)
    if result is None:
        return json.dumps(
            {"status": "no_matches", "message": f"Nothing in '{topic}' matches this query."},
            indent=2,
        )
    return json.dumps(
        {
            "summary": result.summary,
            "sources": result.sources,
            "cached": result.cached,
            "model": result.model,
            "cost": cost_summary(tracker),
        },
        indent=2,
    )


@mcp.tool()
def list_topic_summary(topic: str) -> str:
    """One-paragraph orientation for a topic (free, no model call).

    Pulled from the topic's newest synthesis artifact; used when a sub-agent
    is choosing which topic to query before spending on retrieval.

    Args:
        topic: Topic to summarize.
    """
    from distill.library.paths import strip_frontmatter

    config = load_config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    synth_files = sorted(
        (
            p
            for pattern in ("*_Corpus_Synthesis.md", "*_Topic_Synthesis.md", "*_Paper_Synthesis.md")
            for p in topic_dir.glob(pattern)
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    paragraph = ""
    source_file = ""
    for synth in synth_files:
        try:
            body = strip_frontmatter(synth.read_text(encoding="utf-8"))
        except OSError:
            continue
        # First substantive prose paragraph: skip headings and blank lines.
        for block in body.split("\n\n"):
            stripped = block.strip()
            if stripped and not stripped.startswith("#"):
                paragraph = " ".join(stripped.split())[:1200]
                break
        if paragraph:
            source_file = synth.name
            break

    insight_count = sum(1 for _ in topic_dir.rglob("*_Insights.md"))
    if not paragraph:
        paragraph = (
            f"No synthesis artifact yet; the topic holds {insight_count} insight artifact(s). "
            "Run distill synthesize to produce an overview."
        )
    return json.dumps(
        {
            "topic": topic,
            "summary": paragraph,
            "from": source_file,
            "insights": insight_count,
        },
        indent=2,
    )
