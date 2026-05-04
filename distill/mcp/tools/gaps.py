"""MCP tools — gaps: research_gaps."""

from __future__ import annotations

import json

from distill.mcp import server as _server

__all__: list[str] = []


@_server.mcp.tool()
def research_gaps(topic: str) -> str:
    """Assess what a topic corpus appears to be missing and suggest next actions.

    Uses local corpus heuristics to highlight thin coverage, missing artifacts,
    stale recency, and incomplete processing so an external agent can decide
    whether to trigger more ingestion, resynthesis, or reporting.

    Args:
        topic: Topic name to inspect
    """
    config = _server._config()
    return json.dumps(_server._topic_gap_summary(config, topic), indent=2)
