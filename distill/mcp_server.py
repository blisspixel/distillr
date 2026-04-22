"""Distill MCP Server -- expose YouTube intelligence tools to AI assistants.

Run with:  distill-mcp          (stdio transport, for Claude Desktop / IDE integrations)
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from distill.config import DistillConfig
from distill.costs import CostTracker, save_run_log
from distill.library import Library
from distill.state import ChannelState

mcp = FastMCP(
    "Distill",
    instructions=(
        "YouTube channels to strategic intelligence. "
        "Discover, transcribe, analyze, and synthesize YouTube content."
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────


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
            meta["has_transcript"] = (vid_dir / "transcript.txt").exists()
            meta["has_insights"] = (vid_dir / "insights.md").exists()
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


def _topic_source_inventory(config: DistillConfig, topic: str) -> dict:
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
            if (site_dir / "synthesis.md").exists():
                sites_with_synthesis += 1
            pages_dir = site_dir / "pages"
            if not pages_dir.exists():
                continue
            for page_dir in sorted(pages_dir.iterdir()):
                if not page_dir.is_dir():
                    continue
                if (page_dir / "content.md").exists() or (page_dir / "insights.md").exists():
                    page_count += 1

    papers_dir = config.papers_dir(topic)
    if papers_dir.exists():
        for paper_dir in sorted(papers_dir.iterdir()):
            if not paper_dir.is_dir():
                continue
            if (paper_dir / "insights.md").exists() or (paper_dir / "paper.md").exists():
                papers_with_insights += 1

    topic_dir = config.topic_dir(topic)
    artifacts = {
        "topic_synthesis": (topic_dir / "topic_synthesis.md").exists(),
        "paper_synthesis": (topic_dir / "paper_synthesis.md").exists(),
        "corpus_synthesis": (topic_dir / "corpus_synthesis.md").exists(),
        "topic_diff": (topic_dir / "topic_diff.md").exists(),
        "topic_trends": (topic_dir / "topic_trends.md").exists(),
        "report": (topic_dir / "report.md").exists(),
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


def _topic_gap_summary(config: DistillConfig, topic: str) -> dict:
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
            insights_path = Path(video.get("_dir", "")) / "insights.md"
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


# ── Tools ────────────────────────────────────────────────────────────


@mcp.tool()
def catch_up(
    channel: str | None = None,
    topic: str | None = None,
    days: int | None = None,
) -> str:
    """Refresh watched channels with lightweight scan analysis.

    Discovers new videos, transcribes, and runs fast scan analysis.
    Returns a summary of what was found and processed.

    Args:
        channel: Specific channel name to refresh (default: all watched)
        topic: Only refresh channels in this topic
        days: Override lookback days (default: per-channel setting)
    """
    from distill.cli_shared import ensure_channel_context, process_video
    from distill.discovery import discover_videos
    from distill.summary import ETATracker, RunSummary
    from distill.synthesis import synthesize_channel, synthesize_topic

    config = _config()
    if not config.xai_api_key:
        return "Error: XAI_API_KEY not configured. Run: python scripts/setup.py"

    lib = _lib(config)
    watchlist = lib.get_watchlist()
    if not watchlist:
        return "Watch list is empty. Use watch_add to start tracking channels."

    if channel:
        watchlist = [e for e in watchlist if e.name.lower() == channel.lower()]
        if not watchlist:
            return f"'{channel}' not on watch list."
    if topic:
        watchlist = [e for e in watchlist if e.topic.lower() == topic.lower()]
        if not watchlist:
            return f"No watched channels in topic '{topic}'."

    tracker = CostTracker()
    summary = RunSummary(command="catch-up")
    results = []
    topics_touched: set[str] = set()

    for entry in watchlist:
        ch_days = days if days is not None else entry.days
        try:
            videos = discover_videos(entry.url, days=ch_days, include_shorts=True, quiet=True)
        except Exception as exc:
            results.append({"channel": entry.name, "status": "error", "error": str(exc)})
            continue

        state = ChannelState(config.channel_dir(entry.topic, entry.name) / "state.json")
        new_vids = [v for v in videos if not state.is_processed(v.video_id)]

        if not new_vids:
            results.append(
                {
                    "channel": entry.name,
                    "status": "up_to_date",
                    "checked": len(videos),
                    "days": ch_days,
                }
            )
            continue

        # Process new videos
        ensure_channel_context(entry.topic, entry.name, new_vids, config, tracker)
        eta = ETATracker(total=len(new_vids))
        processed = []
        for vid in new_vids:
            success = process_video(
                entry.topic,
                entry.name,
                vid,
                config,
                tracker,
                summary,
                state=state,
                analysis_mode="scan",
                custom_instructions=entry.instructions,
                eta=eta,
            )
            processed.append({"title": vid.title, "success": success})

        with contextlib.suppress(Exception):
            synthesize_channel(entry.topic, entry.name, config, tracker=tracker)
        topics_touched.add(entry.topic)

        results.append(
            {
                "channel": entry.name,
                "status": "processed",
                "new_videos": len(new_vids),
                "videos": processed,
            }
        )

    for t in topics_touched:
        with contextlib.suppress(Exception):
            synthesize_topic(t, config, tracker=tracker)

    save_run_log(config.library_dir, summary.command, tracker)
    return json.dumps({"results": results, "cost": _cost_summary(tracker)}, indent=2)


@mcp.tool()
def search_videos(query: str, days: int = 60, limit: int = 5) -> str:
    """Preview the best recent YouTube videos for a topic (no processing).

    Searches YouTube, enriches metadata, and ranks by relevance.
    Returns a ranked list with scores and rationale.

    Args:
        query: Topic or question to search for
        days: Recency window in days
        limit: How many results to return
    """
    from distill.browser_search import search_youtube_results
    from distill.discovery import enrich_videos
    from distill.discovery import search_videos as yt_search
    from distill.ranking import rerank_videos

    config = _config()
    tracker = CostTracker()

    candidates = search_youtube_results(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        candidates = yt_search(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        return json.dumps({"results": [], "message": "No videos found"})

    # Dedupe
    seen = set()
    deduped = []
    for v in candidates:
        if v.video_id not in seen:
            seen.add(v.video_id)
            deduped.append(v)

    enriched = enrich_videos(deduped, max_videos=min(len(deduped), 12))
    ranked = rerank_videos(
        query,
        enriched,
        config,
        tracker=tracker,
        top_n=max(limit * 2, 10),
        use_llm=bool(config.xai_api_key),
    )

    results = []
    for item in ranked[:limit]:
        v = item.video
        results.append(
            {
                "title": v.title,
                "channel": v.channel_name or "unknown",
                "date": v.upload_date,
                "url": v.url,
                "duration": v.duration,
                "view_count": v.view_count,
                "score": round(item.final_score, 2),
                "rationale": item.rationale,
            }
        )

    return json.dumps({"results": results, "cost": _cost_summary(tracker)}, indent=2)


@mcp.tool()
def research_gaps(topic: str) -> str:
    """Assess what a topic corpus appears to be missing and suggest next actions.

    Uses local corpus heuristics to highlight thin coverage, missing artifacts,
    stale recency, and incomplete processing so an external agent can decide
    whether to trigger more ingestion, resynthesis, or reporting.

    Args:
        topic: Topic name to inspect
    """
    config = _config()
    return json.dumps(_topic_gap_summary(config, topic), indent=2)


@mcp.tool()
def learn_topic(
    query: str,
    topic: str | None = None,
    days: int = 60,
    limit: int = 5,
) -> str:
    """Find and process the best recent YouTube videos for a topic.

    Searches, ranks, transcribes, analyzes, and synthesizes.
    Creates insights per video and a topic synthesis.

    Args:
        query: Topic or question to learn about
        topic: Topic name to file under (default: derived from query)
        days: Recency window in days
        limit: How many videos to process
    """
    from distill.browser_search import search_youtube_results
    from distill.cli_shared import ensure_channel_context, process_video, topic_from_query
    from distill.discovery import enrich_videos
    from distill.discovery import search_videos as yt_search
    from distill.ranking import rerank_videos
    from distill.summary import ETATracker, RunSummary
    from distill.synthesis import synthesize_channel, synthesize_topic

    config = _config()
    if not config.xai_api_key:
        return "Error: XAI_API_KEY not configured."

    topic_name = topic or topic_from_query(query)
    tracker = CostTracker()

    # Search + rank
    candidates = search_youtube_results(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        candidates = yt_search(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        return json.dumps({"error": "No videos found for this query"})

    seen = set()
    deduped = [v for v in candidates if v.video_id not in seen and not seen.add(v.video_id)]
    enriched = enrich_videos(deduped, max_videos=min(len(deduped), 12))
    ranked = rerank_videos(
        query,
        enriched,
        config,
        tracker=tracker,
        top_n=max(limit * 2, 10),
        use_llm=bool(config.xai_api_key),
    )
    selected = ranked[:limit]

    # Group by channel
    grouped: dict[str, list] = {}
    for item in selected:
        ch = (item.video.channel_name or "unknown").strip() or "unknown"
        grouped.setdefault(ch, []).append(item.video)

    lib = _lib(config)
    summary = RunSummary(command="learn")
    processed_videos = []

    for channel_name, videos in grouped.items():
        channel_url = next((v.channel_url for v in videos if v.channel_url), "")
        if channel_url:
            lib.add_channel(topic_name, channel_url, channel_name)

        state = ChannelState(config.channel_dir(topic_name, channel_name) / "state.json")
        ensure_channel_context(topic_name, channel_name, videos, config, tracker)
        eta = ETATracker(total=len(videos))

        for vid in videos:
            if state.is_processed(vid.video_id):
                processed_videos.append({"title": vid.title, "status": "already_done"})
                continue
            success = process_video(
                topic_name,
                channel_name,
                vid,
                config,
                tracker,
                summary,
                state=state,
                eta=eta,
            )
            processed_videos.append({"title": vid.title, "status": "ok" if success else "failed"})

        with contextlib.suppress(Exception):
            synthesize_channel(topic_name, channel_name, config, tracker=tracker)

    with contextlib.suppress(Exception):
        synthesize_topic(topic_name, config, tracker=tracker)

    save_run_log(config.library_dir, summary.command, tracker)
    return json.dumps(
        {
            "topic": topic_name,
            "videos": processed_videos,
            "cost": _cost_summary(tracker),
        },
        indent=2,
    )


@mcp.tool()
def process_video_url(url: str, topic: str = "ai") -> str:
    """Transcribe and analyze a single YouTube video.

    Args:
        url: YouTube video URL
        topic: Topic to file under
    """
    from distill.cli_shared import ensure_channel_context, process_video, resolve_video_channel_name
    from distill.discovery import get_video_info, resolve_channel_name
    from distill.summary import RunSummary

    config = _config()
    if not config.xai_api_key:
        return "Error: XAI_API_KEY not configured."

    info = get_video_info(url)
    if not info:
        return "Error: Could not get video info. Check the URL."

    channel_name = resolve_video_channel_name(url, info, resolve_channel_name)
    tracker = CostTracker()
    summary = RunSummary(command="video")
    lib = _lib(config)
    lib.add_channel(topic, info.channel_url or url, channel_name)

    ensure_channel_context(topic, channel_name, [info], config, tracker)
    success = process_video(topic, channel_name, info, config, tracker, summary)

    result = {
        "title": info.title,
        "channel": channel_name,
        "success": success,
        "cost": _cost_summary(tracker),
    }

    if success:
        insights_file = (
            config.video_dir_slug(topic, channel_name, info.title, info.video_id) / "insights.md"
        )
        if insights_file.exists():
            result["insights"] = _strip_frontmatter(insights_file.read_text(encoding="utf-8"))

    save_run_log(config.library_dir, summary.command, tracker)
    return json.dumps(result, indent=2)


@mcp.tool()
def watch_add(
    url: str,
    topic: str = "watch",
    days: int = 14,
    instructions: str = "",
) -> str:
    """Add a YouTube channel to your watch list for regular catch-up.

    Args:
        url: YouTube channel URL
        topic: Topic to file under
        days: How far back catch-up looks (e.g., 2 for daily deals, 14 for weekly)
        instructions: Custom analysis instructions (e.g., "Extract top deals with prices")
    """
    from distill.discovery import discover_videos, resolve_channel_name

    config = _config()
    lib = _lib(config)
    name = resolve_channel_name(url)

    # Auto-generate instructions if none provided
    if not instructions and config.xai_api_key:
        try:
            vids = discover_videos(url, months=1, quiet=True)
            if vids:
                from distill.analysis import generate_watch_instructions

                auto = generate_watch_instructions(name, [v.title for v in vids[:15]], config)
                if auto and auto.strip():
                    instructions = auto.strip()
        except Exception:
            pass

    if lib.add_to_watchlist(url, name, topic=topic, instructions=instructions, days=days):
        return json.dumps(
            {
                "status": "added",
                "name": name,
                "topic": topic,
                "days": days,
                "instructions": instructions or "(auto-generated)" if instructions else "(none)",
            },
            indent=2,
        )
    return json.dumps({"status": "already_watching", "name": name})


@mcp.tool()
def watch_remove(name: str) -> str:
    """Remove a channel from your watch list.

    Args:
        name: Channel name to remove
    """
    lib = _lib()
    if lib.remove_from_watchlist(name):
        return json.dumps({"status": "removed", "name": name})
    return json.dumps({"status": "not_found", "name": name})


@mcp.tool()
def generate_report(topic: str, channel: str | None = None) -> str:
    """Generate a deep strategic intelligence report using Gemini Deep Research.

    This is a long-running operation. Returns the report markdown.

    Args:
        topic: Topic to report on
        channel: Specific channel (default: entire topic)
    """
    config = _config()
    if not config.gemini_api_key:
        return "Error: GEMINI_API_KEY not configured. Required for reports."

    from distill.accordion import run_accordion_research
    from distill.summary import RunSummary

    tracker = CostTracker()
    summary = RunSummary(command="report")
    scope = "channel" if channel else "topic"

    try:
        result = run_accordion_research(
            topic=topic,
            config=config,
            scope=scope,
            channel_name=channel,
            tracker=tracker,
        )
    except Exception as e:
        return json.dumps({"error": str(e)})

    save_run_log(config.library_dir, summary.command, tracker)

    if result:
        return json.dumps(
            {
                "status": "complete",
                "words": len(result.split()),
                "characters": len(result),
                "report": result[:5000] + "\n\n... (truncated, full report saved to disk)",
                "cost": _cost_summary(tracker),
            },
            indent=2,
        )
    return json.dumps({"status": "failed", "cost": _cost_summary(tracker)})


@mcp.tool()
def resynthesize_topic(topic: str, channel: str | None = None) -> str:
    """Regenerate synthesis from existing insights without re-analysis.

    Args:
        topic: Topic to resynthesize
        channel: Specific channel (default: all channels + topic)
    """
    from distill.corpus_analysis import synthesize_corpus
    from distill.synthesis import synthesize_channel, synthesize_topic

    config = _config()
    if not config.xai_api_key:
        return "Error: XAI_API_KEY not configured."

    lib = _lib(config)
    tracker = CostTracker()
    channels = lib.get_channels(topic)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]

    results = []
    for ch in channels:
        try:
            synthesize_channel(topic, ch.name, config, tracker=tracker)
            results.append({"channel": ch.name, "status": "ok"})
        except Exception as e:
            results.append({"channel": ch.name, "status": "error", "error": str(e)})

    if not channel:
        try:
            synthesize_topic(topic, config, tracker=tracker)
            results.append({"topic": topic, "status": "ok"})
        except Exception as e:
            results.append({"topic": topic, "status": "error", "error": str(e)})

        try:
            corpus = synthesize_corpus(topic, config, tracker=tracker)
            if corpus:
                results.append({"corpus": topic, "status": "ok"})
            else:
                results.append(
                    {"corpus": topic, "status": "skipped", "reason": "no mixed-source material"}
                )
        except Exception as e:
            results.append({"corpus": topic, "status": "error", "error": str(e)})

    return json.dumps({"results": results, "cost": _cost_summary(tracker)}, indent=2)


# ── Resources ────────────────────────────────────────────────────────


@mcp.resource("distill://topics")
def get_topics() -> str:
    """List all topics with channel counts and video counts."""
    config = _config()
    lib = _lib(config)
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


@mcp.resource("distill://watchlist")
def get_watchlist() -> str:
    """Show the watch list with per-channel settings."""
    lib = _lib()
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


@mcp.resource("distill://topics/{topic}/videos")
def get_topic_videos(topic: str) -> str:
    """List all processed videos in a topic with status."""
    config = _config()
    lib = _lib(config)
    channels = lib.get_channels(topic)
    all_videos = []
    for ch in channels:
        for v in _video_list(config, topic, ch.name):
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


@mcp.resource("distill://topics/{topic}/synthesis")
def get_topic_synthesis(topic: str) -> str:
    """Read the topic synthesis document."""
    config = _config()
    path = config.topic_dir(topic) / "topic_synthesis.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    # Fall back to first channel synthesis
    lib = _lib(config)
    channels = lib.get_channels(topic)
    for ch in channels:
        ch_path = config.channel_dir(topic, ch.name) / "synthesis.md"
        if ch_path.exists():
            return ch_path.read_text(encoding="utf-8")
    return f"No synthesis found for topic '{topic}'. Run catch_up or learn_topic first."


@mcp.resource("distill://topics/{topic}/corpus")
def get_topic_corpus(topic: str) -> str:
    """Read the mixed-source corpus synthesis document when available."""
    config = _config()
    return _read_markdown_resource(
        config.topic_dir(topic) / "corpus_synthesis.md",
        f"No corpus synthesis found for '{topic}'. Run distill corpus {topic} after the topic has multiple source types.",
    )


@mcp.resource("distill://topics/{topic}/sources")
def get_topic_sources(topic: str) -> str:
    """Show source inventory for a topic across videos, websites, and papers."""
    config = _config()
    return json.dumps(_topic_source_inventory(config, topic), indent=2)


@mcp.resource("distill://topics/{topic}/diff")
def get_topic_diff(topic: str) -> str:
    """Read the latest topic diff briefing when available."""
    config = _config()
    return _read_markdown_resource(
        config.topic_dir(topic) / "topic_diff.md",
        f"No topic diff found for '{topic}'. Run distill diff {topic} or topic-watch refresh first.",
    )


@mcp.resource("distill://topics/{topic}/trends")
def get_topic_trends(topic: str) -> str:
    """Read the latest topic trends summary when available."""
    config = _config()
    return _read_markdown_resource(
        config.topic_dir(topic) / "topic_trends.md",
        f"No topic trends found for '{topic}'. Run distill trends {topic} after accumulating change history.",
    )


@mcp.resource("distill://watch-alerts")
def get_watch_alerts() -> str:
    """Read the latest watch alert digest when available."""
    config = _config()
    return _read_markdown_resource(
        config.library_dir / "watch_alerts.md",
        "No watch alerts found. Run distill topic-watch run after adding some watches.",
    )


@mcp.resource("distill://topics/{topic}/channels/{channel}/synthesis")
def get_channel_synthesis(topic: str, channel: str) -> str:
    """Read a channel's synthesis document."""
    config = _config()
    path = config.channel_dir(topic, channel) / "synthesis.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"No synthesis for {channel}. Run catch_up first."


