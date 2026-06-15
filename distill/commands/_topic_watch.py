"""Topic-watch support helpers (naming + ranking-mode resolution).

Small, pure helpers shared by the topic-watch commands (still in ``_logic``),
the discovery flow (``commands/discover.py``), and the home-screen renderer
(``commands/dashboard.py``). Extracted from ``_logic.py`` during the Phase 2
decomposition so the shared seam lives in a foundation module instead of being
imported back out of the monolith.

Ranking-mode resolution is deterministic alias normalization onto a fixed,
documented vocabulary (freshness / balanced / popularity) -- structural ground
truth, not a semantic judgment, so it stays a rule.
"""

from __future__ import annotations

import typer

from distill.cli_shared import topic_from_query as _topic_from_query
from distill.library.paths import slugify_title


def _topic_watch_name(query: str, topic: str | None, name: str | None) -> str:
    if name:
        return name
    base = topic or _topic_from_query(query)
    return slugify_title(base, max_len=30)


_TOPIC_WATCH_RANKING_ALIASES = {
    "freshness": "freshness",
    "freshness-first": "freshness",
    "fresh": "freshness",
    "balanced": "balanced",
    "balanced-mix": "balanced",
    "popularity": "popularity",
    "popularity-biased": "popularity",
    "popular": "popularity",
}


def _normalize_topic_watch_ranking_mode(value: str) -> str:
    normalized = _TOPIC_WATCH_RANKING_ALIASES.get(value.lower().strip())
    if not normalized:
        allowed = ", ".join(["freshness", "balanced", "popularity"])
        raise typer.BadParameter(f"ranking mode must be one of: {allowed}")
    return normalized


def _topic_watch_ranking_strategy(ranking_mode: str) -> dict[str, object]:
    mode = _normalize_topic_watch_ranking_mode(ranking_mode)
    if mode == "freshness":
        return {"mode": mode, "sort": "date", "rerank": False, "label": "freshness-first"}
    if mode == "popularity":
        return {"mode": mode, "sort": "relevance", "rerank": False, "label": "popularity-biased"}
    return {"mode": "balanced", "sort": "date", "rerank": True, "label": "balanced mix"}
