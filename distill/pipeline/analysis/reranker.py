# pyright: strict
"""Per-category chunk reranker for multi-pass analysis.

Scores chunks by relevance to each insight category using keyword matching
and selects the top-k that fit within the context window. Fast, local,
and does not require an LLM call.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from distill.pipeline.analysis.chunking import Chunk, estimate_tokens

__all__ = [
    "INSIGHT_CATEGORIES",
    "MINIMUM_RELEVANCE_THRESHOLD",
    "ScoredChunk",
    "rerank_for_category",
]

INSIGHT_CATEGORIES: list[str] = [
    "Key Findings",
    "Methods",
    "Limits",
    "Open Questions",
]

MINIMUM_RELEVANCE_THRESHOLD: float = 0.3

# Category-specific keywords for relevance scoring
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Key Findings": [
        "finding",
        "result",
        "discover",
        "demonstrate",
        "show",
        "reveal",
        "conclude",
        "significant",
        "novel",
        "contribution",
        "evidence",
        "outcome",
        "achieve",
        "improve",
        "outperform",
    ],
    "Methods": [
        "method",
        "approach",
        "algorithm",
        "architecture",
        "implementation",
        "technique",
        "model",
        "framework",
        "pipeline",
        "procedure",
        "design",
        "system",
        "process",
        "strategy",
        "mechanism",
    ],
    "Limits": [
        "limit",
        "limitation",
        "constraint",
        "drawback",
        "weakness",
        "challenge",
        "issue",
        "problem",
        "fail",
        "unable",
        "restrict",
        "bottleneck",
        "trade-off",
        "tradeoff",
        "caveat",
    ],
    "Open Questions": [
        "question",
        "future",
        "unclear",
        "unknown",
        "investigate",
        "explore",
        "remain",
        "open",
        "hypothesis",
        "conjecture",
        "potential",
        "opportunity",
        "direction",
        "gap",
        "unresolved",
    ],
}


@dataclass
class ScoredChunk:
    """A chunk scored for relevance to a specific category."""

    chunk: Chunk
    score: float
    category: str


def _score_chunk_for_category(chunk: Chunk, category: str) -> float:
    """Score a chunk's relevance to a category using keyword matching.

    Score = (keyword_hits / total_keywords) * (1 + log(total_hits))

    Returns 0.0 if no keywords match.
    """
    keywords = CATEGORY_KEYWORDS.get(category, [])
    if not keywords:
        return 0.0

    text_lower = chunk.text.lower()
    total_hits = 0
    keywords_hit = 0

    for keyword in keywords:
        count = text_lower.count(keyword)
        if count > 0:
            keywords_hit += 1
            total_hits += count

    if total_hits == 0:
        return 0.0

    keyword_coverage = keywords_hit / len(keywords)
    score = keyword_coverage * (1 + math.log(total_hits))
    return score


def rerank_for_category(
    chunks: list[Chunk],
    category: str,
    context_window: int,
) -> list[ScoredChunk]:
    """Score and select top-k chunks for a category, fitting within window.

    Scores each chunk's relevance to the category using keyword matching.
    Greedily adds chunks by score until the context window is filled.
    Returns empty list if all chunks score below the minimum threshold.

    Args:
        chunks: List of content chunks to score.
        category: The insight category to score against.
        context_window: Available tokens for selected chunks.

    Returns:
        List of ScoredChunks ordered by score (highest first),
        fitting within the context window. Empty if all below threshold.
    """
    if not chunks:
        return []

    # Score all chunks
    scored = [
        ScoredChunk(
            chunk=chunk, score=_score_chunk_for_category(chunk, category), category=category
        )
        for chunk in chunks
    ]

    # Filter by minimum threshold
    above_threshold = [sc for sc in scored if sc.score >= MINIMUM_RELEVANCE_THRESHOLD]

    if not above_threshold:
        return []

    # Sort by score descending
    above_threshold.sort(key=lambda sc: sc.score, reverse=True)

    # Greedy top-k selection within context window
    selected: list[ScoredChunk] = []
    tokens_used = 0

    for sc in above_threshold:
        chunk_tokens = estimate_tokens(sc.chunk.text)
        if tokens_used + chunk_tokens <= context_window:
            selected.append(sc)
            tokens_used += chunk_tokens

    return selected
