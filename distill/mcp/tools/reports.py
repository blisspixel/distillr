# pyright: strict
"""MCP tools -- reports: generate_report, resynthesize_topic."""

from __future__ import annotations

import json
from typing import Protocol

from distill.config import DistillConfig
from distill.llm.availability import model_available
from distill.mcp.server import (
    agent_safe_error,
    capped_tracker,
    cost_summary,
    library,
    load_config,
    mcp,
    write_tool,
    write_tool_annotations,
)
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.report.facade import ReportProfileName, run_report
from distill.pipeline.report.profiles import parse_report_profile

__all__: list[str] = []

type ResultRow = dict[str, str]


class TopicSynthesizer(Protocol):
    def __call__(
        self,
        topic: str,
        config: DistillConfig,
        tracker: CostTracker | None = None,
    ) -> str: ...


@mcp.tool(annotations=write_tool_annotations(destructive=True, idempotent=False, open_world=True))
@write_tool("generate_report", ledger_command="report")
def generate_report(
    topic: str,
    channel: str | None = None,
    profile: str = ReportProfileName.ACCORDION.value,
) -> str:
    """Generate a report for a topic through the canonical report facade.

    Args:
        topic: Topic to report on
        channel: Specific channel scope
        profile: corpus-report, accordion, or deep-research
    """
    config = load_config()
    try:
        selected_profile = parse_report_profile(profile)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    if selected_profile is not ReportProfileName.CORPUS_REPORT and not config.gemini_api_key:
        return "Error: GEMINI_API_KEY not configured. Required for reports."

    tracker = capped_tracker()
    scope = "channel" if channel else "topic"

    try:
        result = run_report(
            topic=topic,
            config=config,
            profile=selected_profile,
            scope=scope,
            channel_name=channel,
            tracker=tracker,
        )
    except BudgetExceededError:
        raise  # the per-call spend cap is a hard stop; write_tool answers
    except Exception as e:
        return json.dumps({"error": agent_safe_error(e)})

    if result:
        return json.dumps(
            {
                "status": "complete",
                "words": len(result.split()),
                "characters": len(result),
                "profile": selected_profile.value,
                "report": result[:5000] + "\n\n... (truncated, full report saved to disk)",
                "cost": cost_summary(tracker),
            },
            indent=2,
        )
    return json.dumps(
        {
            "status": "failed",
            "profile": selected_profile.value,
            "cost": cost_summary(tracker),
        }
    )


@mcp.tool(annotations=write_tool_annotations(destructive=True, idempotent=False, open_world=False))
@write_tool("resynthesize_topic", ledger_command="resynthesize-topic")
def resynthesize_topic(topic: str, channel: str | None = None) -> str:
    """Regenerate synthesis from existing insights without re-analysis.

    Args:
        topic: Topic to resynthesize
        channel: Single channel scope
    """
    from distill.pipeline.synthesis.corpus import synthesize_corpus
    from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

    config = load_config()
    if not model_available():
        return "Error: No model configured (set a cloud key or DISTILL_PROVIDER)."

    lib = library(config)
    tracker = capped_tracker()
    channels = lib.get_channels(topic)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]

    results: list[ResultRow] = []
    for ch in channels:
        try:
            synthesize_channel(topic, ch.name, config, tracker=tracker)
            results.append({"channel": ch.name, "status": "ok"})
        except BudgetExceededError:
            raise  # the per-call spend cap is a hard stop; write_tool answers
        except Exception as e:
            results.append({"channel": ch.name, "status": "error", "error": agent_safe_error(e)})

    if not channel:
        results += _resynthesize_topic_level(
            topic,
            config,
            tracker,
            synthesize_topic=synthesize_topic,
            synthesize_corpus=synthesize_corpus,
        )

    return json.dumps({"results": results, "cost": cost_summary(tracker)}, indent=2)


def _resynthesize_topic_level(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker,
    *,
    synthesize_topic: TopicSynthesizer,
    synthesize_corpus: TopicSynthesizer,
) -> list[ResultRow]:
    """Topic + corpus regeneration rows; budget aborts re-raise."""
    results: list[ResultRow] = []
    try:
        synthesize_topic(topic, config, tracker=tracker)
        results.append({"topic": topic, "status": "ok"})
    except BudgetExceededError:
        raise  # the per-call spend cap is a hard stop; write_tool answers
    except Exception as e:
        results.append({"topic": topic, "status": "error", "error": agent_safe_error(e)})

    try:
        corpus = synthesize_corpus(topic, config, tracker=tracker)
        if corpus:
            results.append({"corpus": topic, "status": "ok"})
        else:
            results.append(
                {"corpus": topic, "status": "skipped", "reason": "no mixed-source material"}
            )
    except BudgetExceededError:
        raise
    except Exception as e:
        results.append({"corpus": topic, "status": "error", "error": agent_safe_error(e)})
    return results