@mcp.resource("distill://topics/{topic}/channels/{channel}/insights/{index}")
def get_video_insights(topic: str, channel: str, index: str) -> str:
    """Read insights for a specific video (1=newest).

    Args:
        topic: Topic name
        channel: Channel name
        index: Video number (1=newest, 2=second newest, etc.)
    """
    config = _config()
    vid_list = _video_list(config, topic, channel)
    try:
        idx = int(index)
    except ValueError:
        return f"Invalid index '{index}'. Use a number (1=newest)."

    if idx < 1 or idx > len(vid_list):
        return f"Video #{idx} not found. {channel} has {len(vid_list)} videos (1-{len(vid_list)})."

    video = vid_list[idx - 1]
    vid_dir = Path(video["_dir"])
    insights_file = vid_dir / "insights.md"
    if not insights_file.exists():
        return f"No insights for '{video.get('title', 'Unknown')}'. Video may not be analyzed yet."

    content = _strip_frontmatter(insights_file.read_text(encoding="utf-8"))
    header = (
        f"# {video.get('title', 'Unknown')}\n"
        f"**Date:** {video.get('upload_date', '?')} | "
        f"**Channel:** {channel} | "
        f"**Video {idx}/{len(vid_list)}**\n\n"
    )
    return header + content


@mcp.resource("distill://costs")
def get_costs() -> str:
    """Show recent cost history from past runs."""
    config = _config()
    log_file = config.library_dir / "cost_log.jsonl"
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


