# pyright: strict
"""Section-targeted corpus material for sequential reports."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

from distill.config import DistillConfig
from distill.library.paths import find_artifact
from distill.library.wikilinks import emit_wiki_link

logger = logging.getLogger(__name__)

type ChannelRef = tuple[str, str]


def gather_tagged_materials(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> dict[str, str]:
    """Gather section-specific source material from the corpus."""

    tagged: dict[str, str] = {}
    syntheses = load_syntheses(topic, config, scope, channel_name)
    if syntheses:
        tagged["creator_consensus"] = syntheses
        tagged["creator_accuracy"] = syntheses

    vendor_insights = load_tagged_insights(
        topic,
        config,
        scope,
        channel_name,
        keywords=["Microsoft", "Azure", "Google", "AWS", "NVIDIA", "OpenAI", "Anthropic"],
        max_chars=30000,
    )
    if vendor_insights:
        tagged["vendor_battleground"] = vendor_insights

    enterprise_insights = load_tagged_insights(
        topic,
        config,
        scope,
        channel_name,
        keywords=["enterprise", "customer", "production", "deploy", "ROI", "TCO", "pricing"],
        max_chars=20000,
    )
    if enterprise_insights:
        tagged["enterprise_reality"] = enterprise_insights
    return tagged


def load_syntheses(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> str:
    """Load channel and topic syntheses as supplementary material."""

    parts: list[str] = []
    channels = channels_for_scope(topic, config, scope, channel_name)
    for current_topic, channel in channels:
        synth_file = find_artifact(
            config.channel_dir(current_topic, channel),
            "synthesis",
            identity=f"{current_topic}_{channel}",
        )
        if synth_file.exists():
            link = emit_wiki_link(
                f"Channel synthesis: {channel}",
                f"{current_topic}_{channel}",
                "synthesis",
            )
            body = synth_file.read_text(encoding="utf-8")
            parts.append(f"### {channel} Channel Synthesis\nSource: {link}\n{body}")

    topic_synth = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
    if topic_synth.exists():
        link = emit_wiki_link(f"Topic synthesis: {topic}", topic, "topic_synthesis")
        body = topic_synth.read_text(encoding="utf-8")
        parts.append(f"### Topic Synthesis: {topic}\nSource: {link}\n{body}")
    return "\n\n".join(parts) if parts else ""


def load_tagged_insights(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
    keywords: list[str],
    max_chars: int = 30000,
) -> str:
    """Load insights that mention specific keywords."""

    channels = channels_for_scope(topic, config, scope, channel_name)
    matching: list[str] = []
    total_chars = 0
    keywords_lower = [keyword.lower() for keyword in keywords]
    for current_topic, channel in channels:
        videos_dir = config.videos_dir(current_topic, channel)
        if not videos_dir.exists():
            continue
        for video_dir in sorted(videos_dir.iterdir()):
            if not video_dir.is_dir():
                continue
            insights_file = find_artifact(video_dir, "insights")
            if not insights_file.exists():
                continue
            content = insights_file.read_text(encoding="utf-8")
            if not any(keyword in content.lower() for keyword in keywords_lower):
                continue
            title, source_id = read_video_metadata_title_and_id(
                video_dir / "metadata.json", fallback=video_dir.name
            )
            link = emit_wiki_link(title, source_id, "insights")
            entry = f"**{title}** ({channel}) {link}:\n{content}\n"
            if total_chars + len(entry) > max_chars:
                break
            matching.append(entry)
            total_chars += len(entry)
    return "\n---\n".join(matching) if matching else ""


def channels_for_scope(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> list[ChannelRef]:
    """Resolve topic and channel pairs for one report scope."""

    if scope == "channel" and channel_name:
        return [(topic, channel_name)]
    if scope == "topic":
        channels_dir = config.topic_dir(topic) / "channels"
        if not channels_dir.exists():
            return []
        return [(topic, child.name) for child in sorted(channels_dir.iterdir()) if child.is_dir()]

    channels: list[ChannelRef] = []
    topics_root = config.topics_dir()
    if not topics_root.exists():
        return channels
    for topic_dir in sorted(topics_root.iterdir()):
        if not topic_dir.is_dir():
            continue
        channels_dir = topic_dir / "channels"
        if channels_dir.exists():
            channels.extend(
                (topic_dir.name, child.name)
                for child in sorted(channels_dir.iterdir())
                if child.is_dir()
            )
    return channels


def read_video_metadata_title_and_id(meta_file: Path, fallback: str) -> tuple[str, str]:
    """Read safe display and source identities from one video metadata receipt."""

    if not meta_file.exists():
        return fallback, fallback
    try:
        raw = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Ignoring unreadable video metadata at %s: %s", meta_file, exc)
        return fallback, fallback
    if not isinstance(raw, dict):
        logger.debug("Ignoring non-object video metadata at %s", meta_file)
        return fallback, fallback
    meta = cast("dict[str, Any]", raw)
    title = meta.get("title")
    source_id = meta.get("video_id")
    return (
        title if isinstance(title, str) and title else fallback,
        source_id if isinstance(source_id, str) and source_id else fallback,
    )
