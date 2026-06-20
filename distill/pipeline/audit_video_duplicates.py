"""Exact source-identity duplicate checks for video audit reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class VideoOccurrence:
    """One video artifact carrying an exact source identity."""

    path: str
    channel: str
    title: str
    url: str


@dataclass(frozen=True)
class ExactVideoDuplicateGroup:
    """Video artifacts that point at the same YouTube video identity."""

    identity: str
    occurrences: list[VideoOccurrence]

    @property
    def members(self) -> int:
        return len(self.occurrences)


def _read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _youtube_identity_from_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    host = parsed.netloc.lower().removeprefix("www.")
    path_parts = [part for part in parsed.path.split("/") if part]
    video_id = ""
    if host in {
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
    }:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if (
            not video_id
            and len(path_parts) >= 2
            and path_parts[0]
            in {
                "embed",
                "live",
                "shorts",
                "v",
            }
        ):
            video_id = path_parts[1]
    elif host == "youtu.be" and path_parts:
        video_id = path_parts[0]
    return f"youtube:{video_id}" if video_id else ""


def _video_identity(metadata: dict) -> str:
    video_id = str(metadata.get("video_id") or "").strip()
    if video_id:
        return f"youtube:{video_id}"
    return _youtube_identity_from_url(str(metadata.get("url") or ""))


def _video_occurrence(topic_dir: Path, video_dir: Path, metadata: dict) -> VideoOccurrence:
    try:
        rel = video_dir.relative_to(topic_dir)
    except ValueError:
        rel_path = video_dir.as_posix()
        parts = ()
    else:
        rel_path = rel.as_posix()
        parts = rel.parts
    channel = parts[1] if len(parts) >= 3 and parts[0] == "channels" else ""
    return VideoOccurrence(
        path=rel_path,
        channel=channel,
        title=str(metadata.get("title") or video_dir.name),
        url=str(metadata.get("url") or ""),
    )


def collect_exact_video_duplicates(topic_dir: Path) -> list[ExactVideoDuplicateGroup]:
    """Group video artifacts with the same exact YouTube identity.

    This is an exact source-identity check, not a content-quality or semantic
    similarity judgment. Missing, corrupt, or non-object metadata is ignored.
    """
    videos_root = topic_dir / "channels"
    if not videos_root.exists():
        return []

    by_identity: dict[str, list[VideoOccurrence]] = {}
    for metadata_path in sorted(videos_root.glob("*/videos/*/metadata.json")):
        video_dir = metadata_path.parent
        metadata = _read_json_object(metadata_path)
        identity = _video_identity(metadata)
        if not identity:
            continue
        by_identity.setdefault(identity, []).append(
            _video_occurrence(topic_dir, video_dir, metadata)
        )

    return [
        ExactVideoDuplicateGroup(identity=identity, occurrences=sorted(items, key=lambda o: o.path))
        for identity, items in sorted(by_identity.items())
        if len(items) > 1
    ]


def render_exact_video_duplicates_section(
    groups: list[ExactVideoDuplicateGroup],
) -> list[str]:
    lines = ["## Exact duplicate videos (same YouTube identity)", ""]
    if not groups:
        return [*lines, "- No duplicate video identities found."]
    lines.append(
        "- These artifact directories point at the same source video. Review before deleting "
        "anything, because a duplicate may be intentional cross-topic filing."
    )
    lines.append("")
    for group in groups[:10]:
        lines.append(f"- `{group.identity}` appears in {group.members} artifact directories:")
        lines += [
            f"  - `{item.path}`"
            + (f" - {item.title}" if item.title else "")
            + (f" ({item.channel})" if item.channel else "")
            for item in group.occurrences[:8]
        ]
        if len(group.occurrences) > 8:
            lines.append(f"  - ... and {len(group.occurrences) - 8} more")
    if len(groups) > 10:
        lines.append(f"- ... and {len(groups) - 10} more groups")
    return lines
