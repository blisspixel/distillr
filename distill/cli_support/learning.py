"""Learning and query-expansion helpers for the Distill CLI."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from rich import box
from rich.table import Table

from distill.cli_shared import SHORTS_THRESHOLD, console
from distill.cli_shared import format_date as _format_date
from distill.config import DistillConfig, router_config_from_distill
from distill.ingestors.youtube.browser_search import search_youtube_results
from distill.ingestors.youtube.discovery import enrich_videos, search_videos
from distill.llm import call as llm_call
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.pipeline.ranking import RankedPaper, rerank_videos
from distill.prompts.discover import paper_query_expansion_prompt, search_query_expansion_prompt


def _expand_learning_queries(
    query: str,
    config: DistillConfig | None = None,
    tracker: CostTracker | None = None,
    *,
    skeptical: bool = False,
    expand: bool = True,
) -> list[str]:
    query = query.strip()
    if query.startswith("http://") or query.startswith("https://"):
        return [query]

    normalized = " ".join(query.split())
    variants = _heuristic_learning_queries(normalized, skeptical=skeptical)
    if expand and config and config.xai_api_key:
        llm_variants = _llm_expand_learning_queries(
            normalized,
            config,
            tracker=tracker,
            skeptical=skeptical,
        )
        if llm_variants:
            variants = [normalized, *llm_variants, *variants]
    return _dedupe_query_strings(variants)[:6]


def _heuristic_learning_queries(query: str, *, skeptical: bool = False) -> list[str]:
    normalized = " ".join(query.split())
    lowered = normalized.lower()
    variants = [normalized]

    if "best practices" in lowered:
        variants.append(
            _replace_case_insensitive(normalized, "best practices", "architecture best practices")
        )
        variants.append(
            _replace_case_insensitive(normalized, "best practices", "implementation guide")
        )
        variants.append(_replace_case_insensitive(normalized, "best practices", "tutorial"))
    elif "best practice" in lowered:
        variants.append(
            _replace_case_insensitive(normalized, "best practice", "architecture best practices")
        )

    if any(
        term in lowered
        for term in [
            "best practice",
            "best practices",
            "architecture",
            "implementation",
            "guide",
        ]
    ):
        base = _strip_intent_terms(normalized)
        if base and base.lower() != normalized.lower():
            variants.append(f"{base} architecture")
            variants.append(f"{base} implementation")
            variants.append(f"{base} walkthrough")

    if skeptical or _looks_like_rumor_query(normalized):
        base = _strip_noise_terms(normalized) or normalized
        variants.extend(
            [
                f"{base} source code",
                f"{base} sourcemap",
                f"{base} validation",
                f"{base} debunk",
                f"{base} what leaked",
            ]
        )

    return _dedupe_query_strings(variants)


def _llm_expand_learning_queries(
    query: str,
    config: DistillConfig,
    *,
    tracker: CostTracker | None = None,
    skeptical: bool = False,
) -> list[str]:
    rc = router_config_from_distill(config)
    prompt = search_query_expansion_prompt(query, skeptical=skeptical)
    response = llm_call(
        rc, workload_tag="rerank", prompt=prompt, max_tokens=512, call_type="search_expand"
    )
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="search_expand",
            )
        )
    content = response.text
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
    queries = data.get("queries", []) if isinstance(data, dict) else []
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()]


def _dedupe_query_strings(queries: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in queries:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item.strip())
    return deduped


def _expand_paper_queries(
    query: str,
    config: DistillConfig | None = None,
    tracker: CostTracker | None = None,
    *,
    expand: bool = True,
) -> list[str]:
    normalized = " ".join(query.split())
    if not normalized:
        return []
    variants = [normalized]
    if expand and config and config.xai_api_key:
        try:
            llm_variants = _llm_expand_paper_queries(normalized, config, tracker=tracker)
        except Exception as e:
            console.print(f"  [yellow]Query expansion fallback: {e}[/yellow]")
            llm_variants = []
        variants.extend(llm_variants)
    return _dedupe_query_strings(variants)[:6]


def _llm_expand_paper_queries(
    query: str,
    config: DistillConfig,
    *,
    tracker: CostTracker | None = None,
) -> list[str]:
    rc = router_config_from_distill(config)
    prompt = paper_query_expansion_prompt(query)
    response = llm_call(
        rc, workload_tag="rerank", prompt=prompt, max_tokens=512, call_type="paper_expand"
    )
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="paper_expand",
            )
        )
    content = response.text
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
    queries = data.get("queries", []) if isinstance(data, dict) else []
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()]


def _display_ranked_papers(ranked: list[RankedPaper], title: str) -> None:
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("#", justify="right")
    table.add_column("Title", overflow="fold")
    table.add_column("Authors", overflow="fold")
    table.add_column("Published")
    table.add_column("Categories", overflow="fold")
    table.add_column("Score", justify="right")
    table.add_column("Why", overflow="fold")
    for idx, item in enumerate(ranked, 1):
        authors = ", ".join(item.paper.authors[:2]) if item.paper.authors else "unknown"
        if item.paper.authors and len(item.paper.authors) > 2:
            authors += f" +{len(item.paper.authors) - 2}"
        categories = ", ".join(item.paper.categories[:3]) if item.paper.categories else "-"
        published = (item.paper.published_at or "")[:10] or "-"
        table.add_row(
            str(idx),
            item.paper.title,
            authors,
            published,
            categories,
            f"{item.final_score:.2f}",
            item.rationale,
        )
    console.print(table)


def _replace_case_insensitive(text: str, old: str, new: str) -> str:
    idx = text.lower().find(old.lower())
    if idx < 0:
        return text
    return text[:idx] + new + text[idx + len(old) :]


def _strip_intent_terms(query: str) -> str:
    intent_terms = {
        "best",
        "practice",
        "practices",
        "architecture",
        "implementation",
        "guide",
        "walkthrough",
        "tutorial",
        "how",
        "to",
        "for",
    }
    words = [word for word in query.split() if word.lower() not in intent_terms]
    return " ".join(words).strip()


def _strip_noise_terms(query: str) -> str:
    noise_terms = {
        "analysis",
        "latest",
        "news",
        "rumor",
        "rumour",
        "leak",
        "leaked",
    }
    words = [word for word in query.split() if word.lower() not in noise_terms]
    return " ".join(words).strip()


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


def _auto_skeptical_mode(query: str, *, hours: int | None, days: int) -> bool:
    now = datetime.now()
    if now.month == 4 and now.day == 1 and (hours is None or hours <= 48 or days <= 2):
        return True
    return _looks_like_rumor_query(query)


def _effective_days(days: int, hours: int | None) -> int:
    if hours is None:
        return days
    return max(days, max(1, (hours + 23) // 24))


def _window_label(days: int, hours: int | None) -> str:
    if hours is not None:
        return f"{hours} hours"
    return f"{days} days"


def _default_report_focus(query: str, *, skeptical: bool) -> str | None:
    if not skeptical:
        return None
    return (
        f"Treat this as a rumor-sensitive topic. Cross-validate creator claims for '{query}' across independent videos and external primary sources. "
        "Separate concrete technical evidence from reaction content, satire, April 1 jokes, and unsupported amplification."
    )


def _filter_recent_candidates(videos: list, days: int, hours: int | None = None) -> list:
    cutoff = (
        datetime.now() - timedelta(hours=hours)
        if hours is not None
        else datetime.now() - timedelta(days=days)
    )
    filtered = []
    for video in videos:
        published_at = getattr(video, "published_at", "")
        if published_at:
            try:
                upload_dt = datetime.fromisoformat(published_at)
            except ValueError:
                upload_dt = None
            if upload_dt is not None:
                if upload_dt >= cutoff:
                    filtered.append(video)
                continue
        if not getattr(video, "upload_date", ""):
            filtered.append(video)
            continue
        try:
            upload_dt = datetime.strptime(video.upload_date, "%Y%m%d")
        except ValueError:
            filtered.append(video)
            continue
        if upload_dt >= cutoff:
            filtered.append(video)
    return filtered


def _dedupe_candidates(videos: list) -> list:
    deduped = []
    seen = set()
    for video in videos:
        if video.video_id in seen:
            continue
        seen.add(video.video_id)
        deduped.append(video)
    return deduped


def _format_metric(value: int) -> str:
    if not value:
        return "-"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _select_learning_videos(
    query: str,
    config: DistillConfig,
    tracker: CostTracker,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    *,
    hours: int | None = None,
    skeptical: bool = False,
    expand: bool = True,
):
    effective_days = _effective_days(days, hours)
    candidate_limit = max(limit * 2, 12)
    raw_candidates = []
    queries = _expand_learning_queries(
        query,
        config,
        tracker,
        skeptical=skeptical,
        expand=expand,
    )
    for idx, variant in enumerate(queries, 1):
        console.print(f"[dim]Candidate search {idx}/{len(queries)}: {variant}[/dim]")
        raw_candidates.extend(
            search_youtube_results(
                variant,
                days=effective_days,
                hours=hours,
                limit=candidate_limit,
            )
        )
    raw_candidates = _dedupe_candidates(raw_candidates)
    if not raw_candidates:
        console.print(
            "[dim]Browser-based search returned no candidates; falling back to yt-dlp search[/dim]"
        )
        raw_candidates = search_videos(
            query,
            days=effective_days,
            limit=candidate_limit,
            sort=sort,
            per_channel_cap=max(per_channel_cap * 2, 4),
        )
    if not shorts:
        raw_candidates = [v for v in raw_candidates if v.duration > SHORTS_THRESHOLD]
        console.print(f"[dim]Filtered to {len(raw_candidates)} full-length candidates[/dim]")

    if not raw_candidates:
        return [], []

    enriched = enrich_videos(raw_candidates, max_videos=min(len(raw_candidates), 12))
    enriched = _filter_recent_candidates(enriched, effective_days, hours=hours)
    ranked = rerank_videos(
        query,
        enriched,
        config,
        tracker=tracker,
        top_n=max(limit * 2, 10),
        use_llm=rerank,
        skeptical=skeptical,
    )
    selected = _apply_ranked_channel_cap(ranked, limit, per_channel_cap)
    return enriched, selected


def _apply_ranked_channel_cap(ranked, limit: int, per_channel_cap: int):
    selected = []
    counts = {}
    for item in ranked:
        channel_key = (item.video.channel_name or "unknown").strip().lower() or "unknown"
        if counts.get(channel_key, 0) >= per_channel_cap:
            continue
        selected.append(item)
        counts[channel_key] = counts.get(channel_key, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def _display_ranked_videos(ranked, title: str):
    table = Table(title=title, box=box.SIMPLE_HEAVY)
    table.add_column("#", justify="right")
    table.add_column("Title", overflow="fold")
    table.add_column("Channel")
    table.add_column("Date")
    table.add_column("Views", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Why", overflow="fold")
    for idx, item in enumerate(ranked, 1):
        table.add_row(
            str(idx),
            item.video.title,
            item.video.channel_name or "unknown",
            _format_date(item.video.upload_date),
            _format_metric(item.video.view_count),
            f"{item.final_score:.2f}",
            item.rationale,
        )
    console.print(table)
