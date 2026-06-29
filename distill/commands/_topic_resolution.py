"""Topic and channel resolution helpers shared by command modules."""

from __future__ import annotations

import typer

from distill.library import Library

__all__ = ["resolve_required_topic_for_channel", "resolve_topic_for_channel"]


def resolve_topic_for_channel(
    lib: Library, topic: str | None, channel: str | None
) -> tuple[str | None, str | None]:
    """Auto-resolve topic when only a channel name is given."""
    if topic and channel:
        return topic, channel
    if topic and not channel and topic not in lib.get_topics():
        found = lib.find_channel(topic)
        if found:
            return found.topic, found.name
    if channel and not topic:
        found = lib.find_channel(channel)
        if found:
            return found.topic, found.name
    return topic, channel


def resolve_required_topic_for_channel(
    lib: Library, topic: str | None, channel: str | None
) -> tuple[str, str | None]:
    resolved_topic, resolved_channel = resolve_topic_for_channel(lib, topic, channel)
    if resolved_topic is None:
        raise typer.BadParameter("Topic is required")
    return resolved_topic, resolved_channel
