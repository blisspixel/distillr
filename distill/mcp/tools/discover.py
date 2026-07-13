# pyright: strict
"""MCP tools -- discovery: learn_topic, search_videos, discover."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any

from mcp.server.fastmcp import Context

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.youtube.discovery import VideoInfo, is_valid_youtube_lookback
from distill.library import Library
from distill.library.state import ChannelState
from distill.llm.availability import model_available
from distill.llm.router import RouterConfig
from distill.mcp.server import capped_tracker, cost_summary, library, load_config, mcp, write_tool
from distill.pipeline.costs import BudgetExceededError, CostTracker, save_run_log
from distill.pipeline.ranking import RankedVideo
from distill.pipeline.summary import RunSummary

logger = logging.getLogger(__name__)

__all__: list[str] = []

# Each unit of `limit` triggers transcript downloads and several LLM calls, so a
# prompt-injected agent passing limit=100000 would run up unbounded cloud spend.
# Clamp to a sane ceiling (mirrors site_batch's bounded-cost discipline).
_MAX_LIMIT = 25

type JsonObject = dict[str, object]
type LearnVideoRow = dict[str, str]
type SearchVideoRow = dict[str, str | int | float]


def _clamp_limit(limit: object) -> int:
    try:
        parsed = int(limit) if isinstance(limit, str) else limit
    except (TypeError, ValueError):
        return 5
    if not isinstance(parsed, int) or isinstance(parsed, bool):
        return 5
    return max(1, min(parsed, _MAX_LIMIT))


def _dedupe_videos(videos: Sequence[VideoInfo]) -> list[VideoInfo]:
    seen: set[str] = set()
    deduped: list[VideoInfo] = []
    for video in videos:
        if video.video_id in seen:
            continue
        seen.add(video.video_id)
        deduped.append(video)
    return deduped


def _search_candidates(query: str, *, days: int, limit: int) -> list[VideoInfo]:
    from distill.ingestors.youtube.browser_search import search_youtube_results
    from distill.ingestors.youtube.discovery import search_videos as yt_search

    if not is_valid_youtube_lookback(days):
        return []
    candidates = search_youtube_results(query, days=days, limit=limit)
    if not candidates:
        candidates = yt_search(query, days=days, limit=limit)
    return candidates


def _rank_candidates(
    query: str,
    candidates: Sequence[VideoInfo],
    config: DistillConfig,
    tracker: CostTracker,
    *,
    limit: int,
) -> list[RankedVideo]:
    from distill.ingestors.youtube.discovery import enrich_videos
    from distill.pipeline.ranking import rerank_videos

    deduped = _dedupe_videos(candidates)
    enriched = enrich_videos(deduped, max_videos=min(len(deduped), 12))
    return rerank_videos(
        query,
        enriched,
        config,
        tracker=tracker,
        top_n=max(limit * 2, 10),
        use_llm=True,  # rerank_videos checks model availability itself and labels a no-model fallback
    )


def _search_video_row(item: RankedVideo) -> SearchVideoRow:
    video = item.video
    return {
        "title": video.title,
        "channel": video.channel_name or "unknown",
        "date": video.upload_date,
        "url": video.url,
        "duration": video.duration,
        "view_count": video.view_count,
        "score": round(item.final_score, 2),
        "rationale": item.rationale,
        # How this set was ordered, so an agent consumer can see a degraded
        # ranking: "llm" (model-judged), "heuristic" (deterministic), or
        # "no-model" (forced fallback, no model configured). The graceful-
        # degradation mandate: label it.
        "ranked_by": item.selected_by,
    }


def _paper_authors(paper: PaperRecord) -> list[str]:
    return [str(author) for author in paper.authors[:3]]


def _learn_one_channel(
    topic_name: str,
    channel_name: str,
    videos: Sequence[VideoInfo],
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    *,
    lib: Library,
    ensure_channel_context: Callable[..., None],
    process_video: Callable[..., bool],
    synthesize_channel: Callable[..., str],
) -> list[LearnVideoRow]:
    """Process one channel's selected videos into result rows; budget aborts re-raise."""
    from distill.pipeline.summary import ETATracker

    channel_url = next((v.channel_url for v in videos if v.channel_url), "")
    if channel_url:
        lib.add_channel(topic_name, channel_url, channel_name)

    state = ChannelState(config.channel_dir(topic_name, channel_name) / "state.json")
    ensure_channel_context(topic_name, channel_name, videos, config, tracker)
    eta = ETATracker(total=len(videos))

    rows: list[LearnVideoRow] = []
    for vid in videos:
        if state.is_processed(vid.video_id):
            rows.append({"title": vid.title, "status": "already_done"})
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
        rows.append({"title": vid.title, "status": "ok" if success else "failed"})

    try:
        synthesize_channel(topic_name, channel_name, config, tracker=tracker)
    except BudgetExceededError:
        raise  # the per-call spend cap is a hard stop; write_tool answers
    except Exception as exc:
        logger.warning("discover channel synthesis failed for %s: %s", channel_name, exc)
    return rows


