"""Discover command helpers for the Distill CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from rich import box
from rich.table import Table

from distill.analysis import XAI_BASE_URL
from distill.cli_shared import SHORTS_THRESHOLD, console
from distill.cli_shared import format_date as _format_date
from distill.config import DistillConfig
from distill.costs import CostTracker, TokenUsage
from distill.discovery import VideoInfo
from distill.paper_ingest import PaperRecord
from distill.prompts import discover_query_generation_prompt, discover_rerank_prompt


@dataclass
class RankedDiscoverItem:
    kind: str
    identifier: str
    title: str
    subtitle: str
    date: str
    final_score: float
    goal_fit: float
    depth_score: float
    complementarity_score: float
    rationale: str
    paper: PaperRecord | None = None
    video: VideoInfo | None = None


def discover_generate_queries(
    goal: str,
    config: DistillConfig,
    tracker: CostTracker | None,
    *,
    paper_count: int,
    video_count: int,
    dedupe_query_strings,
) -> tuple[list[str], list[str]]:
    client = OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)
    model = config.xai_model_for("rerank")
    prompt = discover_query_generation_prompt(
        goal, paper_count=paper_count, video_count=video_count
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=768,
        timeout=120,
    )
    if tracker and response.usage:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                model=model,
                call_type="discover_plan",
            )
        )
    content = response.choices[0].message.content if response.choices else ""
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        return [], []
    data = json.loads(text)
    paper_qs = data.get("paper_queries", []) if isinstance(data, dict) else []
    video_qs = data.get("video_queries", []) if isinstance(data, dict) else []
    paper_qs = dedupe_query_strings([q for q in paper_qs if isinstance(q, str)])
    video_qs = dedupe_query_strings([q for q in video_qs if isinstance(q, str)])
    return paper_qs, video_qs


def discover_fetch_videos(
    queries: list[str],
    effective_days: int,
    candidate_cap: int,
    shorts: bool,
    *,
    search_youtube_results,
    dedupe_candidates,
    enrich_videos,
    filter_recent_candidates,
) -> list[VideoInfo]:
    raw: list[VideoInfo] = []
    for idx, q in enumerate(queries, 1):
        console.print(f"[dim]Video search {idx}/{len(queries)}: {q}[/dim]")
        raw.extend(search_youtube_results(q, days=effective_days, hours=None, limit=candidate_cap))
    raw = dedupe_candidates(raw)
    if not raw:
        return []
    if not shorts:
        raw = [v for v in raw if v.duration > SHORTS_THRESHOLD]
    if not raw:
        return []
    enriched = enrich_videos(raw, max_videos=min(len(raw), 20))
    return filter_recent_candidates(enriched, effective_days, hours=None)


def discover_rerank(
    goal: str,
    papers: list[PaperRecord],
    videos: list[VideoInfo],
    config: DistillConfig,
    tracker: CostTracker | None,
) -> list[RankedDiscoverItem]:
    candidates: list[dict[str, Any]] = []
    paper_by_id = {p.paper_id: p for p in papers}
    video_by_id = {v.video_id: v for v in videos}
    for p in papers:
        candidates.append(
            {
                "kind": "paper",
                "identifier": p.paper_id,
                "title": p.title,
                "subtitle": ", ".join((p.authors or [])[:3]) or "unknown",
                "date": (p.published_at or "")[:10],
                "description": p.abstract or "",
            }
        )
    for v in videos:
        candidates.append(
            {
                "kind": "video",
                "identifier": v.video_id,
                "title": v.title,
                "subtitle": v.channel_name or "unknown",
                "date": v.upload_date or "",
                "description": getattr(v, "description", "") or "",
            }
        )
    if not candidates:
        return []

    client = OpenAI(api_key=config.xai_api_key, base_url=XAI_BASE_URL)
    model = config.xai_model_for("rerank")
    prompt = discover_rerank_prompt(goal, candidates)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=8192,
        timeout=240,
    )
    if tracker and response.usage:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                model=model,
                call_type="discover_rerank",
            )
        )
    content = response.choices[0].message.content if response.choices else ""
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text:
        return []
    data = json.loads(text)
    items = data.get("ranked_items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    ranked: list[RankedDiscoverItem] = []
    for entry in items:
        kind = str(entry.get("kind", "")).strip()
        identifier = str(entry.get("identifier", "")).strip()
        if kind == "paper":
            paper = paper_by_id.get(identifier)
            if not paper:
                continue
            ranked.append(
                RankedDiscoverItem(
                    kind="paper",
                    identifier=identifier,
                    title=paper.title,
                    subtitle=", ".join((paper.authors or [])[:2]) or "unknown",
                    date=(paper.published_at or "")[:10],
                    final_score=float(entry.get("final_score", 0.0)),
                    goal_fit=float(entry.get("goal_fit", 0.0)),
                    depth_score=float(entry.get("depth_score", 0.0)),
                    complementarity_score=float(entry.get("complementarity_score", 0.0)),
                    rationale=str(entry.get("rationale", "")).strip(),
                    paper=paper,
                )
            )
        elif kind == "video":
            video = video_by_id.get(identifier)
            if not video:
                continue
            ranked.append(
                RankedDiscoverItem(
                    kind="video",
                    identifier=identifier,
                    title=video.title,
                    subtitle=video.channel_name or "unknown",
                    date=_format_date(video.upload_date or ""),
                    final_score=float(entry.get("final_score", 0.0)),
                    goal_fit=float(entry.get("goal_fit", 0.0)),
                    depth_score=float(entry.get("depth_score", 0.0)),
                    complementarity_score=float(entry.get("complementarity_score", 0.0)),
                    rationale=str(entry.get("rationale", "")).strip(),
                    video=video,
                )
            )
    return sorted(ranked, key=lambda x: x.final_score, reverse=True)


def display_ranked_discover(items: list[RankedDiscoverItem], title: str) -> None:
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("#", justify="right")
    table.add_column("Type")
    table.add_column("Title", overflow="fold")
    table.add_column("Source", overflow="fold")
    table.add_column("Date")
    table.add_column("Score", justify="right")
    table.add_column("Why", overflow="fold")
    for idx, item in enumerate(items, 1):
        table.add_row(
            str(idx),
            item.kind,
            item.title,
            item.subtitle,
            item.date or "-",
            f"{item.final_score:.2f}",
            item.rationale or "-",
        )
    console.print(table)
