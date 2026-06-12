"""MCP tools — discovery: learn_topic, search_videos, discover."""

from __future__ import annotations

import contextlib
import json

from mcp.server.fastmcp import Context

from distill.library.state import ChannelState
from distill.mcp import server as _server
from distill.pipeline.costs import CostTracker, save_run_log

__all__: list[str] = []

# Each unit of `limit` triggers transcript downloads and several LLM calls, so a
# prompt-injected agent passing limit=100000 would run up unbounded cloud spend.
# Clamp to a sane ceiling (mirrors site_batch's bounded-cost discipline).
_MAX_LIMIT = 25


def _clamp_limit(limit: int) -> int:
    try:
        return max(1, min(int(limit), _MAX_LIMIT))
    except (TypeError, ValueError):
        return 5


@_server.mcp.tool()
@_server.write_tool("learn_topic")
def learn_topic(
    query: str,
    topic: str | None = None,
    days: int = 60,
    limit: int = 5,
) -> str:
    """Find, process, and synthesize the best YouTube videos for a topic.

    Args:
        query: Topic or question to research
        topic: Topic name to file under
        days: Lookback window in days
        limit: Max videos to process
    """
    from distill.cli_shared import ensure_channel_context, process_video, topic_from_query
    from distill.ingestors.youtube.browser_search import search_youtube_results
    from distill.ingestors.youtube.discovery import enrich_videos
    from distill.ingestors.youtube.discovery import search_videos as yt_search
    from distill.pipeline.ranking import rerank_videos
    from distill.pipeline.summary import ETATracker, RunSummary
    from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

    config = _server._config()
    if not config.xai_api_key:
        return "Error: XAI_API_KEY not configured."

    limit = _clamp_limit(limit)
    topic_name = topic or topic_from_query(query)
    tracker = CostTracker()

    # Search + rank
    candidates = search_youtube_results(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        candidates = yt_search(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        return json.dumps({"error": "No videos found for this query"})

    seen: set[str] = set()
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

    lib = _server._lib(config)
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
            "cost": _server._cost_summary(tracker),
        },
        indent=2,
    )


@_server.mcp.tool()
def search_videos(query: str, days: int = 60, limit: int = 5) -> str:
    """Search YouTube for a topic; return ranked videos without processing.

    Args:
        query: Topic or question to search for
        days: Lookback window in days
        limit: Max results to return
    """
    from distill.ingestors.youtube.browser_search import search_youtube_results
    from distill.ingestors.youtube.discovery import enrich_videos
    from distill.ingestors.youtube.discovery import search_videos as yt_search
    from distill.pipeline.ranking import rerank_videos

    config = _server._config()
    tracker = CostTracker()
    limit = _clamp_limit(limit)

    candidates = search_youtube_results(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        candidates = yt_search(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        return json.dumps({"results": [], "message": "No videos found"})

    # Dedupe
    seen: set[str] = set()
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

    return json.dumps({"results": results, "cost": _server._cost_summary(tracker)}, indent=2)


@_server.mcp.tool()
@_server.write_tool("discover")
async def discover(  # noqa: C901
    goal: str,
    topic: str | None = None,
    limit: int = 5,
    papers_only: bool = False,
    videos_only: bool = False,
    ctx: Context = None,
) -> str:
    """Goal-aware cross-source discovery: papers + videos, ranked.

    Args:
        goal: Research goal or question
        topic: Topic to file under (derived from goal)
        limit: Max sources to process
        papers_only: Only search papers
        videos_only: Only search videos
    """
    from distill.cli_shared import topic_from_query

    config = _server._config()
    if not config.xai_api_key:
        return json.dumps({"status": "error", "error": "XAI_API_KEY not configured."})

    limit = _clamp_limit(limit)
    topic_name = topic or topic_from_query(goal)
    tracker = CostTracker()
    results: dict = {"topic": topic_name, "videos": [], "papers": []}

    # Stage 1: Search videos (unless papers_only)
    if not papers_only:
        if ctx:
            await ctx.report_progress(progress=0, total=3)
        try:
            from distill.ingestors.youtube.browser_search import search_youtube_results
            from distill.ingestors.youtube.discovery import enrich_videos
            from distill.ingestors.youtube.discovery import search_videos as yt_search
            from distill.pipeline.ranking import rerank_videos

            candidates = search_youtube_results(goal, days=60, limit=max(limit * 2, 12))
            if not candidates:
                candidates = yt_search(goal, days=60, limit=max(limit * 2, 12))

            if candidates:
                seen: set[str] = set()
                deduped = [
                    v for v in candidates if v.video_id not in seen and not seen.add(v.video_id)
                ]
                enriched = enrich_videos(deduped, max_videos=min(len(deduped), 12))
                ranked = rerank_videos(
                    goal,
                    enriched,
                    config,
                    tracker=tracker,
                    top_n=max(limit * 2, 10),
                    use_llm=bool(config.xai_api_key),
                )
                for item in ranked[:limit]:
                    v = item.video
                    results["videos"].append(
                        {
                            "title": v.title,
                            "channel": v.channel_name or "unknown",
                            "url": v.url,
                            "score": round(item.final_score, 2),
                        }
                    )
        except Exception as e:
            results["video_error"] = str(e)

    # Stage 2: Search papers (unless videos_only)
    if not videos_only:
        if ctx:
            await ctx.report_progress(progress=1, total=3)
        try:
            from distill.ingestors.papers.arxiv import search_arxiv

            found = search_arxiv(goal, max_results=limit)
            for paper in found[:limit]:
                authors = [
                    getattr(author, "name", author)
                    for author in (paper.authors[:3] if paper.authors else [])
                ]
                results["papers"].append(
                    {
                        "title": paper.title,
                        "authors": authors,
                        "url": getattr(paper, "entry_id", "") or getattr(paper, "abs_url", ""),
                    }
                )
        except Exception as e:
            results["paper_error"] = str(e)

    # Stage 3: Done
    if ctx:
        await ctx.report_progress(progress=3, total=3)

    # Metadata-aware spend estimate for the candidates this run surfaced, so an
    # agent can size an ingest the same way the CLI preview does.
    from distill.pipeline.costs import estimate_discover_items, load_cost_calibration

    estimate = estimate_discover_items(
        papers=len(results["papers"]),
        video_durations=[None] * len(results["videos"]),
        calibration=load_cost_calibration(config.library_dir),
    )
    results["cost_estimate"] = {
        "expected": round(estimate.expected, 4),
        "low": round(estimate.low, 4),
        "high": round(estimate.high, 4),
        "calibrated": estimate.calibrated,
    }

    save_run_log(config.library_dir, "discover", tracker)
    results["status"] = "complete"
    results["cost"] = _server._cost_summary(tracker)
    return json.dumps(results, indent=2)
