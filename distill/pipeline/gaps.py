# pyright: strict
"""Corpus coverage / research-gap analysis for a topic.

Lifted out of the MCP server so both the `research_gaps` tool and the
`discover --from-gaps` command (and any future caller) share one implementation
without `commands -> mcp` coupling. Pure filesystem inspection over the library:
counts sources, checks for the expected synthesis artifacts, and emits a
gap summary plus recommended next actions. No LLM, no network.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from distill.config import DistillConfig
from distill.library import Library
from distill.library.confined import read_confined_text
from distill.library.paths import artifact_exists, find_artifact, strip_frontmatter

# Ceiling for the thin-insight scan; matches the sibling MCP readers.
_MAX_INSIGHTS_SCAN_BYTES = 1024 * 1024

__all__ = [
    "gap_discovery_goal",
    "topic_gap_summary",
    "topic_source_inventory",
    "video_list",
]


type JsonObject = dict[str, object]


class VideoMetadata(TypedDict):
    title: str
    upload_date: str
    _dir: str
    has_transcript: bool
    has_insights: bool
    duration: int
    url: str
    analysis_mode: str


class TopicInventory(TypedDict):
    topic: str
    channels: int
    videos: int
    sites: int
    pages: int
    papers: int
    x_posts: int
    active_source_types: list[str]
    artifacts: dict[str, bool]
    latest_video_date: str | None


class TopicGapSummary(TypedDict):
    topic: str
    channels: int
    videos: int
    sites: int
    pages: int
    papers: int
    x_posts: int
    active_source_types: list[str]
    latest_video_date: str | None
    recency_status: str
    missing_artifacts: list[str]
    missing_insights: list[str]
    missing_transcripts: list[str]
    thin_insights: list[str]
    gaps: list[str]
    recommended_actions: list[str]
    next_actions: list[str]
    _error: NotRequired[str]


def _parse_upload_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None


def _read_json_object(path: Path) -> JsonObject | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, RecursionError, UnicodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return cast("JsonObject", data)


def _string_value(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int_value(value: object, default: int = 0) -> int:
    try:
        parsed = int(value) if isinstance(value, str) else value
    except ValueError:
        return default
    if isinstance(parsed, bool) or not isinstance(parsed, int):
        return default
    return parsed


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in cast(list[object], value) if isinstance(item, str)]


def _video_title(video: VideoMetadata) -> str:
    return video.get("title", "Unknown")


def video_list(config: DistillConfig, topic: str, channel_name: str) -> list[VideoMetadata]:
    """Collect and sort a channel's videos (newest first) with artifact flags."""
    videos_dir = config.videos_dir(topic, channel_name)
    if not videos_dir.exists():
        return []
    vid_list: list[VideoMetadata] = []
    for vid_dir in videos_dir.iterdir():
        if not vid_dir.is_dir():
            continue
        meta_file = vid_dir / "metadata.json"
        if meta_file.exists():
            # Degrade on a corrupt metadata.json (e.g. interrupted run) instead
            # of crashing the MCP resources/tools that read this, matching every
            # sibling reader (web routes, dashboard_data).
            raw_meta = _read_json_object(meta_file)
            if raw_meta is None:
                continue  # valid JSON but not an object -> not usable metadata
            meta: VideoMetadata = {
                "title": _string_value(raw_meta.get("title"), "Unknown"),
                "upload_date": _string_value(raw_meta.get("upload_date")),
                "_dir": str(vid_dir),
                "has_transcript": artifact_exists(vid_dir, "transcript", extension="txt"),
                "has_insights": artifact_exists(vid_dir, "insights"),
                "duration": _int_value(raw_meta.get("duration")),
                "url": _string_value(raw_meta.get("url")),
                "analysis_mode": _string_value(raw_meta.get("analysis_mode"), "unknown"),
            }
            vid_list.append(meta)
    vid_list.sort(key=lambda v: v.get("upload_date", ""), reverse=True)
    return vid_list


