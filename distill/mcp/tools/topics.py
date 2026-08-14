# pyright: strict
"""MCP tools — topics: process_video_url."""

from __future__ import annotations

import json

from distill.library.paths import find_artifact
from distill.llm.availability import model_available
from distill.mcp.server import (
    agent_visible_path,
    capped_tracker,
    cost_summary,
    library,
    load_config,
    mcp,
    refuse_if_host_not_allowed,
    write_tool,
    write_tool_annotations,
)
from distill.youtube_urls import normalize_youtube_video_url

__all__: list[str] = []


@mcp.tool(annotations=write_tool_annotations(destructive=False, idempotent=False, open_world=True))
@write_tool("process_video_url", ledger_command="video")
def process_video_url(url: str, topic: str = "ai") -> str:
    """Transcribe and analyze a single YouTube video.

    Args:
        url: YouTube video URL
        topic: Topic to file under
    """
    from distill.cli_shared import ensure_channel_context, process_video, resolve_video_channel_name
    from distill.ingestors.youtube.discovery import get_video_info, resolve_channel_name
    from distill.pipeline.summary import RunSummary

    canonical = normalize_youtube_video_url(url)
    if not canonical:
        return json.dumps(
            {
                "status": "usage_error",
                "error": "URL is not a supported YouTube video URL.",
                "action": "process_video_url",
                "phase": "gate.usage",
            },
            indent=2,
        )
    refusal = refuse_if_host_not_allowed(canonical, action="process_video_url")
    if refusal is not None:
        return refusal
    config = load_config()
    if not model_available():
        return "Error: No model configured (set a cloud key or DISTILL_PROVIDER)."

    info = get_video_info(canonical)
    if not info:
        return "Error: Could not get video info. Check the URL."

    channel_name = resolve_video_channel_name(url, info, resolve_channel_name)
    tracker = capped_tracker()
    summary = RunSummary(command="video")
    lib = library(config)
    lib.add_channel(topic, info.channel_url or url, channel_name)

    ensure_channel_context(topic, channel_name, [info], config, tracker)
    success = process_video(topic, channel_name, info, config, tracker, summary)

    result: dict[str, object] = {
        "title": info.title,
        "channel": channel_name,
        "success": success,
        "cost": cost_summary(tracker),
    }

    if success:
        insights_file = find_artifact(
            config.video_dir_slug(topic, channel_name, info.title, info.video_id),
            "insights",
        )
        if insights_file.exists():
            result["insights_path"] = agent_visible_path(config.library_dir, insights_file)

    return json.dumps(result, indent=2)
