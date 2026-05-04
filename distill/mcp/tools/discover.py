"""MCP tools — discovery: learn_topic, search_videos."""

from __future__ import annotations

import contextlib
import json

from distill.library.state import ChannelState
from distill.mcp import server as _server
from distill.pipeline.costs import CostTracker, save_run_log

__all__: list[str] = []


@_server.mcp.tool()
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
    """Preview the best recent YouTube videos for a topic (no processing).

    Searches YouTube, enriches metadata, and ranks by relevance.
    Returns a ranked list with scores and rationale.

    Args:
        query: Topic or question to search for
        days: Recency window in days
        limit: How many results to return
    """
    from distill.ingestors.youtube.browser_search import search_youtube_results
    from distill.ingestors.youtube.discovery import enrich_videos
    from distill.ingestors.youtube.discovery import search_videos as yt_search
    from distill.pipeline.ranking import rerank_videos

    config = _server._config()
    tracker = CostTracker()

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
