"""MCP tools — reports: generate_report, resynthesize_topic."""

from __future__ import annotations

import json

from distill.mcp import server as _server
from distill.pipeline.costs import CostTracker, save_run_log

__all__: list[str] = []


@_server.mcp.tool()
@_server.write_tool("generate_report")
def generate_report(topic: str, channel: str | None = None) -> str:
    """Generate a deep research report for a topic (long-running).

    Args:
        topic: Topic to report on
        channel: Specific channel scope
    """
    config = _server._config()
    if not config.gemini_api_key:
        return "Error: GEMINI_API_KEY not configured. Required for reports."

    from distill.pipeline.report.accordion import run_accordion_research
    from distill.pipeline.summary import RunSummary

    tracker = CostTracker()
    summary = RunSummary(command="report")
    scope = "channel" if channel else "topic"

    try:
        result = run_accordion_research(
            topic=topic,
            config=config,
            scope=scope,
            channel_name=channel,
            tracker=tracker,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})

    save_run_log(config.library_dir, summary.command, tracker)

    if result:
        return json.dumps(
            {
                "status": "complete",
                "words": len(result.split()),
                "characters": len(result),
                "report": result[:5000] + "\n\n... (truncated, full report saved to disk)",
                "cost": _server._cost_summary(tracker),
            },
            indent=2,
        )
    return json.dumps({"status": "failed", "cost": _server._cost_summary(tracker)})


@_server.mcp.tool()
@_server.write_tool("resynthesize_topic")
def resynthesize_topic(topic: str, channel: str | None = None) -> str:
    """Regenerate synthesis from existing insights without re-analysis.

    Args:
        topic: Topic to resynthesize
        channel: Single channel scope
    """
    from distill.pipeline.synthesis.corpus import synthesize_corpus
    from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

    config = _server._config()
    if not config.xai_api_key:
        return "Error: XAI_API_KEY not configured."

    lib = _server._lib(config)
    tracker = CostTracker()
    channels = lib.get_channels(topic)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]

    results = []
    for ch in channels:
        try:
            synthesize_channel(topic, ch.name, config, tracker=tracker)
            results.append({"channel": ch.name, "status": "ok"})
        except Exception as e:
            results.append({"channel": ch.name, "status": "error", "error": str(e)})

    if not channel:
        try:
            synthesize_topic(topic, config, tracker=tracker)
            results.append({"topic": topic, "status": "ok"})
        except Exception as e:
            results.append({"topic": topic, "status": "error", "error": str(e)})

        try:
            corpus = synthesize_corpus(topic, config, tracker=tracker)
            if corpus:
                results.append({"corpus": topic, "status": "ok"})
            else:
                results.append(
                    {"corpus": topic, "status": "skipped", "reason": "no mixed-source material"}
                )
        except Exception as e:
            results.append({"corpus": topic, "status": "error", "error": str(e)})

    return json.dumps({"results": results, "cost": _server._cost_summary(tracker)}, indent=2)
