"""MCP tool -- ask: corpus-grounded question answering.

The one deliberate tool addition since the 0.9.30 consolidation. Returns the
answer text plus the artifact path (paths-not-payloads for the sources --
drill into them with ``read_insight``). Promotion (``--save``) is CLI-only
until MCP write-gating ships: re-ingesting generated content is a corpus
mutation, and connected agents do not get it silently.
"""

from __future__ import annotations

import json

from distill.mcp import server as _server

__all__: list[str] = []


@_server.mcp.tool()
@_server.write_tool("ask")
def ask(topic: str, question: str) -> str:
    """Answer a question from a topic's corpus, grounded-only with citations.

    Args:
        topic: Topic whose corpus grounds the answer.
        question: The question to answer.
    """
    from distill.pipeline.ask import ask_corpus

    config = _server._config()
    if not config.xai_api_key:
        return json.dumps({"status": "error", "error": "XAI_API_KEY not configured."}, indent=2)
    if not config.topic_dir(topic).exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    tracker = _server.capped_tracker()
    result = ask_corpus(question, topic=topic, config=config, save=False, tracker=tracker)
    if result.no_coverage:
        return json.dumps(
            {
                "status": "no_coverage",
                "message": f"Topic '{topic}' has no matching artifacts for this question.",
            },
            indent=2,
        )
    return json.dumps(
        {
            "answer": result.answer_text,
            "sources": result.sources,
            "answer_path": str(result.answer_path.relative_to(config.library_dir))
            if result.answer_path
            else "",
            "cost": _server._cost_summary(tracker),
        },
        indent=2,
    )