def topic_source_inventory(  # noqa: C901 - legacy shape
    config: DistillConfig, topic: str
) -> TopicInventory:
    """Count a topic's sources and which synthesis artifacts exist."""
    lib = Library(config)
    channel_names = lib.get_corpus_channel_names(topic)
    video_count = 0
    sites_with_synthesis = 0
    page_count = 0
    papers_with_insights = 0
    dates: list[datetime] = []

    for channel_name in channel_names:
        for video in video_list(config, topic, channel_name):
            video_count += 1
            upload_dt = _parse_upload_date(video.get("upload_date"))
            if upload_dt is not None:
                dates.append(upload_dt)

    sites_dir = config.sites_dir(topic)
    if sites_dir.exists():
        for site_dir in sorted(sites_dir.iterdir()):
            if not site_dir.is_dir():
                continue
            if artifact_exists(site_dir, "site_synthesis", identity=f"{topic}_{site_dir.name}"):
                sites_with_synthesis += 1
            pages_dir = site_dir / "pages"
            if not pages_dir.exists():
                continue
            for page_dir in sorted(pages_dir.iterdir()):
                if not page_dir.is_dir():
                    continue
                if artifact_exists(page_dir, "content") or artifact_exists(page_dir, "insights"):
                    page_count += 1

    papers_dir = config.papers_dir(topic)
    if papers_dir.exists():
        for paper_dir in sorted(papers_dir.iterdir()):
            if not paper_dir.is_dir():
                continue
            if artifact_exists(paper_dir, "insights") or artifact_exists(paper_dir, "paper"):
                papers_with_insights += 1

    topic_dir = config.topic_dir(topic)
    x_posts_with_insights = 0
    x_dir = topic_dir / "x"
    if x_dir.exists():
        for post_dir in sorted(x_dir.glob("*/posts/*")):
            if post_dir.is_dir() and artifact_exists(post_dir, "insights"):
                x_posts_with_insights += 1

    artifacts = {
        "topic_synthesis": artifact_exists(topic_dir, "topic_synthesis", identity=topic),
        "paper_synthesis": artifact_exists(topic_dir, "paper_synthesis", identity=topic),
        "corpus_synthesis": artifact_exists(topic_dir, "corpus_synthesis", identity=topic),
        "topic_diff": artifact_exists(topic_dir, "topic_diff", identity=topic),
        "topic_trends": artifact_exists(topic_dir, "topic_trends", identity=topic),
        "report": artifact_exists(topic_dir, "report", identity=topic),
    }
    active_source_types = [
        name
        for name, present in {
            "youtube": video_count > 0,
            "website": page_count > 0 or sites_with_synthesis > 0,
            "paper": papers_with_insights > 0,
            "x": x_posts_with_insights > 0,
        }.items()
        if present
    ]

    latest = max(dates) if dates else None
    return {
        "topic": topic,
        "channels": len(channel_names),
        "videos": video_count,
        "sites": sites_with_synthesis,
        "pages": page_count,
        "papers": papers_with_insights,
        "x_posts": x_posts_with_insights,
        "active_source_types": active_source_types,
        "artifacts": artifacts,
        "latest_video_date": latest.strftime("%Y-%m-%d") if latest else None,
    }


