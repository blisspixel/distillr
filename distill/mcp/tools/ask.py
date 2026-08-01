# pyright: strict
"""MCP tool -- ask: corpus-grounded question answering.

The one deliberate tool addition since the 0.9.30 consolidation. Returns the
answer text plus the artifact path (paths-not-payloads for the sources --
drill into them with ``read_insight``). Promotion (``--save``) is CLI-only
until MCP write-gating ships: re-ingesting generated content is a corpus
mutation, and connected agents do not get it silently.
"""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import Field

from distill.llm.availability import model_available
from distill.mcp.server import (
    agent_visible_path,
    capped_tracker,
    cost_summary,
    load_config,
    mcp,
    write_tool,
    write_tool_annotations,
)
from distill.pipeline.ask import MAX_ASK_ANSWER_CHARS, MAX_ASK_QUESTION_CHARS

__all__: list[str] = []


@mcp.tool(annotations=write_tool_annotations(destructive=False, idempotent=False, open_world=False))
@write_tool("ask")
def ask(
    topic: Annotated[str, Field(min_length=1, max_length=128)],
    question: Annotated[str, Field(min_length=1, max_length=MAX_ASK_QUESTION_CHARS)],
) -> str:
    """Answer a question from a topic's corpus, grounded-only with citations.

    Args:
        topic: Topic whose corpus grounds the answer.
        question: The question to answer.
    """
    from distill.pipeline.ask import ask_corpus

    if not topic.strip() or len(topic) > 128:
        return json.dumps({"status": "error", "error": "Topic is empty or too long."}, indent=2)
    if not question.strip() or len(question) > MAX_ASK_QUESTION_CHARS:
        return json.dumps(
            {
                "status": "error",
                "error": f"Question must contain 1 to {MAX_ASK_QUESTION_CHARS} characters.",
            },
            indent=2,
        )
    config = load_config()
    if not model_available("qa"):
        return json.dumps(
            {
                "status": "error",
                "error": "No model configured (set a cloud key or DISTILL_PROVIDER).",
            },
            indent=2,
        )
    if not config.topic_dir(topic).exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    tracker = capped_tracker()
    result = ask_corpus(question, topic=topic, config=config, save=False, tracker=tracker)
    if len(result.answer_text) > MAX_ASK_ANSWER_CHARS:
        return json.dumps(
            {
                "status": "error",
                "error": "Answer exceeded the MCP response limit.",
            },
            indent=2,
        )
    if result.no_coverage:
        return json.dumps(
            {
                "status": "no_coverage",
                "message": f"Topic '{topic}' has no matching artifacts for this question.",
            },
            indent=2,
        )
    if result.answer_refused_reason:
        return json.dumps(
            {
                "status": "refused",
                "error": result.answer_refused_reason,
                "answer": result.answer_text,
                "sources": result.sources,
                "answer_path": "",
                "cost": cost_summary(tracker),
            },
            indent=2,
        )
    return json.dumps(
        {
            "answer": result.answer_text,
            "sources": result.sources,
            "answer_path": (
                agent_visible_path(config.library_dir, result.answer_path)
                if result.answer_path
                else ""
            ),
            "cost": cost_summary(tracker),
        },
        indent=2,
    )
