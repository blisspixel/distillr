"""Distill MCP Server -- transport, registration, and lifecycle.

Run with:  distill-mcp          (stdio transport, for Claude Desktop / IDE integrations)

This module creates the FastMCP instance and wires all tools, resources,
and prompts from their respective submodules.  No business logic lives here.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_exists, find_artifact
from distill.pipeline.costs import CostTracker

__all__ = ["main", "mcp"]

mcp = FastMCP(
    "Distill",
    instructions=(
        "YouTube channels to strategic intelligence. "
        "Discover, transcribe, analyze, and synthesize YouTube content."
    ),
)


# ── Shared helpers (used by tools, resources, prompts) ───────────────


def _config() -> DistillConfig:
    load_dotenv()
    return DistillConfig()


def _lib(config: DistillConfig | None = None) -> Library:
    return Library(config or _config())


def _video_list(config: DistillConfig, topic: str, channel_name: str) -> list[dict]:
    """Collect and sort videos for a channel, newest first."""
    videos_dir = config.videos_dir(topic, channel_name)
    if not videos_dir.exists():
        return []
    vid_list = []
    for vid_dir in videos_dir.iterdir():
        if not vid_dir.is_dir():
            continue
        meta_file = vid_dir / "metadata.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["_dir"] = str(vid_dir)
            meta["has_transcript"] = artifact_exists(vid_dir, "transcript", extension="txt")
            meta["has_insights"] = artifact_exists(vid_dir, "insights")
            vid_list.append(meta)
    vid_list.sort(key=lambda v: v.get("upload_date", ""), reverse=True)
    return vid_list


def _cost_summary(tracker: CostTracker) -> dict:
    return {
        "total_cost": round(tracker.total_cost, 6),
        "total_input_tokens": tracker.total_input_tokens,
        "total_output_tokens": tracker.total_output_tokens,
        "calls": len(tracker.entries),
    }


def _strip_frontmatter(content: str) -> str:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


def _read_markdown_resource(path: Path, missing_message: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return missing_message


def _parse_upload_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None


def _topic_source_inventory(config: DistillConfig, topic: str) -> dict:  # noqa: C901 — legacy, will refactor
    lib = _lib(config)
    channels = lib.get_channels(topic)
    video_count = 0
    sites_with_synthesis = 0
    page_count = 0
    papers_with_insights = 0
    dates: list[datetime] = []

    for ch in channels:
        for video in _video_list(config, topic, ch.name):
            video_count += 1
            upload_dt = _parse_upload_date(video.get("upload_date"))
            if upload_dt is not None:
                dates.append(upload_dt)

    sites_dir = config.sites_dir(topic)
    if sites_dir.exists():
        for site_dir in sorted(sites_dir.iterdir()):
            if not site_dir.is_dir():
                continue
            if artifact_exists(
                site_dir,
                "site_synthesis",
                identity=f"{topic}_{site_dir.name}",
            ):
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
        }.items()
        if present
    ]

    latest = max(dates) if dates else None
    return {
        "topic": topic,
        "channels": len(channels),
        "videos": video_count,
        "sites": sites_with_synthesis,
        "pages": page_count,
        "papers": papers_with_insights,
        "active_source_types": active_source_types,
        "artifacts": artifacts,
        "latest_video_date": latest.strftime("%Y-%m-%d") if latest else None,
    }


def _topic_gap_summary(config: DistillConfig, topic: str) -> dict:  # noqa: C901 — legacy, will refactor
    inventory = _topic_source_inventory(config, topic)
    lib = _lib(config)
    channels = lib.get_channels(topic)
    missing_insights = []
    missing_transcripts = []
    thin_insights = []
    dates: list[datetime] = []

    for ch in channels:
        channel_videos = _video_list(config, topic, ch.name)
        for video in channel_videos:
            upload_dt = _parse_upload_date(video.get("upload_date"))
            if upload_dt is not None:
                dates.append(upload_dt)
            if not video.get("has_insights", False):
                missing_insights.append(f"{ch.name}: {video.get('title', 'Unknown')}")
            if not video.get("has_transcript", False):
                missing_transcripts.append(f"{ch.name}: {video.get('title', 'Unknown')}")
            insights_path = find_artifact(Path(video.get("_dir", "")), "insights")
            if (
                insights_path.exists()
                and len(_strip_frontmatter(insights_path.read_text(encoding="utf-8")).strip()) < 800
            ):
                thin_insights.append(f"{ch.name}: {video.get('title', 'Unknown')}")

    missing_artifacts = [name for name, present in inventory["artifacts"].items() if not present]
    latest = max(dates) if dates else None
    stale_cutoff = datetime.now() - timedelta(days=7)
    stale_status = "stale" if latest and latest < stale_cutoff else "fresh"
    if latest is None:
        stale_status = "unknown"

    gaps = []
    next_actions = []

    if inventory["channels"] < 3:
        gaps.append(f"Only {inventory['channels']} channel(s) are tracked for this topic.")
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
    if "topic_synthesis" in missing_artifacts:
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
        "active_source_types": inventory["active_source_types"],
        "latest_video_date": latest.strftime("%Y-%m-%d") if latest else None,
        "recency_status": stale_status,
        "missing_artifacts": missing_artifacts,
        "missing_insights": missing_insights[:10],
        "missing_transcripts": missing_transcripts[:10],
        "thin_insights": thin_insights[:10],
        "gaps": gaps,
        "recommended_actions": next_actions,
    }


# ── Wire tools, resources, and prompts from submodules ───────────────

# Import submodules so their @mcp decorators register on the shared instance.
# The submodules import ``mcp`` from this module and decorate their handlers.
import distill.mcp.prompts as _prompts  # noqa: E402, F401, I001
import distill.mcp.resources as _resources  # noqa: E402, F401
import distill.mcp.tools.discover as _tools_discover  # noqa: E402, F401
import distill.mcp.tools.gaps as _tools_gaps  # noqa: E402, F401
import distill.mcp.tools.reports as _tools_reports  # noqa: E402, F401
import distill.mcp.tools.topics as _tools_topics  # noqa: E402, F401
import distill.mcp.tools.watch as _tools_watch  # noqa: E402, F401


# ── Entry point ──────────────────────────────────────────────────────


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
