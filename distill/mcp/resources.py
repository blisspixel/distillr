# pyright: strict
"""MCP resources -- all resource handlers for the Distill MCP server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from distill.config import DistillConfig
from distill.library.confined import read_confined_text
from distill.library.paths import find_artifact
from distill.library.state import ChannelState
from distill.mcp.server import (
    library,
    load_config,
    mcp,
    strip_frontmatter,
    topic_source_inventory,
    video_list,
)
from distill.pipeline.cost_history import (
    CostLogScan,
    cost_history_integrity_message,
    project_cost_log_row,
    scan_confined_cost_log,
    select_cost_log_path,
)

__all__: list[str] = []

type JsonObject = dict[str, object]

_MAX_MCP_ARTIFACT_BYTES = 4 * 1024 * 1024


class TopicRow(TypedDict):
    name: str
    channels: int
    channel_names: list[str]
    videos_analyzed: int


class WatchlistRow(TypedDict):
    name: str
    url: str
    topic: str
    days: int
    instructions: str
    instructions_approved: bool
    added_at: str


class TopicVideoRow(TypedDict):
    title: str
    channel: str
    date: str
    duration: int
    url: str
    has_insights: bool
    has_transcript: bool
    analysis_mode: str


def _cost_value(entry: JsonObject) -> float:
    value = entry.get("actual_cost", 0)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _read_library_text(path: Path, config: DistillConfig) -> str | None:
    return read_confined_text(
        path,
        config.library_dir,
        max_bytes=_MAX_MCP_ARTIFACT_BYTES,
    )


def _read_library_resource(
    path: Path,
    config: DistillConfig,
    missing_message: str,
) -> str:
    content = _read_library_text(path, config)
    return content if content is not None else missing_message


@mcp.resource("distill://topics")
def get_topics() -> str:
    """List all topics with channel counts and video counts."""
    config = load_config()
    lib = library(config)
    topics: list[TopicRow] = []
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


@mcp.resource("distill://watchlist")
def get_watchlist() -> str:
    """Show the watch list with per-channel settings."""
    lib = library()
    entries: list[WatchlistRow] = []
    for e in lib.get_watchlist():
        entries.append(
            {
                "name": e.name,
                "url": e.url,
                "topic": e.topic,
                "days": e.days,
                "instructions": e.instructions,
                "instructions_approved": e.instructions_approved,
                "added_at": e.added_at,
            }
        )
    return json.dumps({"watchlist": entries}, indent=2)


@mcp.resource("distill://topics/{topic}/videos")
def get_topic_videos(topic: str) -> str:
    """List all processed videos in a topic with status."""
    config = load_config()
    lib = library(config)
    channels = lib.get_channels(topic)
    all_videos: list[TopicVideoRow] = []
    for ch in channels:
        for v in video_list(config, topic, ch.name):
            all_videos.append(
                {
                    "title": v["title"],
                    "channel": ch.name,
                    "date": v["upload_date"],
                    "duration": v["duration"],
                    "url": v["url"],
                    "has_insights": v["has_insights"],
                    "has_transcript": v["has_transcript"],
                    "analysis_mode": v["analysis_mode"],
                }
            )
    all_videos.sort(key=lambda row: row["date"], reverse=True)
    return json.dumps({"topic": topic, "videos": all_videos}, indent=2)


@mcp.resource("distill://topics/{topic}/synthesis")
def get_topic_synthesis(topic: str) -> str:
    """Read the topic synthesis document."""
    config = load_config()
    path = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
    content = _read_library_text(path, config)
    if content is not None:
        return content
    # Fall back to first channel synthesis
    lib = library(config)
    channels = lib.get_channels(topic)
    for ch in channels:
        ch_path = find_artifact(
            config.channel_dir(topic, ch.name),
            "synthesis",
            identity=f"{topic}_{ch.name}",
        )
        content = _read_library_text(ch_path, config)
        if content is not None:
            return content
    return f"No synthesis found for topic '{topic}'. Run catch_up or learn_topic first."


@mcp.resource("distill://topics/{topic}/corpus")
def get_topic_corpus(topic: str) -> str:
    """Read the mixed-source corpus synthesis document when available."""
    config = load_config()
    return _read_library_resource(
        find_artifact(config.topic_dir(topic), "corpus_synthesis", identity=topic),
        config,
        f"No corpus synthesis found for '{topic}'. Run distill corpus {topic} after the topic has multiple source types.",
    )


@mcp.resource("distill://topics/{topic}/sources")
def get_topic_sources(topic: str) -> str:
    """Show source inventory for a topic across videos, websites, and papers."""
    config = load_config()
    return json.dumps(topic_source_inventory(config, topic), indent=2)


@mcp.resource("distill://topics/{topic}/diff")
def get_topic_diff(topic: str) -> str:
    """Read the latest topic diff briefing when available."""
    config = load_config()
    return _read_library_resource(
        find_artifact(config.topic_dir(topic), "topic_diff", identity=topic),
        config,
        f"No topic diff found for '{topic}'. Run distill diff {topic} or topic-watch refresh first.",
    )


@mcp.resource("distill://topics/{topic}/trends")
def get_topic_trends(topic: str) -> str:
    """Read the latest topic trends summary when available."""
    config = load_config()
    return _read_library_resource(
        find_artifact(config.topic_dir(topic), "topic_trends", identity=topic),
        config,
        f"No topic trends found for '{topic}'. Run distill trends {topic} after accumulating change history.",
    )


@mcp.resource("distill://watch-alerts")
def get_watch_alerts() -> str:
    """Read the latest watch alert digest when available."""
    config = load_config()
    return _read_library_resource(
        find_artifact(config.library_dir, "watch_alerts", identity="library"),
        config,
        "No watch alerts found. Run distill topic-watch run after adding some watches.",
    )


@mcp.resource("distill://topics/{topic}/channels/{channel}/synthesis")
def get_channel_synthesis(topic: str, channel: str) -> str:
    """Read a channel's synthesis document."""
    config = load_config()
    path = find_artifact(
        config.channel_dir(topic, channel),
        "synthesis",
        identity=f"{topic}_{channel}",
    )
    content = _read_library_text(path, config)
    if content is not None:
        return content
    return f"No synthesis for {channel}. Run catch_up first."


