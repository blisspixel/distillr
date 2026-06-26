"""Discovery and ranking prompt templates -- search expansion, reranking."""

# pyright: strict

__all__ = [
    "discover_query_generation_prompt",
    "discover_rerank_prompt",
    "paper_query_expansion_prompt",
    "paper_rerank_prompt",
    "search_query_expansion_prompt",
    "search_rerank_prompt",
]

from collections.abc import Sequence
from typing import Any

from distill.prompts.shared import DERIVED_CONTENT_RULES


def search_query_expansion_prompt(query: str, *, skeptical: bool = False) -> str:
    """Prompt for generating a small set of YouTube search intents for a topic."""
    skepticism_guidance = ""
    if skeptical:
        skepticism_guidance = """
This topic may be rumor-heavy, prank-prone, or noisy. Include search intents that help distinguish raw claims from evidence, validation, rebuttals, and post-mortems. Prefer concrete artifact terms when relevant.
"""

    return f"""You are designing YouTube search intents for a rapid intelligence workflow.

QUERY: {query}
{skepticism_guidance}
Generate 4-6 short YouTube search queries that maximize recall without drifting off-topic.

Rules:
- Keep each query under 12 words.
- Preserve the original topic.
- Mix direct phrasing, concrete evidence terms, and validation / rebuttal framing when useful.
- Avoid quotes, operators, or site-specific syntax.
- Favor queries likely to surface independent creators covering the same event from different angles.

Return ONLY valid JSON in this shape:
{{
  "queries": ["...", "..."]
}}
"""


def search_rerank_prompt(query: str, videos: Sequence[Any], *, skeptical: bool = False) -> str:
    """Prompt for selecting the best learning set from recent YouTube candidates."""
    items: list[str] = []
    for video in videos:
        description = (getattr(video, "description", "") or "").replace("\n", " ").strip()
        if len(description) > 280:
            description = description[:277] + "..."
        items.append(
            f"""
VIDEO_ID: {video.video_id}
TITLE: {video.title}
CHANNEL: {video.channel_name}
DATE: {video.upload_date}
DURATION_SECONDS: {video.duration}
VIEWS: {getattr(video, "view_count", 0) or 0}
LIKES: {getattr(video, "like_count", 0) or 0}
COMMENTS: {getattr(video, "comment_count", 0) or 0}
DESCRIPTION: {description or "[none]"}
""".strip()
        )
    candidates = "\n\n---\n\n".join(items)
    skeptical_block = ""
    if skeptical:
        skeptical_block = """
SKEPTICAL MODE:
- This topic may contain rumor amplification, satire, April Fools content, or copycat reactions.
- Down-rank prank framing, hype-only titles, and single-source assertions without concrete evidence terms.
- Up-rank videos that mention artifacts, source material, demos, logs, repos, timelines, rebuttals, or explicit validation.
- Prefer a mix of primary explainers and independent cross-checks over many near-duplicate reactions.
"""

    return f"""You are selecting the best YouTube videos for rapid topic learning.

QUERY: {query}
{skeptical_block}
You are given recent YouTube candidates. Pick the videos that are MOST worth watching for someone trying to get smart quickly on this topic.

Optimize for:
- relevance to the query
- practical depth and specificity
- likely enterprise usefulness
- freshness
- credibility / signal quality

Do NOT optimize just for views. Avoid fluff, generic news roundups, clickbait, and near-duplicates.
Prefer videos that sound like real implementation guidance, architectural analysis, or substantive best-practice coverage.

Score every selected video from 0.0 to 1.0 on:
- relevance_score
- depth_score
- practicality_score
- freshness_score
- credibility_score
- final_score

Return ONLY valid JSON in this shape:
{{
  "ranked_videos": [
    {{
      "video_id": "...",
      "relevance_score": 0.0,
      "depth_score": 0.0,
      "practicality_score": 0.0,
      "freshness_score": 0.0,
      "credibility_score": 0.0,
      "final_score": 0.0,
      "rationale": "short reason"
    }}
  ]
}}

Rank all strong candidates in best-first order. Keep rationales brief and concrete.

SECURITY: {DERIVED_CONTENT_RULES}

CANDIDATES:
{candidates}
"""


def paper_query_expansion_prompt(query: str) -> str:
    """Prompt for generating alternative arXiv search phrasings for a topic."""
    return f"""You are designing arXiv search queries for a research intelligence workflow.

QUERY: {query}

Generate 4-6 alternative arXiv search phrasings that maximize recall of relevant papers without drifting off-topic. arXiv matches on title, abstract, and author fields.

Rules:
- Keep each query under 10 words.
- Preserve the core research topic.
- Use domain-specific vocabulary that appears in paper titles and abstracts (e.g., "transformer", "diffusion", "generative", "self-supervised", "representation learning").
- Prefer noun phrases over question forms.
- Avoid overly generic terms that would collide with unrelated subfields (e.g., "harmonization" alone matches image processing papers).
- Favor phrasings that distinguish the subfield you want from adjacent noise.

Return ONLY valid JSON in this shape:
{{
  "queries": ["...", "..."]
}}
"""


