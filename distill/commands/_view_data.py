# pyright: strict
"""Structured data helpers for corpus-browsing commands."""

from __future__ import annotations

from pathlib import Path

from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_exists
from distill.library.state import ChannelState
from distill.pipeline.dashboard_records import JsonObject, json_object


def read_json_object(path: Path) -> JsonObject | None:
    try:
        from distill.parsing import strict_json_loads

        return json_object(strict_json_loads(path.read_text(encoding="utf-8")))
    except (OSError, RecursionError, UnicodeError, ValueError):
        return None


def text_field(record: JsonObject, key: str, default: str = "") -> str:
    value = record.get(key)
    return default if value is None else str(value)


def int_field(record: JsonObject, key: str, default: int = 0) -> int:
    value = record.get(key)
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (OverflowError, ValueError):
            return default
    return default


def bool_field(record: JsonObject, key: str, default: bool = False) -> bool:
    value = record.get(key)
    return value if isinstance(value, bool) else default


def path_field(record: JsonObject, key: str) -> Path | None:
    value = record.get(key)
    return value if isinstance(value, Path) else None


def video_metadata(videos_dir: Path) -> list[JsonObject]:
    """Read usable video records from a channel directory, newest first."""
    if not videos_dir.exists():
        return []
    videos: list[JsonObject] = []
    for video_dir in sorted(videos_dir.iterdir()):
        if not video_dir.is_dir():
            continue
        metadata_path = video_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata = read_json_object(metadata_path)
        if metadata is None:
            continue
        metadata["_dir"] = video_dir
        metadata["_has_transcript"] = artifact_exists(
            video_dir,
            "transcript",
            extension="txt",
        )
        metadata["_has_insights"] = artifact_exists(video_dir, "insights")
        videos.append(metadata)
    videos.sort(key=lambda video: text_field(video, "upload_date"), reverse=True)
    return videos


def channel_video_count(config: DistillConfig, topic: str, channel_name: str) -> int:
    """Use registered state when present, with a direct-ingest disk fallback."""
    channel_dir = config.channel_dir(topic, channel_name)
    state_path = channel_dir / "state.json"
    if state_path.exists():
        return ChannelState(state_path).get_processed_count()
    return len(video_metadata(channel_dir / "videos"))


def library_action_hints(topic: str, has_registered_channels: bool) -> str:
    hints = [f"distill videos {topic}", f"distill synthesis {topic}"]
    if has_registered_channels:
        hints.append(f"distill run {topic} --refresh")
    return "  |  ".join(hints)


def topic_artifact_labels(topic_dir: Path, topic: str) -> list[str]:
    return [
        label
        for label, artifact_type in (
            ("topic synthesis", "topic_synthesis"),
            ("corpus synthesis", "corpus_synthesis"),
            ("paper synthesis", "paper_synthesis"),
            ("report", "report"),
        )
        if artifact_exists(topic_dir, artifact_type, identity=topic)
    ]


def library_payload(
    config: DistillConfig,
    library: Library,
    topics: list[str],
) -> dict[str, object]:
    """Structured library inventory for ``--json`` (topics -> channels + artifacts)."""
    result: list[dict[str, object]] = []
    for topic in topics:
        channels: list[dict[str, object]] = []
        registered = {channel.name.casefold() for channel in library.get_channels(topic)}
        for channel_name in library.get_corpus_channel_names(topic):
            channel_dir = config.channel_dir(topic, channel_name)
            state = ChannelState(channel_dir / "state.json")
            artifacts = [
                name
                for name, present in (
                    (
                        "synthesis",
                        artifact_exists(
                            channel_dir,
                            "synthesis",
                            identity=f"{topic}_{channel_name}",
                        ),
                    ),
                    (
                        "report",
                        artifact_exists(
                            channel_dir,
                            "report",
                            identity=f"{topic}_{channel_name}",
                        ),
                    ),
                )
                if present
            ]
            channels.append(
                {
                    "name": channel_name,
                    "registered": channel_name.casefold() in registered,
                    "videos": channel_video_count(config, topic, channel_name),
                    "last_refresh": state.get_last_refresh() or None,
                    "artifacts": artifacts,
                }
            )
        topic_dir = config.topic_dir(topic)
        topic_artifacts = [
            name
            for name, present in (
                (
                    "topic_synthesis",
                    artifact_exists(topic_dir, "topic_synthesis", identity=topic),
                ),
                (
                    "corpus_synthesis",
                    artifact_exists(topic_dir, "corpus_synthesis", identity=topic),
                ),
                (
                    "paper_synthesis",
                    artifact_exists(topic_dir, "paper_synthesis", identity=topic),
                ),
                ("report", artifact_exists(topic_dir, "report", identity=topic)),
            )
            if present
        ]
        result.append(
            {
                "topic": topic,
                "channels": channels,
                "topic_artifacts": topic_artifacts,
            }
        )
    return {"topics": result, "count": len(result)}
