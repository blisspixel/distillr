"""MCP tools — gaps: research_gaps."""

from __future__ import annotations

import json

from distill.mcp import server as _server

__all__: list[str] = []


@_server.mcp.tool()
def research_gaps(topic: str) -> str:
    """Assess corpus gaps and suggest next research actions for a topic.

    Args:
        topic: Topic name to inspect
    """
    config = _server._config()
    return json.dumps(_server._topic_gap_summary(config, topic), indent=2)