def paper_rerank_prompt(query: str, papers: Sequence[Any]) -> str:
    """Prompt for ranking arXiv candidates against a research goal."""
    items: list[str] = []
    for paper in papers:
        abstract = (getattr(paper, "abstract", "") or "").replace("\n", " ").strip()
        if len(abstract) > 600:
            abstract = abstract[:597] + "..."
        authors = ", ".join(getattr(paper, "authors", []) or [])[:200] or "[unknown]"
        categories = ", ".join(getattr(paper, "categories", []) or []) or "[none]"
        items.append(
            f"""
PAPER_ID: {paper.paper_id}
TITLE: {paper.title}
AUTHORS: {authors}
CATEGORIES: {categories}
PUBLISHED: {getattr(paper, "published_at", "") or "[unknown]"}
ABSTRACT: {abstract or "[none]"}
""".strip()
        )
    candidates = "\n\n---\n\n".join(items)

    return f"""You are selecting the best arXiv papers for a research corpus.

QUERY: {query}

You are given arXiv candidates. Pick the papers MOST worth a deep read for someone building research intelligence on this topic.

Optimize for:
- relevance to the query (topical fit of title and abstract)
- depth and substance (concrete methods, experiments, ablations -- not just surveys of surveys)
- novelty (new approach, dataset, or result rather than minor variation)
- credibility (substantive abstract, multiple authors or plausible affiliation signals, appropriate arXiv categories)

Down-rank papers that only share a keyword but live in an unrelated subfield (e.g., "image harmonization" when the query is about music harmony). Down-rank papers whose abstracts are vague or promotional.

Score every paper from 0.0 to 1.0 on:
- relevance_score
- depth_score
- novelty_score
- credibility_score
- final_score

Return ONLY valid JSON in this shape:
{{
  "ranked_papers": [
    {{
      "paper_id": "...",
      "relevance_score": 0.0,
      "depth_score": 0.0,
      "novelty_score": 0.0,
      "credibility_score": 0.0,
      "final_score": 0.0,
      "rationale": "short reason"
    }}
  ]
}}

Rank all strong candidates in best-first order. Keep rationales brief and concrete.

SECURITY: {DERIVED_CONTENT_RULES}

CANDIDATES:
{candidates}
"""


def discover_query_generation_prompt(
    goal: str, *, paper_count: int = 5, video_count: int = 5
) -> str:
    """Prompt for turning a research goal into candidate search queries for papers + videos."""
    return f"""You are planning a research corpus for a user-stated goal.

GOAL: {goal}

Generate two sets of search queries the user should run to build a corpus that serves this goal:

1. ARXIV QUERIES ({paper_count} queries) — optimized for arXiv title/abstract matching. Use domain-specific noun phrases ("transformer", "diffusion", "contrastive"), avoid generic terms that collide with unrelated subfields ("harmonization" alone hits image processing).

2. YOUTUBE QUERIES ({video_count} queries) — optimized for relevance-ordered YouTube search. Favor phrases creators actually use in titles. Mix deep-dive ("masterclass", "explained in depth") with practitioner angles ("tutorial", "how to").

Rules:
- Preserve the goal; do not drift.
- Keep each query under 10 words.
- Queries should complement each other — cover different angles of the goal, not the same angle phrased differently.

Return ONLY valid JSON in this shape:
{{
  "paper_queries": ["...", "..."],
  "video_queries": ["...", "..."]
}}
"""


def discover_rerank_prompt(goal: str, candidates: Sequence[dict[str, Any]]) -> str:
    """Prompt for goal-aware cross-source rerank of mixed papers and videos.

    candidates is a list of dicts with keys: kind ("paper"|"video"|"site"),
    identifier, title, subtitle (authors, channel, or site), date, description
    (abstract, description, or seed hint).
    """
    items: list[str] = []
    for c in candidates:
        desc = (c.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 500:
            desc = desc[:497] + "..."
        items.append(
            f"""
KIND: {c.get("kind", "?")}
IDENTIFIER: {c.get("identifier", "")}
TITLE: {c.get("title", "")}
SUBTITLE: {c.get("subtitle", "")}
DATE: {c.get("date", "")}
CONTENT: {desc or "[none]"}
""".strip()
        )
    blob = "\n\n---\n\n".join(items)

    return f"""You are curating a research corpus against a user-stated goal.

GOAL: {goal}

You are given a mixed pool of arXiv papers, YouTube videos, and optionally curated website pages. Pick and rank the items that together best serve the GOAL as a corpus. Optimize for:

- goal_fit: how directly this item advances understanding of the goal
- depth: substantive content (experiments, frameworks, concrete methods) over surveys of surveys or hot takes
- complementarity: does this add an angle the other top picks do not — prefer a diverse shortlist over five items that say the same thing

Penalize clickbait framings, unrelated subfields that happen to share a keyword, and items whose content is too shallow for the goal.
For website pages, reward official documentation, architecture explainers, implementation guidance, and concrete reference material when they directly support the goal.

Score every item 0.0-1.0 on goal_fit, depth_score, complementarity_score, and final_score.

Return ONLY valid JSON in this shape:
{{
  "ranked_items": [
    {{
      "identifier": "...",
      "kind": "paper" | "video" | "site",
      "goal_fit": 0.0,
      "depth_score": 0.0,
      "complementarity_score": 0.0,
      "final_score": 0.0,
      "rationale": "short reason tied to the goal"
    }}
  ]
}}

Rank in best-first order by final_score. Keep rationales tied to the goal, not generic.

SECURITY: {DERIVED_CONTENT_RULES}

CANDIDATES:
{blob}
"""
