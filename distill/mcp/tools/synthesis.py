# pyright: strict
"""MCP tools -- synthesis: run or regenerate synthesis for a topic."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context
from pydantic import StrictBool

from distill.llm.availability import model_available
from distill.mcp.server import capped_tracker, cost_summary, library, load_config, mcp, write_tool
from distill.pipeline.costs import BudgetExceededError

__all__: list[str] = []

type SynthesisRow = dict[str, str | bool]


@mcp.tool()
@write_tool("synthesize")
async def synthesize(  # noqa: C901 - preserves ordered progress and scope rows.
    topic: str,
    force: StrictBool = False,
    style: str = "",
    two_pass: bool = False,
    ctx: Context[Any, Any, Any] | None = None,
) -> str:
    """Run or regenerate synthesis for a topic across all sources.

    Args:
        topic: Topic to synthesize
        force: Force regeneration even if fresh
        style: Optional register for the topic/corpus synthesis, one of
            exec, pop, landscape, disagreements-only (empty = standard).
        two_pass: When true, the corpus synthesis extracts atomic claims into a
            per-topic claims.jsonl and synthesizes over the claim set (clusters,
            contradictions, per-claim citations). Opt-in; default single-pass.
    """
    if force is not True:
        return json.dumps(
            {
                "status": "authorization_required",
                "action": "regenerate_synthesis",
                "message": (
                    "Synthesis regeneration requires explicit authorization. Retry with force=true."
                ),
                "required": {"force": True},
            },
            indent=2,
        )

    config = load_config()
    if not model_available():
        return json.dumps(
            {
                "status": "error",
                "error": "No model configured (set a cloud key or DISTILL_PROVIDER).",
            }
        )

    from distill.pipeline.synthesis.corpus import synthesize_corpus
    from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic
    from distill.prompts.synthesis import STYLE_NAMES

    if style and style not in STYLE_NAMES:
        return json.dumps(
            {
                "status": "error",
                "error": f"Unknown style '{style}'. Use one of: {list(STYLE_NAMES)}.",
            }
        )

    lib = library(config)
    tracker = capped_tracker()
    channels = lib.get_channels(topic)
    results: list[SynthesisRow] = []
    total_steps = len(channels) + 2  # channels + topic + corpus

    for i, ch in enumerate(channels):
        if ctx:
            await ctx.report_progress(progress=i, total=total_steps)
        try:
            synthesize_channel(topic, ch.name, config, tracker=tracker)
            results.append({"channel": ch.name, "status": "ok"})
        except BudgetExceededError:
            raise  # the per-call spend cap is a hard stop; write_tool answers
        except Exception as e:
            results.append({"channel": ch.name, "status": "error", "error": str(e)})

    # Topic synthesis
    if ctx:
        await ctx.report_progress(progress=len(channels), total=total_steps)
    try:
        synthesize_topic(topic, config, tracker=tracker, style=style)
        results.append({"scope": "topic", "status": "ok"})
    except BudgetExceededError:
        raise
    except Exception as e:
        results.append({"scope": "topic", "status": "error", "error": str(e)})

    # Corpus synthesis
    if ctx:
        await ctx.report_progress(progress=len(channels) + 1, total=total_steps)
    try:
        corpus = synthesize_corpus(topic, config, tracker=tracker, style=style, two_pass=two_pass)
        if corpus:
            results.append({"scope": "corpus", "status": "ok", "two_pass": two_pass})
        else:
            results.append({"scope": "corpus", "status": "skipped", "reason": "no mixed sources"})
    except BudgetExceededError:
        raise
    except Exception as e:
        results.append({"scope": "corpus", "status": "error", "error": str(e)})

    if ctx:
        await ctx.report_progress(progress=total_steps, total=total_steps)

    return json.dumps(
        {
            "status": "complete",
            "results": results,
            "cost": cost_summary(tracker),
        },
        indent=2,
    )
