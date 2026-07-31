# pyright: strict
"""MCP tools — gaps: research_gaps."""

from __future__ import annotations

import json

from distill.mcp.server import READ_TOOL_ANNOTATIONS, load_config, mcp
from distill.pipeline.gaps import topic_gap_summary

__all__: list[str] = []


@mcp.tool(annotations=READ_TOOL_ANNOTATIONS)
def research_gaps(topic: str) -> str:
    """Assess corpus gaps and suggest next research actions for a topic.

    Args:
        topic: Topic name to inspect
    """
    config = load_config()
    return json.dumps(topic_gap_summary(config, topic), indent=2)
