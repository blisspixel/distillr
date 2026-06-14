"""Candidate reranking for topic-first YouTube learning."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.youtube.discovery import VideoInfo
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.discover import paper_rerank_prompt, search_rerank_prompt

__all__ = [
    "RankedPaper",
    "RankedVideo",
    "chronological_rank",
    "rerank_papers",
    "rerank_videos",
]


def _rerank_model_available() -> bool:
    """Is a model configured for the rerank workload (cloud key OR local provider)?

    Asks the router (does ``validate_config`` pass for this workload?), never
    ``config.xai_api_key`` -- an Ollama/LM Studio user has a usable local judge
    and must get it, not the keyword heuristic. When no model is configured at
    all, the caller falls back to the deterministic baseline (an honest,
    non-semantic order). See docs/design/model-judgment-vs-brittle-fallbacks.md
    (P1: "use what they have, never assume a cloud key").
    """
    from distill.llm.availability import model_available

    return model_available("rerank")


def _mark_no_model(ranked: list) -> list:
    """Relabel a deterministic order as the forced no-model fallback (P2).

    Both ``RankedVideo`` and ``RankedPaper`` carry ``selected_by``; setting it to
    ``"no-model"`` distinguishes "deterministic because no model is configured"
    from "deterministic because the user passed --no-rerank" (which stays
    ``"heuristic"``), so a consumer (MCP/JSON) sees the degradation rather than
    mistaking a fallback order for a quality ranking. The graceful-degradation
    mandate: label every degraded response.
    """
    for item in ranked:
        item.selected_by = "no-model"
    return ranked


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
    if not use_llm:
        # User chose the deterministic order (--no-rerank); "heuristic" is honest.
        return baseline[:top_n]
    if not _rerank_model_available():
        # No model configured at all: the deterministic order is a forced
        # fallback, not a choice. Label it "no-model" so a downstream consumer
        # (MCP/JSON) sees a degraded, non-model ranking (the graceful-degradation
        # mandate: label every degraded response). See P2 in
        # docs/design/model-judgment-vs-brittle-fallbacks.md.
        return _mark_no_model(baseline[:top_n])

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
    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="rerank",
        prompt=prompt,
        max_tokens=4096,
        call_type="search_rerank",
        temperature=0.0,  # deterministic rerank so a preview and its re-run agree
    )
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
    from distill.llm.json_extract import extract_json

    data = extract_json(content)
    if data is None:
        return []
    if isinstance(data, dict):
        data = data.get("ranked_videos", [])
    return data if isinstance(data, list) else []


def _heuristic_rank(
    query: str, videos: list[VideoInfo], *, skeptical: bool = False
) -> list[RankedVideo]:
    """Deterministic, no-model ranking -- the honest tier-4 fallback, not a quality judge.

    Composed of keyword/length/metadata heuristics (`_practicality_score`,
    `_topicality_score`, token overlap, duration bands, engagement). Each is a
    brittle proxy for a semantic call ("is this on-topic / practical / credible?")
    and is used ONLY when no model is configured (the LLM rerank in `rerank_videos`
    is the primary signal whenever a model is available, per P1) or as a supplement
    to fill out the model's picks. The right reading is "a transparent best-effort
    order without a model", never "a quality score" -- the model is the judge when
    there is one. See docs/design/model-judgment-vs-brittle-fallbacks.md.
    """
    ranked = []
    for video in videos:
        relevance = _query_overlap(query, video)
        depth = _depth_score(video.duration)
        freshness = _freshness_score(video.upload_date)
        credibility = _credibility_score(video)
        practicality = _practicality_score(query, video)
        topicality = _topicality_score(query, video)
        skepticism_delta, skeptical_notes = _skepticism_adjustment(video, skeptical=skeptical)
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
    # Brittle keyword proxy for "is this practical/how-to vs news?" -- booster and
    # penalty word lists. A tier-4 fallback heuristic only (see _heuristic_rank);
    # the model judges practicality when one is available.
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
    # Brittle token-overlap proxy for "is this on-topic?" with an ignore-list. A
    # tier-4 fallback heuristic only (see _heuristic_rank); the model judges
    # topicality when one is available.
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


def _skepticism_adjustment(video: VideoInfo, *, skeptical: bool = False) -> tuple[float, list[str]]:
    # Only runs when the caller explicitly turned on skeptical mode (the user's
    # --skeptical, or the structural April-1 date guard). It used to also fire
    # when a keyword list decided the *query* "looks like a rumor" -- a brittle
    # proxy that mislabeled neutral queries (e.g. "analysis") as rumor-sensitive
    # and leaked that verdict into the primary rerank prompt. Removed (P3): whether
    # a source is an unverified leak is the model's read, not a keyword list's.
    if not skeptical:
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
    if not use_llm:
        return baseline[:top_n]  # user chose deterministic (--no-rerank)
    if not _rerank_model_available():
        return _mark_no_model(baseline[:top_n])  # forced fallback; label it (P2)

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
    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="rerank",
        prompt=prompt,
        max_tokens=4096,
        call_type="paper_rerank",
        temperature=0.0,  # deterministic rerank so a preview and its re-run agree
    )
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
    from distill.llm.json_extract import extract_json

    data = extract_json(content)
    if data is None:
        return []
    if isinstance(data, dict):
        data = data.get("ranked_papers", [])
    return data if isinstance(data, list) else []


def _heuristic_rank_papers(query: str, papers: list[PaperRecord]) -> list[RankedPaper]:
    """Deterministic, no-model paper ranking -- the honest tier-4 fallback.

    Like `_heuristic_rank` for videos: token overlap + abstract length/substance
    keywords + recency + author/category metadata. Brittle proxies used only when
    no model is configured (the LLM rerank is primary whenever one is); a
    transparent best-effort order, not a quality judgment.
    """
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
    # Brittle proxy for "is this paper substantive?" by abstract length + a
    # substance-phrase keyword list. Tier-4 fallback heuristic only (see
    # _heuristic_rank_papers); the model judges depth when one is available.
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