@mcp.resource("distill://topics/{topic}/channels/{channel}/insights/{index}")
def get_video_insights(topic: str, channel: str, index: str) -> str:
    """Read insights for a specific video (1=newest).

    Args:
        topic: Topic name
        channel: Channel name
        index: Video number (1=newest, 2=second newest, etc.)
    """
    config = load_config()
    vid_list = video_list(config, topic, channel)
    try:
        idx = int(index)
    except ValueError:
        return f"Invalid index '{index}'. Use a number (1=newest)."

    if idx < 1 or idx > len(vid_list):
        return f"Video #{idx} not found. {channel} has {len(vid_list)} videos (1-{len(vid_list)})."

    video = vid_list[idx - 1]
    vid_dir = Path(video["_dir"])
    insights_file = find_artifact(vid_dir, "insights")
    raw_content = _read_library_text(insights_file, config)
    if raw_content is None:
        return f"No insights for '{video['title']}'. Video may not be analyzed yet."

    content = strip_frontmatter(raw_content)
    header = (
        f"# {video['title']}\n"
        f"**Date:** {video['upload_date'] or '?'} | "
        f"**Channel:** {channel} | "
        f"**Video {idx}/{len(vid_list)}**\n\n"
    )
    return header + content


@mcp.resource("distill://costs")
def get_costs() -> str:
    """Show recent cost history from past runs."""
    config = load_config()
    log_file = select_cost_log_path(config.library_dir)
    if log_file is None:
        return json.dumps(
            {
                "costs": [],
                "message": "No cost history yet.",
                "cost_history": CostLogScan().coverage(),
            }
        )

    cost_scan = scan_confined_cost_log(log_file, config.library_dir)
    recent = [project_cost_log_row(entry) for entry in cost_scan.rows[-20:]]
    total = sum(_cost_value(e) for e in recent)
    return json.dumps(
        {
            "recent_runs": recent,
            "total_cost": round(total, 4),
            "runs_shown": len(recent),
            "total_scope": "returned_valid_runs",
            "cost_history": cost_scan.coverage(),
            **(
                {"message": cost_history_integrity_message(log_file, cost_scan)}
                if not cost_scan.complete
                else {}
            ),
        },
        indent=2,
    )
