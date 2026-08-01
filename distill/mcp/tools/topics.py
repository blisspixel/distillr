# pyright: strict
"""MCP tools — topics: process_video_url."""

from __future__ import annotations

import json

from distill.library.paths import find_artifact
from distill.llm.availability import model_available
from distill.mcp.server import (
    capped_tracker,
    cost_summary,
    library,
    load_config,
    mcp,
    refuse_if_host_not_allowed,
    strip_frontmatter,
    write_tool,
    write_tool_annotations,
)

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

    refusal = refuse_if_host_not_allowed(url, action="process_video_url")
    if refusal is not None:
        return refusal
    config = load_config()
    if not model_available():
        return "Error: No model configured (set a cloud key or DISTILL_PROVIDER)."

    info = get_video_info(url)
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
            result["insights"] = strip_frontmatter(insights_file.read_text(encoding="utf-8"))

    return json.dumps(result, indent=2)
