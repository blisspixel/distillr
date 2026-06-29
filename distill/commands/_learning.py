# pyright: strict
"""Learning and query-expansion helpers for the Distill CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

from rich import box
from rich.table import Table

from distill.cli_shared import SHORTS_THRESHOLD, console
from distill.cli_shared import format_date as _format_date
from distill.commands import _learning_flow as _learning_flow_support
from distill.commands._helpers import (
    ensure_channel_context as _ensure_channel_context,
)
from distill.commands._helpers import (
    get_config,
)
from distill.commands._helpers import (
    output_path as _output_path,
)
from distill.commands._helpers import (
    process_video as _process_video,
)
from distill.commands._helpers import (
    run_preflight as _preflight,
)
from distill.commands._helpers import (
    run_scope_report as _run_scope_report,
)
from distill.commands._helpers import (
    topic_from_query as _topic_from_query,
)
from distill.config import DistillConfig
from distill.ingestors.youtube.browser_search import search_youtube_results
from distill.ingestors.youtube.discovery import VideoInfo, enrich_videos, search_videos
from distill.library import Library
from distill.llm import call as llm_call
from distill.llm.availability import model_available
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.pipeline.ranking import RankedPaper, RankedVideo, chronological_rank, rerank_videos
from distill.pipeline.report.briefing import generate_topic_brief
from distill.pipeline.summary import RunSummary
from distill.pipeline.synthesis.corpus import synthesize_corpus
from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic
from distill.prompts.discover import paper_query_expansion_prompt, search_query_expansion_prompt


class _ScoredRankedItem(Protocol):
    final_score: float


class _RankedVideoSelection(Protocol):
    video: VideoInfo


def _query_strings_from_response_text(text: str) -> list[str]:
    data = json.loads(text)
    if not isinstance(data, dict):
        return []
    payload = cast("dict[str, object]", data)
    raw_queries = payload.get("queries", [])
    if not isinstance(raw_queries, list):
        return []
    queries: list[str] = []
    for item in cast(list[object], raw_queries):
        if isinstance(item, str) and item.strip():
            queries.append(item.strip())
    return queries


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
    if expand and config and model_available("rerank"):
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

    if skeptical:
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
    rc = RouterConfig()
    prompt = search_query_expansion_prompt(query, skeptical=skeptical)
    response = llm_call(
        rc, workload_tag="rerank", prompt=prompt, max_tokens=512, call_type="search_expand"
    )
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="search_expand"))
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
    return _query_strings_from_response_text(text)


def _dedupe_query_strings(queries: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in queries:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item.strip())
    return deduped


def dedupe_query_strings(queries: list[str]) -> list[str]:
    """Public query de-duplication seam for command helpers."""
    return _dedupe_query_strings(queries)


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
    if expand and config and model_available("rerank"):
        try:
            llm_variants = _llm_expand_paper_queries(normalized, config, tracker=tracker)
        except Exception as e:
            console.print(f"  [yellow]Query expansion fallback: {e}[/yellow]")
            llm_variants = []
        variants.extend(llm_variants)
    return _dedupe_query_strings(variants)[:6]


def expand_paper_queries(
    query: str,
    config: DistillConfig | None = None,
    tracker: CostTracker | None = None,
    *,
    expand: bool = True,
) -> list[str]:
    """Public paper-query expansion seam for command modules."""
    return _expand_paper_queries(query, config=config, tracker=tracker, expand=expand)


def _llm_expand_paper_queries(
    query: str,
    config: DistillConfig,
    *,
    tracker: CostTracker | None = None,
) -> list[str]:
    rc = RouterConfig()
    prompt = paper_query_expansion_prompt(query)
    response = llm_call(
        rc, workload_tag="rerank", prompt=prompt, max_tokens=512, call_type="paper_expand"
    )
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="paper_expand"))
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
    return _query_strings_from_response_text(text)


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


def display_ranked_papers(ranked: list[RankedPaper], title: str) -> None:
    """Public ranked-paper rendering seam for command modules."""
    _display_ranked_papers(ranked, title)


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


def _auto_skeptical_mode(query: str, *, hours: int | None, days: int) -> bool:
    # Structural date guard only: April 1 carries elevated prank/satire risk for
    # short windows, so default skeptical mode on then. This used to also flip on
    # when a keyword list decided the query "looks like a rumor" (leak/hack/even
    # "analysis") -- a brittle proxy that leaked into the primary rerank prompt.
    # Removed (P3): whether a source is an unverified leak is the model's read.
    # `query` is retained for the injected-callable signature but unused.
    now = datetime.now()
    return now.month == 4 and now.day == 1 and (hours is None or hours <= 48 or days <= 2)


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


def _filter_recent_candidates(
    videos: list[VideoInfo], days: int, hours: int | None = None
) -> list[VideoInfo]:
    cutoff = (
        datetime.now() - timedelta(hours=hours)
        if hours is not None
        else datetime.now() - timedelta(days=days)
    )
    filtered: list[VideoInfo] = []
    for video in videos:
        published_at = video.published_at
        if published_at:
            try:
                upload_dt = datetime.fromisoformat(published_at)
                # YouTube returns tz-aware timestamps (RFC3339 with Z/offset);
                # cutoff is naive local time, so normalize to naive local to
                # avoid "can't compare offset-naive and offset-aware" below.
                if upload_dt.tzinfo is not None:
                    upload_dt = upload_dt.astimezone().replace(tzinfo=None)
            except ValueError:
                upload_dt = None
            if upload_dt is not None:
                if upload_dt >= cutoff:
                    filtered.append(video)
                continue
        if not video.upload_date:
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


def filter_recent_candidates(
    videos: list[VideoInfo], days: int, hours: int | None = None
) -> list[VideoInfo]:
    """Public recent-video filter seam for command helpers."""
    return _filter_recent_candidates(videos, days, hours=hours)


def _dedupe_candidates(videos: list[VideoInfo]) -> list[VideoInfo]:
    deduped: list[VideoInfo] = []
    seen: set[str] = set()
    for video in videos:
        if video.video_id in seen:
            continue
        seen.add(video.video_id)
        deduped.append(video)
    return deduped


def dedupe_candidates(videos: list[VideoInfo]) -> list[VideoInfo]:
    """Public video de-duplication seam for command helpers."""
    return _dedupe_candidates(videos)


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
    top_by_date: bool = False,
    rigor: str = "off",
) -> tuple[list[VideoInfo], list[RankedVideo]]:
    effective_days = _effective_days(days, hours)
    candidate_limit = max(limit * 2, 12)
    raw_candidates: list[VideoInfo] = []
    # Strict chronological mode bypasses both rerank and the heuristic mix,
    # which means query expansion would only burn tokens and leak the query
    # to the LLM provider without ever influencing the final selection.
    effective_expand = expand and not top_by_date
    queries = _expand_learning_queries(
        query,
        config,
        tracker,
        skeptical=skeptical,
        expand=effective_expand,
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
    if top_by_date:
        # Strict chronological pick: bypass both LLM rerank and the heuristic
        # mix. Channel cap still applies to keep one prolific uploader from
        # monopolizing the slate.
        ranked = chronological_rank(enriched, top_n=max(limit * 2, 10))
    else:
        ranked = rerank_videos(
            query,
            enriched,
            config,
            tracker=tracker,
            top_n=max(limit * 2, 10),
            use_llm=rerank,
            skeptical=skeptical,
        )
        # A rigor bar drops sub-threshold videos before the channel cap; chronological
        # mode (top_by_date) bypasses scoring entirely, so rigor never applies there.
        ranked = _apply_source_rigor(
            ranked, source="video", rigor=rigor, rerank_on=rerank, limit=len(ranked)
        )
    selected = _apply_ranked_channel_cap(ranked, limit, per_channel_cap)
    return enriched, selected


def _preview_learning_selection(
    query: str,
    *,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    header: str,
    table_title: str,
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    top_by_date: bool = False,
    rigor: str = "off",
) -> tuple[DistillConfig, CostTracker, list[RankedVideo]]:
    return _learning_flow_support.preview_learning_selection(
        query,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        header=header,
        table_title=table_title,
        get_config=get_config,
        cost_tracker_factory=CostTracker,
        auto_skeptical_mode=_auto_skeptical_mode,
        window_label=_window_label,
        select_learning_videos=_select_learning_videos,
        display_ranked_videos=_display_ranked_videos,
        hours=hours,
        skeptical=skeptical,
        expand=expand,
        top_by_date=top_by_date,
        rigor=rigor,
    )


def preview_learning_selection(
    query: str,
    *,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    header: str,
    table_title: str,
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    top_by_date: bool = False,
    rigor: str = "off",
) -> tuple[DistillConfig, CostTracker, list[RankedVideo]]:
    """Public learning-preview command seam."""
    return _preview_learning_selection(
        query,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        header=header,
        table_title=table_title,
        hours=hours,
        skeptical=skeptical,
        expand=expand,
        top_by_date=top_by_date,
        rigor=rigor,
    )


def _run_learning_command(
    query: str,
    *,
    topic: str | None,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    header: str,
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    focus: str | None = None,
    top_by_date: bool = False,
    post_ingest_callback: Callable[[str, CostTracker], None] | None = None,
    rigor: str = "off",
) -> None:
    _preflight()
    _learning_flow_support.run_learning_command(
        query,
        topic=topic,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        save=save,
        report=report,
        test=test,
        generate_brief=generate_brief,
        header=header,
        get_config=get_config,
        cost_tracker_factory=CostTracker,
        topic_from_query=_topic_from_query,
        auto_skeptical_mode=_auto_skeptical_mode,
        default_report_focus=_default_report_focus,
        window_label=_window_label,
        select_learning_videos=_select_learning_videos,
        display_ranked_videos=_display_ranked_videos,
        process_learning_selection=_process_learning_selection,
        hours=hours,
        skeptical=skeptical,
        expand=expand,
        focus=focus,
        top_by_date=top_by_date,
        post_ingest_callback=post_ingest_callback,
        rigor=rigor,
    )


def run_learning_command(
    query: str,
    *,
    topic: str | None,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    header: str,
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    focus: str | None = None,
    top_by_date: bool = False,
    post_ingest_callback: Callable[[str, CostTracker], None] | None = None,
    rigor: str = "off",
) -> None:
    """Public learning-ingest command seam."""
    _run_learning_command(
        query,
        topic=topic,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        save=save,
        report=report,
        test=test,
        generate_brief=generate_brief,
        header=header,
        hours=hours,
        skeptical=skeptical,
        expand=expand,
        focus=focus,
        top_by_date=top_by_date,
        post_ingest_callback=post_ingest_callback,
        rigor=rigor,
    )


def _process_learning_selection(
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    selected: list[Any],
    *,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    report_focus: str | None = None,
    post_ingest_callback: Callable[[str, CostTracker], None] | None = None,
) -> None:
    _learning_flow_support.process_learning_selection(
        topic_name,
        config,
        tracker,
        selected,
        save=save,
        report=report,
        test=test,
        generate_brief=generate_brief,
        library_factory=Library,
        run_summary_factory=RunSummary,
        output_path=_output_path,
        ensure_channel_context=_ensure_channel_context,
        process_video=_process_video,
        synthesize_channel=synthesize_channel,
        synthesize_topic=synthesize_topic,
        synthesize_corpus=synthesize_corpus,
        run_scope_report=_run_scope_report,
        generate_and_export_topic_brief=_generate_and_export_topic_brief,
        report_focus=report_focus,
        post_ingest_callback=post_ingest_callback,
    )


def process_learning_selection(
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    selected: list[Any],
    *,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    report_focus: str | None = None,
    post_ingest_callback: Any | None = None,
) -> None:
    """Public learning-selection ingest seam for command helpers."""
    _process_learning_selection(
        topic_name,
        config,
        tracker,
        selected,
        save=save,
        report=report,
        test=test,
        generate_brief=generate_brief,
        report_focus=report_focus,
        post_ingest_callback=post_ingest_callback,
    )


def _generate_and_export_topic_brief(
    topic_name: str, config: DistillConfig, tracker: CostTracker
) -> None:
    _learning_flow_support.generate_and_export_topic_brief(
        topic_name,
        config,
        tracker,
        generate_topic_brief=generate_topic_brief,
        output_path=_output_path,
    )


def generate_and_export_topic_brief(
    topic_name: str, config: DistillConfig, tracker: CostTracker
) -> None:
    """Public topic-brief export seam for command helpers."""
    _generate_and_export_topic_brief(topic_name, config, tracker)


def _apply_ranked_channel_cap[T: _RankedVideoSelection](
    ranked: list[T], limit: int, per_channel_cap: int
) -> list[T]:
    selected: list[T] = []
    counts: dict[str, int] = {}
    for item in ranked:
        channel_key = (item.video.channel_name or "unknown").strip().lower() or "unknown"
        if counts.get(channel_key, 0) >= per_channel_cap:
            continue
        selected.append(item)
        counts[channel_key] = counts.get(channel_key, 0) + 1
        if len(selected) >= limit:
            break
    return selected


def _apply_source_rigor[T: _ScoredRankedItem](
    ranked: list[T],
    *,
    source: str,
    rigor: str,
    rerank_on: bool,
    limit: int,
) -> list[T]:
    """Drop reranked items below the per-source rigor bar, then cap at ``limit``."""
    if rigor == "off":
        return ranked[:limit]
    if not rerank_on:
        console.print(
            f"[yellow]--rigor {rigor} needs the LLM rerank (it scores on the rerank's scale); "
            "ignoring it under --no-rerank.[/yellow]"
        )
        return ranked[:limit]
    from distill.pipeline.discovery import source_rigor_threshold

    threshold = source_rigor_threshold(source, rigor)
    kept = [r for r in ranked if r.final_score >= threshold]
    if len(kept) < len(ranked):
        console.print(
            f"  [dim]--rigor {rigor}: kept {len(kept)}/{len(ranked)} candidate(s) "
            f"(score >= {threshold:.2f})[/dim]"
        )
    if not kept:
        console.print(
            f"[yellow]No candidates clear the '{rigor}' bar (score >= {threshold:.2f}). "
            "Try --rigor loose.[/yellow]"
        )
    return kept[:limit]


def apply_source_rigor[T: _ScoredRankedItem](
    ranked: list[T],
    *,
    source: str,
    rigor: str,
    rerank_on: bool,
    limit: int,
) -> list[T]:
    """Public source-rigor filtering seam for command modules."""
    return _apply_source_rigor(
        ranked,
        source=source,
        rigor=rigor,
        rerank_on=rerank_on,
        limit=limit,
    )


def _display_ranked_videos(ranked: list[RankedVideo], title: str) -> None:
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