# ── Prompts ──────────────────────────────────────────────────────────


@mcp.prompt()
def daily_deals(channel: str) -> str:
    """Get today's deals from a watched channel.

    Catches up on new videos and shows the latest insights.
    """
    return (
        f"1. Call the catch_up tool for channel '{channel}' to scan for new videos.\n"
        f"2. Read the resource distill://topics/deals/channels/{channel}/insights/1 "
        f"to get the latest video insights.\n"
        f"3. Summarize the best deals with prices, vendors, and savings. "
        f"Format as a numbered list, sorted by best value.\n"
        f"4. If catch_up found new videos, also read insights/2 and insights/3 "
        f"to check for any additional deals from recent videos."
    )


@mcp.prompt()
def morning_briefing() -> str:
    """Catch up on all watched channels and summarize what's new."""
    return (
        "1. Call the catch_up tool with no arguments to refresh all watched channels.\n"
        "2. Read distill://watch-alerts for the latest watch-level alerts if available.\n"
        "3. Read distill://topics to see what topics exist.\n"
        "4. For each topic that had new activity, read its synthesis "
        "(distill://topics/{topic}/synthesis).\n"
        "5. If available, also read distill://topics/{topic}/diff and "
        "distill://topics/{topic}/trends to capture what changed and whether momentum is rising or cooling.\n"
        "6. Create a concise morning briefing covering:\n"
        "   - What's new since last check\n"
        "   - Key developments or announcements\n"
        "   - Momentum or cooling signals\n"
        "   - Any actionable items or deals\n"
        "   Format with clear topic headers and bullet points."
    )