@mcp.tool()
@write_tool("learn_topic")
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
    from distill.pipeline.summary import RunSummary
    from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

    config = load_config()
    if not model_available():
        return "Error: No model configured (set a cloud key or DISTILL_PROVIDER)."

    limit = _clamp_limit(limit)
    topic_name = topic or topic_from_query(query)
    tracker = capped_tracker()

    # Search + rank
    candidates = _search_candidates(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        return json.dumps({"error": "No videos found for this query"})

    ranked = _rank_candidates(query, candidates, config, tracker, limit=limit)
    selected = ranked[:limit]

    # Group by channel
    grouped: dict[str, list[VideoInfo]] = {}
    for item in selected:
        ch = (item.video.channel_name or "unknown").strip() or "unknown"
        grouped.setdefault(ch, []).append(item.video)

    lib = library(config)
    summary = RunSummary(command="learn")
    processed_videos: list[LearnVideoRow] = []

    for channel_name, videos in grouped.items():
        processed_videos += _learn_one_channel(
            topic_name,
            channel_name,
            videos,
            config,
            tracker,
            summary,
            lib=lib,
            ensure_channel_context=ensure_channel_context,
            process_video=process_video,
            synthesize_channel=synthesize_channel,
        )

    try:
        synthesize_topic(topic_name, config, tracker=tracker)
    except BudgetExceededError:
        raise
    except Exception as exc:
        logger.warning("learn_topic synthesis failed for %s: %s", topic_name, exc)

    save_run_log(config.library_dir, summary.command, tracker)
    return json.dumps(
        {
            "topic": topic_name,
            "videos": processed_videos,
            "cost": cost_summary(tracker),
        },
        indent=2,
    )


@mcp.tool()
@write_tool("search_videos")
def search_videos(query: str, days: int = 60, limit: int = 5) -> str:
    """Search YouTube for a topic; return ranked videos without processing.

    Args:
        query: Topic or question to search for
        days: Lookback window in days
        limit: Max results to return
    """
    config = load_config()
    tracker = capped_tracker()
    limit = _clamp_limit(limit)

    candidates = _search_candidates(query, days=days, limit=max(limit * 2, 12))
    if not candidates:
        return json.dumps({"results": [], "message": "No videos found"})

    ranked = _rank_candidates(query, candidates, config, tracker, limit=limit)

    results = [_search_video_row(item) for item in ranked[:limit]]

    ranked_by = ranked[0].selected_by if ranked else "none"
    payload: JsonObject = {
        "results": results,
        "ranked_by": ranked_by,
        "cost": cost_summary(tracker),
    }
    if ranked_by == "no-model":
        payload["notice"] = (
            "No model configured -- results are a deterministic fallback order, not model-ranked. "
            "Set a cloud key or DISTILL_PROVIDER=ollama for model reranking."
        )
    return json.dumps(payload, indent=2)


@mcp.tool()
@write_tool("discover")
async def discover(  # noqa: C901 - legacy discovery workflow
    goal: str,
    topic: str | None = None,
    limit: int = 5,
    papers_only: bool = False,
    videos_only: bool = False,
    ctx: Context[Any, Any, Any] | None = None,
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

    config = load_config()
    if not model_available():
        return json.dumps(
            {
                "status": "error",
                "error": "No model configured (set a cloud key or DISTILL_PROVIDER).",
            }
        )

    limit = _clamp_limit(limit)
    topic_name = topic or topic_from_query(goal)
    tracker = capped_tracker()
    video_results: list[JsonObject] = []
    paper_results: list[JsonObject] = []
    errors: JsonObject = {}

    # Stage 1: Search videos (unless papers_only)
    if not papers_only:
        if ctx:
            await ctx.report_progress(progress=0, total=3)
        try:
            candidates = _search_candidates(goal, days=60, limit=max(limit * 2, 12))

            if candidates:
                ranked = _rank_candidates(goal, candidates, config, tracker, limit=limit)
                for item in ranked[:limit]:
                    v = item.video
                    video_results.append(
                        {
                            "title": v.title,
                            "channel": v.channel_name or "unknown",
                            "url": v.url,
                            "score": round(item.final_score, 2),
                        }
                    )
        except BudgetExceededError:
            raise  # the per-call spend cap is a hard stop; write_tool answers
        except Exception as e:
            errors["video_error"] = str(e)

    # Stage 2: Search papers (unless videos_only)
    if not videos_only:
        if ctx:
            await ctx.report_progress(progress=1, total=3)
        try:
            from distill.ingestors.papers.arxiv import search_arxiv

            found = search_arxiv(goal, max_results=limit)
            for paper in found[:limit]:
                paper_results.append(
                    {
                        "title": paper.title,
                        "authors": _paper_authors(paper),
                        "url": getattr(paper, "entry_id", "") or getattr(paper, "abs_url", ""),
                    }
                )
        except BudgetExceededError:
            raise
        except Exception as e:
            errors["paper_error"] = str(e)

    # Stage 3: Done
    if ctx:
        await ctx.report_progress(progress=3, total=3)

    # Metadata-aware spend estimate for the candidates this run surfaced, so an
    # agent can size an ingest the same way the CLI preview does.
    from distill.pipeline.costs import estimate_discover_items, load_cost_calibration

    estimate = estimate_discover_items(
        papers=len(paper_results),
        video_durations=[None] * len(video_results),
        calibration=load_cost_calibration(config.library_dir),
        router_config=RouterConfig(),
    )
    payload: JsonObject = {
        "topic": topic_name,
        "videos": video_results,
        "papers": paper_results,
        **errors,
        "cost_estimate": {
            "expected": round(estimate.expected, 4),
            "low": round(estimate.low, 4),
            "high": round(estimate.high, 4),
            "calibrated": estimate.calibrated,
        },
        "status": "complete",
        "cost": cost_summary(tracker),
    }

    save_run_log(
        config.library_dir,
        "discover",
        tracker,
        estimated_cost=estimate.expected,
    )
    return json.dumps(payload, indent=2)
