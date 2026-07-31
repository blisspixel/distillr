# pyright: strict
"""MCP tools -- JIT retrieval: find_insights, read_insight."""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import Field

from distill.library.confined import read_confined_text
from distill.library.paths import strip_frontmatter
from distill.mcp.server import READ_TOOL_ANNOTATIONS, load_config, mcp, resolve_within_library
from distill.pipeline.search import (
    MAX_SEARCH_QUERY_CHARS,
    MAX_SEARCH_RESULTS,
    extract_section,
    is_corpus_artifact_path,
    search_corpus,
)

__all__: list[str] = []

_MAX_READ_INSIGHT_PATH_CHARS = 4_096
_MAX_READ_INSIGHT_SECTION_CHARS = 256
_MAX_READ_INSIGHT_BYTES = 1 * 1024 * 1024
_MAX_READ_INSIGHT_RESPONSE_CHARS = 200_000


def _bounded_content(content: str) -> tuple[str, bool]:
    if len(content) <= _MAX_READ_INSIGHT_RESPONSE_CHARS:
        return content, False
    return content[:_MAX_READ_INSIGHT_RESPONSE_CHARS], True


@mcp.tool(annotations=READ_TOOL_ANNOTATIONS)
def find_insights(
    topic: str,
    query: Annotated[str, Field(min_length=1, max_length=MAX_SEARCH_QUERY_CHARS)],
    limit: Annotated[int, Field(ge=1, le=MAX_SEARCH_RESULTS)] = 10,
) -> str:
    """Search topic corpus; return ranked path/preview/score tuples.

    Args:
        topic: Topic name to search within
        query: Search query terms
        limit: Max results to return
    """
    config = load_config()

    # Check topic exists
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        available: list[str] = []
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

    try:
        results = search_corpus(config, topic, query, limit=limit)
    except ValueError as exc:
        return json.dumps(
            {"status": "error", "error": str(exc)},
            indent=2,
        )

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


@mcp.tool(annotations=READ_TOOL_ANNOTATIONS)
def read_insight(
    path: Annotated[str, Field(min_length=1, max_length=_MAX_READ_INSIGHT_PATH_CHARS)],
    section: Annotated[
        str | None,
        Field(min_length=1, max_length=_MAX_READ_INSIGHT_SECTION_CHARS),
    ] = None,
) -> str:
    """Read artifact content by path, optionally filtered to a section.

    Args:
        path: Relative path from library root
        section: Optional section heading to extract
    """
    config = load_config()
    if not path or len(path) > _MAX_READ_INSIGHT_PATH_CHARS:
        return json.dumps(
            {"status": "error", "error": "Artifact path is empty or too long."},
            indent=2,
        )
    if section is not None and (
        not section.strip() or len(section) > _MAX_READ_INSIGHT_SECTION_CHARS
    ):
        return json.dumps(
            {"status": "error", "error": "Section name is empty or too long."},
            indent=2,
        )
    full_path = resolve_within_library(config.library_dir, path)

    if full_path is None or not is_corpus_artifact_path(config, full_path):
        return json.dumps(
            {
                "status": "error",
                "error": "Path must identify a Markdown artifact inside library/topics.",
            },
            indent=2,
        )

    raw = read_confined_text(
        full_path,
        config.library_dir,
        max_bytes=_MAX_READ_INSIGHT_BYTES,
    )
    if raw is None:
        return json.dumps(
            {
                "status": "error",
                "error": "Artifact is missing, unsafe, unreadable, or exceeds the read limit.",
            },
            indent=2,
        )

    body = strip_frontmatter(raw)

    if section:
        content, found = extract_section(body, section)
        if not found:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Section '{section}' was not found.",
                    "path": path,
                    "section": section,
                    "section_found": False,
                },
                indent=2,
            )
        content, truncated = _bounded_content(content)
        result: dict[str, object] = {
            "path": path,
            "content": content,
            "section": section,
            "section_found": True,
            "truncated": truncated,
        }
        return json.dumps(result, indent=2)

    content, truncated = _bounded_content(body)
    return json.dumps(
        {"path": path, "content": content, "truncated": truncated},
        indent=2,
    )
