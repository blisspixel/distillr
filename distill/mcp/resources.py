"""MCP resources — all resource handlers for the Distill MCP server."""

from __future__ import annotations

import json
from pathlib import Path

from distill.library.paths import find_artifact
from distill.library.state import ChannelState
from distill.mcp import server as _server

__all__: list[str] = []


@_server.mcp.resource("distill://topics")
def get_topics() -> str:
    """List all topics with channel counts and video counts."""
    config = _server._config()
    lib = _server._lib(config)
    topics = []
    for t in lib.get_topics():
        channels = lib.get_channels(t)
        total_videos = 0
        for ch in channels:
            state_path = config.channel_dir(t, ch.name) / "state.json"
            if state_path.parent.exists():
                st = ChannelState(state_path)
                total_videos += st.get_processed_count()
        topics.append(
            {
                "name": t,
                "channels": len(channels),
                "channel_names": [ch.name for ch in channels],
                "videos_analyzed": total_videos,
            }
        )
    return json.dumps({"topics": topics}, indent=2)


@_server.mcp.resource("distill://watchlist")
def get_watchlist() -> str:
    """Show the watch list with per-channel settings."""
    lib = _server._lib()
    entries = []
    for e in lib.get_watchlist():
        entries.append(
            {
                "name": e.name,
                "url": e.url,
                "topic": e.topic,
                "days": e.days,
                "instructions": e.instructions,
                "added_at": e.added_at,
            }
        )
    return json.dumps({"watchlist": entries}, indent=2)


@_server.mcp.resource("distill://topics/{topic}/videos")
def get_topic_videos(topic: str) -> str:
    """List all processed videos in a topic with status."""
    config = _server._config()
    lib = _server._lib(config)
    channels = lib.get_channels(topic)
    all_videos = []
    for ch in channels:
        for v in _server._video_list(config, topic, ch.name):
            all_videos.append(
                {
                    "title": v.get("title", "Unknown"),
                    "channel": ch.name,
                    "date": v.get("upload_date", ""),
                    "duration": v.get("duration", 0),
                    "url": v.get("url", ""),
                    "has_insights": v.get("has_insights", False),
                    "has_transcript": v.get("has_transcript", False),
                    "analysis_mode": v.get("analysis_mode", "unknown"),
                }
            )
    all_videos.sort(key=lambda x: x.get("date", ""), reverse=True)
    return json.dumps({"topic": topic, "videos": all_videos}, indent=2)


@_server.mcp.resource("distill://topics/{topic}/synthesis")
def get_topic_synthesis(topic: str) -> str:
    """Read the topic synthesis document."""
    config = _server._config()
    path = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
    if path.exists():
        return path.read_text(encoding="utf-8")
    # Fall back to first channel synthesis
    lib = _server._lib(config)
    channels = lib.get_channels(topic)
    for ch in channels:
        ch_path = find_artifact(
            config.channel_dir(topic, ch.name),
            "synthesis",
            identity=f"{topic}_{ch.name}",
        )
        if ch_path.exists():
            return ch_path.read_text(encoding="utf-8")
    return f"No synthesis found for topic '{topic}'. Run catch_up or learn_topic first."


@_server.mcp.resource("distill://topics/{topic}/corpus")
def get_topic_corpus(topic: str) -> str:
    """Read the mixed-source corpus synthesis document when available."""
    config = _server._config()
    return _server._read_markdown_resource(
        find_artifact(config.topic_dir(topic), "corpus_synthesis", identity=topic),
        f"No corpus synthesis found for '{topic}'. Run distill corpus {topic} after the topic has multiple source types.",
    )


@_server.mcp.resource("distill://topics/{topic}/sources")
def get_topic_sources(topic: str) -> str:
    """Show source inventory for a topic across videos, websites, and papers."""
    config = _server._config()
    return json.dumps(_server._topic_source_inventory(config, topic), indent=2)


@_server.mcp.resource("distill://topics/{topic}/diff")
def get_topic_diff(topic: str) -> str:
    """Read the latest topic diff briefing when available."""
    config = _server._config()
    return _server._read_markdown_resource(
        find_artifact(config.topic_dir(topic), "topic_diff", identity=topic),
        f"No topic diff found for '{topic}'. Run distill diff {topic} or topic-watch refresh first.",
    )


@_server.mcp.resource("distill://topics/{topic}/trends")
def get_topic_trends(topic: str) -> str:
    """Read the latest topic trends summary when available."""
    config = _server._config()
    return _server._read_markdown_resource(
        find_artifact(config.topic_dir(topic), "topic_trends", identity=topic),
        f"No topic trends found for '{topic}'. Run distill trends {topic} after accumulating change history.",
    )


@_server.mcp.resource("distill://watch-alerts")
def get_watch_alerts() -> str:
    """Read the latest watch alert digest when available."""
    config = _server._config()
    return _server._read_markdown_resource(
        find_artifact(config.library_dir, "watch_alerts", identity="library"),
        "No watch alerts found. Run distill topic-watch run after adding some watches.",
    )


@_server.mcp.resource("distill://topics/{topic}/channels/{channel}/synthesis")
def get_channel_synthesis(topic: str, channel: str) -> str:
    """Read a channel's synthesis document."""
    config = _server._config()
    path = find_artifact(
        config.channel_dir(topic, channel),
        "synthesis",
        identity=f"{topic}_{channel}",
    )
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"No synthesis for {channel}. Run catch_up first."


@_server.mcp.resource("distill://topics/{topic}/channels/{channel}/insights/{index}")
def get_video_insights(topic: str, channel: str, index: str) -> str:
    """Read insights for a specific video (1=newest).

    Args:
        topic: Topic name
        channel: Channel name
        index: Video number (1=newest, 2=second newest, etc.)
    """
    config = _server._config()
    vid_list = _server._video_list(config, topic, channel)
    try:
        idx = int(index)
    except ValueError:
        return f"Invalid index '{index}'. Use a number (1=newest)."

    if idx < 1 or idx > len(vid_list):
        return f"Video #{idx} not found. {channel} has {len(vid_list)} videos (1-{len(vid_list)})."

    video = vid_list[idx - 1]
    vid_dir = Path(video["_dir"])
    insights_file = find_artifact(vid_dir, "insights")
    if not insights_file.exists():
        return f"No insights for '{video.get('title', 'Unknown')}'. Video may not be analyzed yet."

    content = _server._strip_frontmatter(insights_file.read_text(encoding="utf-8"))
    header = (
        f"# {video.get('title', 'Unknown')}\n"
        f"**Date:** {video.get('upload_date', '?')} | "
        f"**Channel:** {channel} | "
        f"**Video {idx}/{len(vid_list)}**\n\n"
    )
    return header + content


@_server.mcp.resource("distill://costs")
def get_costs() -> str:
    """Show recent cost history from past runs."""
    config = _server._config()
    # Check new location first, fall back to old
    ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    legacy_log = config.library_dir / "cost_log.jsonl"
    log_file = ops_log if ops_log.exists() else legacy_log
    if not log_file.exists():
        return json.dumps({"costs": [], "message": "No cost history yet."})

    entries = []
    for line in log_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    recent = entries[-20:]
    total = sum(e.get("actual_cost", 0) for e in recent)
    return json.dumps(
        {
            "recent_runs": recent,
            "total_cost": round(total, 4),
            "runs_shown": len(recent),
        },
        indent=2,
    )
