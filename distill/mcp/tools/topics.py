"""MCP tools — topics: process_video_url."""

from __future__ import annotations

import json

from distill.library.paths import find_artifact
from distill.llm.availability import model_available
from distill.mcp import server as _server
from distill.pipeline.costs import save_run_log

__all__: list[str] = []


@_server.mcp.tool()
@_server.write_tool("process_video_url")
def process_video_url(url: str, topic: str = "ai") -> str:
    """Transcribe and analyze a single YouTube video.

    Args:
        url: YouTube video URL
        topic: Topic to file under
    """
    from distill.cli_shared import ensure_channel_context, process_video, resolve_video_channel_name
    from distill.ingestors.youtube.discovery import get_video_info, resolve_channel_name
    from distill.pipeline.summary import RunSummary

    refusal = _server.refuse_if_host_not_allowed(url)
    if refusal is not None:
        return refusal
    config = _server._config()
    if not model_available():
        return "Error: No model configured (set a cloud key or DISTILL_PROVIDER)."

    info = get_video_info(url)
    if not info:
        return "Error: Could not get video info. Check the URL."

    channel_name = resolve_video_channel_name(url, info, resolve_channel_name)
    tracker = _server.capped_tracker()
    summary = RunSummary(command="video")
    lib = _server._lib(config)
    lib.add_channel(topic, info.channel_url or url, channel_name)

    ensure_channel_context(topic, channel_name, [info], config, tracker)
    success = process_video(topic, channel_name, info, config, tracker, summary)

    result = {
        "title": info.title,
        "channel": channel_name,
        "success": success,
        "cost": _server._cost_summary(tracker),
    }

    if success:
        insights_file = find_artifact(
            config.video_dir_slug(topic, channel_name, info.title, info.video_id),
            "insights",
        )
        if insights_file.exists():
            result["insights"] = _server._strip_frontmatter(
                insights_file.read_text(encoding="utf-8")
            )

    save_run_log(config.library_dir, summary.command, tracker)
    return json.dumps(result, indent=2)
