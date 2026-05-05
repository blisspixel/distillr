"""MCP tools — JIT retrieval: find_insights, read_insight."""

from __future__ import annotations

import json

from distill.library.paths import strip_frontmatter
from distill.mcp import server as _server
from distill.pipeline.search import extract_section, search_corpus

__all__: list[str] = []


@_server.mcp.tool()
def find_insights(topic: str, query: str, limit: int = 10) -> str:
    """Search topic corpus; return ranked path/preview/score tuples.

    Args:
        topic: Topic name to search within
        query: Search query terms
        limit: Max results to return
    """
    config = _server._config()

    # Check topic exists
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        available = []
        topics_dir = config.topics_dir()
        if topics_dir.exists():
            available = [d.name for d in topics_dir.iterdir() if d.is_dir()]
        return json.dumps(
            {
                "status": "error",
                "error": f"Topic '{topic}' not found. Available: {', '.join(available) or 'none'}",
            },
            indent=2,
        )

    results = search_corpus(config, topic, query, limit=limit)

    if not results:
        return json.dumps(
            {
                "results": [],
                "count": 0,
                "topic": topic,
                "message": f"No results found for '{query}' in topic '{topic}'.",
            },
            indent=2,
        )

    return json.dumps(
        {
            "results": [
                {"path": r.path, "preview": r.preview, "score": round(r.score, 3)} for r in results
            ],
            "count": len(results),
            "topic": topic,
        },
        indent=2,
    )


@_server.mcp.tool()
def read_insight(path: str, section: str | None = None) -> str:
    """Read artifact content by path, optionally filtered to a section.

    Args:
        path: Relative path from library root
        section: Optional section heading to extract
    """
    config = _server._config()
    full_path = config.library_dir / path

    if not full_path.exists():
        return json.dumps(
            {"status": "error", "error": f"Path not found: {path}"},
            indent=2,
        )

    try:
        raw = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return json.dumps(
            {"status": "error", "error": f"Cannot read file: {e}"},
            indent=2,
        )

    body = strip_frontmatter(raw)

    if section:
        content, found = extract_section(body, section)
        result: dict = {
            "path": path,
            "content": content,
            "section": section,
            "section_found": found,
        }
        if not found:
            result["warning"] = f"Section '{section}' not found. Returning full content."
        return json.dumps(result, indent=2)

    return json.dumps(
        {"path": path, "content": body},
        indent=2,
    )