@mcp.prompt()
def topic_gap_review(topic: str) -> str:
    """Review what a tracked topic is missing before triggering more work."""
    return (
        f"1. Call research_gaps for topic '{topic}'.\n"
        f"2. Summarize the main gaps in corpus coverage, missing artifacts, or stale recency.\n"
        f"3. Recommend the smallest next Distill action to close each gap, such as learn_topic, catch_up, resynthesize_topic, distill diff, distill trends, or generate_report.\n"
        f"4. If the corpus already looks healthy, say so explicitly and explain why additional ingestion is not yet necessary."
    )


@mcp.prompt()
def topic_research(query: str) -> str:
    """Research a topic from YouTube content end-to-end."""
    return (
        f"1. Call search_videos with query '{query}' to preview the best videos.\n"
        f"2. Show the user the ranked results and ask if they want to proceed.\n"
        f"3. If yes, call learn_topic with query '{query}' to process the videos.\n"
        f"4. Read the topic synthesis to get the cross-video analysis.\n"
        f"5. Present a structured summary with:\n"
        f"   - Key findings and themes\n"
        f"   - Areas of consensus and disagreement\n"
        f"   - Actionable takeaways\n"
        f"   - Suggestions for deeper research if relevant"
    )


# ── Entry point ──────────────────────────────────────────────────────


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