def topic_gap_summary(config: DistillConfig, topic: str) -> TopicGapSummary:  # noqa: C901
    """Compute coverage gaps + recommended next actions for a topic."""
    inventory = topic_source_inventory(config, topic)
    lib = Library(config)
    channel_names = lib.get_corpus_channel_names(topic)
    missing_insights: list[str] = []
    missing_transcripts: list[str] = []
    thin_insights: list[str] = []
    dates: list[datetime] = []

    for channel_name in channel_names:
        for video in video_list(config, topic, channel_name):
            upload_dt = _parse_upload_date(video.get("upload_date"))
            if upload_dt is not None:
                dates.append(upload_dt)
            if not video.get("has_insights", False):
                missing_insights.append(f"{channel_name}: {_video_title(video)}")
            if not video.get("has_transcript", False):
                missing_transcripts.append(f"{channel_name}: {_video_title(video)}")
            insights_path = find_artifact(Path(video.get("_dir", "")), "insights")
            # Bounded, confined read like every sibling MCP reader. This was a
            # plain ``read_text`` with no byte ceiling and no symlink/inode
            # validation, reached from the ungated ``research_gaps`` tool, so a
            # single oversized, escaping, or non-UTF-8 artifact could exhaust
            # memory or raise out of the tool. Unreadable counts as not-thin.
            insights_text = read_confined_text(
                insights_path,
                config.library_dir,
                max_bytes=_MAX_INSIGHTS_SCAN_BYTES,
            )
            if insights_text is not None and len(strip_frontmatter(insights_text).strip()) < 800:
                thin_insights.append(f"{channel_name}: {_video_title(video)}")

    missing_artifacts = [name for name, present in inventory["artifacts"].items() if not present]
    latest = max(dates) if dates else None
    stale_cutoff = datetime.now() - timedelta(days=7)
    stale_status = "stale" if latest and latest < stale_cutoff else "fresh"
    if latest is None:
        stale_status = "unknown"

    gaps: list[str] = []
    next_actions: list[str] = []

    if inventory["channels"] < 3:
        gaps.append(f"Only {inventory['channels']} channel(s) are available for this topic.")
        next_actions.append(
            f"Run learn_topic or latest again for '{topic}' with broader queries to widen coverage."
        )
    if inventory["videos"] < 5:
        gaps.append(f"Only {inventory['videos']} processed video(s) are available for this topic.")
    if len(inventory["active_source_types"]) <= 1:
        source_label = (
            inventory["active_source_types"][0] if inventory["active_source_types"] else "none"
        )
        gaps.append(f"Coverage is effectively single-source ({source_label}).")
        next_actions.append(
            f"Add website or paper sources to '{topic}' if you need stronger cross-source validation."
        )
    if inventory["pages"] and not inventory["artifacts"].get("corpus_synthesis"):
        gaps.append(
            "Website material exists, but no mixed-source corpus synthesis has been generated yet."
        )
        next_actions.append(
            f"Run distill corpus {topic} to merge website findings with the rest of the topic corpus."
        )
    if inventory["papers"] and not inventory["artifacts"].get("corpus_synthesis"):
        gaps.append(
            "Paper material exists, but no mixed-source corpus synthesis has been generated yet."
        )
        next_actions.append(
            f"Run distill corpus {topic} to merge paper findings with the rest of the topic corpus."
        )
    if missing_insights:
        gaps.append(f"{len(missing_insights)} video(s) are missing insights.")
        next_actions.append("Reprocess incomplete videos so synthesis is based on full insights.")
    if missing_transcripts:
        gaps.append(f"{len(missing_transcripts)} video(s) are missing transcripts.")
        next_actions.append("Re-run transcription for incomplete videos before deeper synthesis.")
    if thin_insights:
        gaps.append(f"{len(thin_insights)} insight file(s) look unusually thin.")
    if "topic_synthesis" in missing_artifacts and "corpus_synthesis" in missing_artifacts:
        gaps.append("Topic synthesis has not been generated yet.")
        next_actions.append(f"Run resynthesize_topic or a topic synthesis workflow for '{topic}'.")
    if "corpus_synthesis" in missing_artifacts and len(inventory["active_source_types"]) > 1:
        gaps.append("Mixed-source corpus synthesis is missing for a multi-source topic.")
        next_actions.append(f"Run distill corpus {topic} to create a combined cross-source view.")
    if "topic_diff" in missing_artifacts:
        gaps.append("No topic diff is available yet.")
        next_actions.append(f"Run distill diff {topic} to establish a change baseline.")
    if "topic_trends" in missing_artifacts:
        gaps.append("No topic trend summary is available yet.")
        next_actions.append(f"Run distill trends {topic} after at least two diff windows exist.")
    if latest is None:
        gaps.append("No valid upload dates were found, so recency cannot be assessed.")
    elif stale_status == "stale":
        gaps.append(
            f"Latest processed coverage is older than 7 days ({latest.strftime('%Y-%m-%d')})."
        )
        next_actions.append(
            f"Refresh '{topic}' with a recent search window to get current coverage."
        )
    if "report" in missing_artifacts and inventory["videos"] >= 3:
        next_actions.append(
            f"Run generate_report for '{topic}' if you need a shareable synthesis document."
        )

    if not gaps:
        gaps.append("No major research gaps detected from the local corpus heuristics.")
    if not next_actions:
        next_actions.append("No immediate follow-on action required.")

    return {
        "topic": topic,
        "channels": inventory["channels"],
        "videos": inventory["videos"],
        "sites": inventory["sites"],
        "pages": inventory["pages"],
        "papers": inventory["papers"],
        "x_posts": inventory["x_posts"],
        "active_source_types": inventory["active_source_types"],
        "latest_video_date": latest.strftime("%Y-%m-%d") if latest else None,
        "recency_status": stale_status,
        "missing_artifacts": missing_artifacts,
        "missing_insights": missing_insights[:10],
        "missing_transcripts": missing_transcripts[:10],
        "thin_insights": thin_insights[:10],
        "gaps": gaps,
        "recommended_actions": next_actions,
        "next_actions": next_actions,
    }


def gap_discovery_goal(summary: TopicGapSummary | JsonObject) -> str:
    """Turn a gap summary into a discovery goal string for `discover --from-gaps`.

    Phrases the corpus's thin spots as a research goal the existing query
    generation can fan out from. Empty/no-gap corpora get a generic broadening
    goal so discovery still does something useful.
    """
    topic = _string_value(summary.get("topic"), "this topic")
    gaps = [
        g
        for g in _string_list(summary.get("gaps"))
        if "No major research gaps" not in g and "cannot be assessed" not in g
    ]
    sources = _string_list(summary.get("active_source_types"))
    parts = [f"Broaden and strengthen coverage of {topic}."]
    if gaps:
        parts.append("The current corpus has these gaps: " + " ".join(gaps))
    if len(sources) <= 1:
        parts.append(
            "Prioritize source types not yet represented (papers, websites, or videos) to enable "
            "cross-source validation."
        )
    parts.append(
        "Find recent, substantive sources that fill these gaps rather than restating what is already covered."
    )
    return " ".join(parts)
