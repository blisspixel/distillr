"""Candidate reranking for topic-first YouTube learning."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime

from rich.console import Console

from distill.config import DistillConfig, router_config_from_distill
from distill.costs import CostTracker, TokenUsage
from distill.discovery import VideoInfo
from distill.llm import call as llm_call
from distill.paper_ingest import PaperRecord
from distill.prompts import paper_rerank_prompt, search_rerank_prompt

console = Console()


@dataclass
class RankedVideo:
    video: VideoInfo
    final_score: float
    relevance_score: float
    depth_score: float
    practicality_score: float
    freshness_score: float
    credibility_score: float
    rationale: str
    selected_by: str = "heuristic"


def rerank_videos(
    query: str,
    videos: list[VideoInfo],
    config: DistillConfig,
    tracker: CostTracker | None = None,
    top_n: int = 5,
    use_llm: bool = True,
    skeptical: bool = False,
) -> list[RankedVideo]:
    if not videos:
        return []

    baseline = _heuristic_rank(query, videos, skeptical=skeptical)
    if not use_llm or not config.xai_api_key:
        return baseline[:top_n]

    try:
        llm_ranked = _llm_rerank(query, videos, config, tracker, skeptical=skeptical)
    except Exception as e:
        console.print(f"  [yellow]Rerank fallback: {e}[/yellow]")
        return baseline[:top_n]

    if not llm_ranked:
        return baseline[:top_n]

    seen = {item.video.video_id for item in llm_ranked}
    supplemented = list(llm_ranked)
    for item in baseline:
        if item.video.video_id in seen:
            continue
        supplemented.append(item)
        seen.add(item.video.video_id)
        if len(supplemented) >= top_n:
            break
    return supplemented[:top_n]


def _llm_rerank(
    query: str,
    videos: list[VideoInfo],
    config: DistillConfig,
    tracker: CostTracker | None = None,
    skeptical: bool = False,
) -> list[RankedVideo]:
    prompt = search_rerank_prompt(query, videos, skeptical=skeptical)
    rc = router_config_from_distill(config)
    response = llm_call(rc, workload_tag="rerank", prompt=prompt, max_tokens=4096, call_type="search_rerank")
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="search_rerank",
            )
        )

    content = response.text
    parsed = _parse_rerank_response(content)
    if not parsed:
        return []

    by_id = {video.video_id: video for video in videos}
    ranked = []
    for item in parsed:
        video = by_id.get(item.get("video_id", ""))
        if not video:
            continue
        ranked.append(
            RankedVideo(
                video=video,
                final_score=float(item.get("final_score", 0.0)),
                relevance_score=float(item.get("relevance_score", 0.0)),
                depth_score=float(item.get("depth_score", 0.0)),
                practicality_score=float(item.get("practicality_score", 0.0)),
                freshness_score=float(item.get("freshness_score", 0.0)),
                credibility_score=float(item.get("credibility_score", 0.0)),
                rationale=str(item.get("rationale", "")).strip()
                or "Best-fit candidate for the query.",
                selected_by="llm",
            )
        )

    return sorted(ranked, key=lambda item: item.final_score, reverse=True)


def _parse_rerank_response(content: str) -> list[dict]:
    if not content:
        return []
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("ranked_videos", [])
    return data if isinstance(data, list) else []


def _heuristic_rank(
    query: str, videos: list[VideoInfo], *, skeptical: bool = False
) -> list[RankedVideo]:
    ranked = []
    for video in videos:
        relevance = _query_overlap(query, video)
        depth = _depth_score(video.duration)
        freshness = _freshness_score(video.upload_date)
        credibility = _credibility_score(video)
        practicality = _practicality_score(query, video)
        topicality = _topicality_score(query, video)
        skepticism_delta, skeptical_notes = _skepticism_adjustment(
            query, video, skeptical=skeptical
        )
        base_score = (
            relevance * 0.28
            + depth * 0.18
            + practicality * 0.18
            + freshness * 0.14
            + credibility * 0.08
            + topicality * 0.14
        )
        final_score = round(max(0.0, min(1.0, base_score + skepticism_delta)), 3)
        ranked.append(
            RankedVideo(
                video=video,
                final_score=final_score,
                relevance_score=relevance,
                depth_score=depth,
                practicality_score=practicality,
                freshness_score=freshness,
                credibility_score=credibility,
                rationale=_heuristic_reason(
                    video,
                    relevance,
                    depth,
                    freshness,
                    topicality,
                    skeptical_notes=skeptical_notes,
                ),
                selected_by="heuristic",
            )
        )
    return sorted(ranked, key=lambda item: item.final_score, reverse=True)


def _query_overlap(query: str, video: VideoInfo) -> float:
    query_terms = {t for t in _tokenize(query) if len(t) > 2}
    if not query_terms:
        return 0.5
    haystack = set(_tokenize(f"{video.title} {video.description} {video.channel_name}"))
    matches = sum(1 for term in query_terms if term in haystack)
    return round(min(1.0, matches / max(3, len(query_terms))), 3)


def _depth_score(duration_seconds: int) -> float:
    if duration_seconds <= 0:
        return 0.0
    minutes = duration_seconds / 60
    if minutes < 4:
        return 0.15
    if minutes < 8:
        return 0.45
    if minutes <= 35:
        return 0.95
    if minutes <= 60:
        return 0.75
    return 0.55


def _freshness_score(upload_date: str) -> float:
    try:
        age_days = (datetime.now() - datetime.strptime(upload_date, "%Y%m%d")).days
    except ValueError:
        return 0.0
    if age_days <= 7:
        return 1.0
    if age_days <= 21:
        return 0.85
    if age_days <= 45:
        return 0.7
    if age_days <= 60:
        return 0.55
    return 0.25


def chronological_rank(videos: list[VideoInfo], top_n: int) -> list[RankedVideo]:
    """Return the ``top_n`` most recent videos by upload date, no quality scoring.

    Use when the user wants strict "last N uploads" semantics and explicitly
    does not want the LLM rerank or the heuristic mix of relevance/depth/etc.
    Videos with unparseable upload dates land at the bottom of the order.
    """

    def _sort_key(video: VideoInfo):
        try:
            return datetime.strptime(video.upload_date or "", "%Y%m%d")
        except ValueError:
            return datetime(1, 1, 1)

    sorted_by_date = sorted(videos, key=_sort_key, reverse=True)
    ranked = []
    for video in sorted_by_date[:top_n]:
        freshness = _freshness_score(video.upload_date or "")
        ranked.append(
            RankedVideo(
                video=video,
                final_score=freshness,
                relevance_score=0.0,
                depth_score=0.0,
                practicality_score=0.0,
                freshness_score=freshness,
                credibility_score=0.0,
                rationale="selected by upload date",
                selected_by="chronological",
            )
        )
    return ranked


def _credibility_score(video: VideoInfo) -> float:
    views = math.log10(max(1, video.view_count)) / 6 if video.view_count else 0.2
    engagement = (
        math.log10(max(1, video.like_count + video.comment_count + 1)) / 5
        if (video.like_count or video.comment_count)
        else 0.2
    )
    return round(min(1.0, (views * 0.7) + (engagement * 0.3)), 3)


def _practicality_score(query: str, video: VideoInfo) -> float:
    text = f"{video.title} {video.description}".lower()
    boosters = [
        "best practice",
        "best practices",
        "architecture",
        "iac",
        "terraform",
        "bicep",
        "deployment",
        "walkthrough",
        "guide",
        "pattern",
        "governance",
        "implementation",
        "how to",
        "tutorial",
    ]
    penalties = ["news", "announcement", "announced", "weekly", "recap", "roundup"]
    score = sum(0.1 for term in boosters if term in text)
    score -= sum(0.08 for term in penalties if term in text)
    if any(word in query.lower() for word in ["best practice", "architecture", "iac"]):
        score += 0.18
    return round(min(1.0, max(0.05, score)), 3)


def _topicality_score(query: str, video: VideoInfo) -> float:
    ignored = {
        "best",
        "practice",
        "practices",
        "guide",
        "tutorial",
        "walkthrough",
        "implementation",
        "architecture",
        "how",
        "to",
    }
    query_terms = [t for t in _tokenize(query) if len(t) > 2 and t not in ignored]
    video_terms = set(_tokenize(f"{video.title} {video.description} {video.channel_name}"))
    if not query_terms:
        return 0.7

    matched = sum(1 for term in query_terms if term in video_terms)
    score = matched / len(query_terms)

    anchors = [term for term in query_terms if len(term) >= 5]
    if anchors:
        anchor_matches = sum(1 for term in anchors if term in video_terms)
        anchor_ratio = anchor_matches / len(anchors)
        score = (score * 0.6) + (anchor_ratio * 0.4)
        if anchor_ratio == 0:
            score -= 0.35
        elif anchor_ratio < 0.5:
            score -= 0.15

    return round(max(0.0, min(1.0, score)), 3)


def _heuristic_reason(
    video: VideoInfo,
    relevance: float,
    depth: float,
    freshness: float,
    topicality: float,
    *,
    skeptical_notes: list[str] | None = None,
) -> str:
    parts = []
    if topicality >= 0.7:
        parts.append("strong topic fit")
    if relevance >= 0.6:
        parts.append("strong title/description match")
    if depth >= 0.75:
        parts.append("substantive runtime")
    if freshness >= 0.7:
        parts.append("recent")
    if skeptical_notes:
        parts.extend(skeptical_notes[:2])
    return ", ".join(parts) or "best deterministic match"


def _tokenize(text: str) -> list[str]:
    cleaned = []
    current = []
    for char in text.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            cleaned.append("".join(current))
            current = []
    if current:
        cleaned.append("".join(current))
    return cleaned


def _skepticism_adjustment(
    query: str, video: VideoInfo, *, skeptical: bool = False
) -> tuple[float, list[str]]:
    if not skeptical and not _looks_like_rumor_query(query):
        return 0.0, []

    text = f"{video.title} {video.description}".lower()
    notes: list[str] = []
    delta = 0.0

    evidence_terms = [
        "source code",
        "sourcemap",
        "repo",
        "repository",
        "artifact",
        "feature flag",
        "feature flags",
        "daemon",
        "log",
        "logs",
        "bundle",
        "decompile",
        "analysis",
        "validated",
        "validation",
        "debunk",
        "rebuttal",
        "what leaked",
    ]
    prank_terms = [
        "april fool",
        "april fools",
        "prank",
        "satire",
        "parody",
        "lol",
        "lmao",
        "crazy",
        "insane",
        "worst nightmare",
        "it's over",
        "its over",
        "cooked",
    ]

    evidence_hits = sum(1 for term in evidence_terms if term in text)
    prank_hits = sum(1 for term in prank_terms if term in text)
    if evidence_hits:
        delta += min(0.18, evidence_hits * 0.04)
        notes.append("concrete evidence terms")
    if prank_hits:
        delta -= min(0.24, prank_hits * 0.08)
        notes.append("prank-style framing penalty")

    today = datetime.now()
    if today.month == 4 and today.day == 1 and video.upload_date == today.strftime("%Y%m%d"):
        delta -= 0.05
        notes.append("April 1 caution")

    return delta, notes


def _looks_like_rumor_query(query: str) -> bool:
    lowered = query.lower()
    rumor_terms = {
        "leak",
        "leaked",
        "rumor",
        "rumour",
        "source code",
        "hack",
        "breach",
        "exposed",
        "incident",
        "analysis",
    }
    return any(term in lowered for term in rumor_terms)


@dataclass
class RankedPaper:
    paper: PaperRecord
    final_score: float
    relevance_score: float
    depth_score: float
    novelty_score: float
    credibility_score: float
    rationale: str
    selected_by: str = "heuristic"


def rerank_papers(
    query: str,
    papers: list[PaperRecord],
    config: DistillConfig,
    tracker: CostTracker | None = None,
    top_n: int = 10,
    use_llm: bool = True,
) -> list[RankedPaper]:
    if not papers:
        return []

    baseline = _heuristic_rank_papers(query, papers)
    if not use_llm or not config.xai_api_key:
        return baseline[:top_n]

    try:
        llm_ranked = _llm_rerank_papers(query, papers, config, tracker)
    except Exception as e:
        console.print(f"  [yellow]Paper rerank fallback: {e}[/yellow]")
        return baseline[:top_n]

    if not llm_ranked:
        return baseline[:top_n]

    seen = {item.paper.paper_id for item in llm_ranked}
    supplemented = list(llm_ranked)
    for item in baseline:
        if item.paper.paper_id in seen:
            continue
        supplemented.append(item)
        seen.add(item.paper.paper_id)
        if len(supplemented) >= top_n:
            break
    return supplemented[:top_n]


def _llm_rerank_papers(
    query: str,
    papers: list[PaperRecord],
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> list[RankedPaper]:
    prompt = paper_rerank_prompt(query, papers)
    rc = router_config_from_distill(config)
    response = llm_call(rc, workload_tag="rerank", prompt=prompt, max_tokens=4096, call_type="paper_rerank")
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="paper_rerank",
            )
        )

    content = response.text
    parsed = _parse_paper_rerank_response(content or "")
    if not parsed:
        return []

    by_id = {paper.paper_id: paper for paper in papers}
    ranked: list[RankedPaper] = []
    for item in parsed:
        paper = by_id.get(item.get("paper_id", ""))
        if not paper:
            continue
        ranked.append(
            RankedPaper(
                paper=paper,
                final_score=float(item.get("final_score", 0.0)),
                relevance_score=float(item.get("relevance_score", 0.0)),
                depth_score=float(item.get("depth_score", 0.0)),
                novelty_score=float(item.get("novelty_score", 0.0)),
                credibility_score=float(item.get("credibility_score", 0.0)),
                rationale=str(item.get("rationale", "")).strip()
                or "Best-fit candidate for the query.",
                selected_by="llm",
            )
        )
    return sorted(ranked, key=lambda item: item.final_score, reverse=True)


def _parse_paper_rerank_response(content: str) -> list[dict]:
    if not content:
        return []
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("ranked_papers", [])
    return data if isinstance(data, list) else []


def _heuristic_rank_papers(query: str, papers: list[PaperRecord]) -> list[RankedPaper]:
    ranked: list[RankedPaper] = []
    for paper in papers:
        relevance = _paper_query_overlap(query, paper)
        depth = _paper_depth_score(paper)
        novelty = _paper_novelty_score(paper)
        credibility = _paper_credibility_score(paper)
        base_score = relevance * 0.45 + depth * 0.20 + novelty * 0.15 + credibility * 0.20
        final_score = round(max(0.0, min(1.0, base_score)), 3)
        ranked.append(
            RankedPaper(
                paper=paper,
                final_score=final_score,
                relevance_score=relevance,
                depth_score=depth,
                novelty_score=novelty,
                credibility_score=credibility,
                rationale=_paper_heuristic_reason(relevance, depth, novelty, credibility),
                selected_by="heuristic",
            )
        )
    return sorted(ranked, key=lambda item: item.final_score, reverse=True)


def _paper_query_overlap(query: str, paper: PaperRecord) -> float:
    query_terms = {t for t in _tokenize(query) if len(t) > 2}
    if not query_terms:
        return 0.5
    haystack = set(_tokenize(f"{paper.title} {paper.abstract}"))
    matches = sum(1 for term in query_terms if term in haystack)
    return round(min(1.0, matches / max(3, len(query_terms))), 3)


def _paper_depth_score(paper: PaperRecord) -> float:
    abstract = (paper.abstract or "").lower()
    if not abstract:
        return 0.2
    length = len(abstract)
    base = 0.3
    if length >= 400:
        base = 0.55
    if length >= 900:
        base = 0.75
    substance_terms = [
        "we propose",
        "we present",
        "we introduce",
        "experiments",
        "ablation",
        "benchmark",
        "dataset",
        "evaluation",
        "empirical",
        "outperform",
        "achieve",
        "state-of-the-art",
        "sota",
    ]
    hits = sum(1 for term in substance_terms if term in abstract)
    boost = min(0.25, hits * 0.05)
    return round(min(1.0, base + boost), 3)


def _paper_novelty_score(paper: PaperRecord) -> float:
    published = (paper.published_at or "").strip()
    if not published:
        return 0.4
    try:
        # arXiv timestamps look like "2025-03-12T04:17:00Z"
        date = datetime.strptime(published[:10], "%Y-%m-%d")
    except ValueError:
        return 0.4
    age_days = (datetime.now() - date).days
    if age_days <= 180:
        return 1.0
    if age_days <= 365:
        return 0.85
    if age_days <= 730:
        return 0.65
    if age_days <= 1825:
        return 0.45
    return 0.25


def _paper_credibility_score(paper: PaperRecord) -> float:
    score = 0.4
    author_count = len(paper.authors or [])
    if author_count >= 2:
        score += 0.15
    if author_count >= 4:
        score += 0.1
    categories = [c.lower() for c in (paper.categories or [])]
    if any(c.startswith(("cs.", "stat.", "eess.")) for c in categories):
        score += 0.15
    abstract_len = len(paper.abstract or "")
    if abstract_len >= 600:
        score += 0.1
    return round(min(1.0, score), 3)


def _paper_heuristic_reason(
    relevance: float, depth: float, novelty: float, credibility: float
) -> str:
    parts = []
    if relevance >= 0.7:
        parts.append("strong title/abstract match")
    if depth >= 0.7:
        parts.append("substantive abstract")
    if novelty >= 0.85:
        parts.append("recent")
    if credibility >= 0.7:
        parts.append("credibility signals")
    return ", ".join(parts) or "best deterministic match"
