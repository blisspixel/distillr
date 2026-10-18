# pyright: strict
"""arXiv paper ingestion commands, extracted from the _logic monolith.

`distill paper` (single arXiv paper) and `distill papers` (query-expanded,
LLM-reranked multi-paper ingest with cross-paper synthesis). Paper artifact
writing lives in `_paper_artifacts`; shared concept helpers stay in _logic
during the decomposition. Registered via register().
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import typer

import distill.cli_shared as cli_shared
from distill._console import console
from distill.cli_shared import require_model as _require_model
from distill.cli_shared import topic_from_query as _topic_from_query
from distill.commands._concept_ingest import (
    run_concepts_after_ingest as _run_concepts_after_ingest,
)
from distill.commands._helpers import (
    _apply_verify_override,
    _persist_lens,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
    resolve_intent,
)
from distill.commands._json import ExitCode
from distill.commands._learning import (
    apply_source_rigor,
    display_ranked_papers,
    expand_paper_queries,
)
from distill.commands._paper_artifacts import PaperPublicationRefusedError
from distill.commands._paper_artifacts import write_paper_artifacts as _write_paper_artifacts
from distill.commands._paper_search import report_revision_candidates, report_search_coverage
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import (
    PaperRecord,
    PaperSearchResults,
    fetch_arxiv_paper,
    search_arxiv_multi,
    search_arxiv_papers,
)
from distill.ingestors.papers.search_receipts import SearchReceipt
from distill.library.intent import CorpusIntent
from distill.library.paths import find_artifact
from distill.llm.availability import model_available
from distill.llm.cost_policy import LOCAL_PROVIDER_NAMES, CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.concurrency import (
    MAX_INGEST_WORKERS,
    BoundedTaskResult,
    iter_bounded,
)
from distill.pipeline.costs import BudgetExceededError, CostTracker, estimate_paper_workflow_cost
from distill.pipeline.duration_estimates import (
    DurationEstimate,
    estimate_stage_duration,
    estimate_workflow_duration,
    format_run_projection,
    load_speed_calibration,
)
from distill.pipeline.ranking import RankedPaper, rerank_papers
from distill.pipeline.summary import BatchProgress, RunSummary, display_summary
from distill.pipeline.synthesis.corpus import has_corpus_synthesis_inputs, synthesize_corpus

__all__ = ["paper", "papers", "register"]

_apply_source_rigor = apply_source_rigor
_display_ranked_papers = display_ranked_papers
_expand_paper_queries = expand_paper_queries
_resolve_intent = resolve_intent


def _nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _paper_tail_calls(topic: str, config: DistillConfig) -> int:
    """One paper synthesis plus a corpus call only when mixed inputs require it."""
    return 1 + int(has_corpus_synthesis_inputs(topic, config))


def _papers_run_projection(
    paper_count: int,
    *,
    synthesis_calls: int,
    projected_cost: float,
    config: DistillConfig,
    router_config: RouterConfig,
) -> None:
    """Print the $ and wall-clock projection for this papers run."""
    provider, model = router_config.resolve("analysis")
    local = provider in LOCAL_PROVIDER_NAMES
    duration = DurationEstimate(model=model)
    if local:
        calibration = load_speed_calibration(config.library_dir, model=model, provider=provider)
        duration = estimate_workflow_duration(
            {"paper": max(paper_count, 0), "synthesis": max(synthesis_calls, 0)},
            calibration,
        )
    line = format_run_projection(cost_usd=projected_cost, duration=duration, local=local)
    if local:
        console.print(line)
        console.print(
            "[dim]This projection covers analysis only. "
            "Follow up with --from-shortlist to skip search and rerank.[/dim]"
        )
    else:
        console.print(f"[yellow]{line}[/yellow]")


def _planned_paper_seconds(router_config: RouterConfig, config: DistillConfig) -> float:
    provider, model = router_config.resolve("analysis")
    if provider not in LOCAL_PROVIDER_NAMES:
        return 0.0
    estimate = estimate_stage_duration(
        "paper",
        load_speed_calibration(config.library_dir, model=model, provider=provider),
    )
    return estimate.expected_seconds if estimate.calibrated else 0.0


def _write_completed_paper(
    result: BoundedTaskResult[PaperRecord, tuple[str, str]],
    *,
    topic: str,
    config: DistillConfig,
) -> tuple[Path | None, Exception | None]:
    error = result.error
    if isinstance(error, (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError)):
        raise error
    if error is not None:
        return None, error
    if result.value is None:
        return None, RuntimeError("paper analysis completed without a result")

    insights, document = result.value
    try:
        # Verification, filesystem writes, console notices, and summary
        # mutation stay on the coordinating thread.
        return (
            _write_paper_artifacts(
                topic,
                result.item,
                config,
                insights,
                document,
            ),
            None,
        )
    except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
        raise
    except Exception as exc:
        return None, exc


def _analyze_paper_batch(
    records: list[PaperRecord],
    *,
    topic: str,
    config: DistillConfig,
    tracker: CostTracker,
    router_config: RouterConfig,
    workers: int,
    summary: RunSummary,
) -> int:
    """Analyze independent papers concurrently and serialize all shared writes."""

    intent: CorpusIntent | None = _resolve_intent(config, topic)
    item_estimate = estimate_paper_workflow_cost(
        1,
        synthesis_calls=0,
        router_config=router_config,
    )
    progress = BatchProgress(
        "paper",
        len(records),
        tracker,
        planned_item_seconds=_planned_paper_seconds(router_config, config),
    )
    starts: dict[int, float] = {}
    paper_dirs: dict[int, Path] = {}
    item_errors: dict[int, Exception] = {}

    def on_submit(index: int, record: PaperRecord) -> None:
        starts[index] = progress.start_item()
        console.print(progress.item_line("analyze", record.title, index=index + 1))

    def analyze(record: PaperRecord) -> tuple[str, str]:
        with tracker.reserve_budget(item_estimate):
            item_tracker = tracker.concurrent_child()
            return analyze_paper(
                record,
                config,
                tracker=item_tracker,
                intent=intent,
            )

    for result in iter_bounded(
        records,
        analyze,
        max_workers=workers,
        on_submit=on_submit,
    ):
        paper_dir, error = _write_completed_paper(result, topic=topic, config=config)
        success = paper_dir is not None
        if paper_dir is not None:
            paper_dirs[result.index] = paper_dir

        if error is not None:
            item_errors[result.index] = error
            console.print(f"  [red]failed: {error}[/red]")

        progress.finish_item(starts.pop(result.index), success=success)
        console.print(progress.status_line("done" if success else "failed"))

    # Stable summary order follows the selected-paper order, independent of
    # completion timing.
    for index, record in enumerate(records):
        error = item_errors.get(index)
        if error is not None:
            cli_shared.record_exception_issue(
                summary,
                stage="paper-analysis",
                exc=error,
                context=record.title,
                details={"topic": topic, "paper_id": record.paper_id},
            )
            continue
        paper_dir = paper_dirs[index]
        summary.add_output(find_artifact(paper_dir, "paper"))
        summary.add_output(find_artifact(paper_dir, "insights"))
    return len(paper_dirs)


def _completed_paper_artifacts(
    config: DistillConfig,
    topic: str,
    paper_id: str,
) -> tuple[Path, Path, Path] | None:
    """Return receipts for an exact arXiv version, never a versionless match."""
    papers_dir = config.papers_dir(topic)
    if not papers_dir.exists():
        return None
    for metadata_path in sorted(papers_dir.glob("*/metadata.json")):
        try:
            raw_metadata: object = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, RecursionError, UnicodeError, ValueError):
            continue
        if not isinstance(raw_metadata, dict):
            continue
        metadata = cast("dict[str, object]", raw_metadata)
        if metadata.get("paper_id") != paper_id:
            continue
        paper_dir = metadata_path.parent
        paper_path = find_artifact(paper_dir, "paper")
        insights_path = find_artifact(paper_dir, "insights")
        if _nonempty(paper_path) and _nonempty(insights_path):
            return paper_dir, paper_path, insights_path
    return None


def paper(
    target: str = typer.Argument(help="arXiv paper URL or paper ID"),
    topic: str = typer.Option("papers", "--topic", "-t", help="Topic to file under"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reanalyze even when this exact arXiv version already has complete artifacts.",
    ),
):
    """Ingest and analyze one arXiv version, reusing an exact completed replay."""
    config = get_config()
    tracker = budgeted_cost_tracker(config, "paper")
    summary = RunSummary(command="paper")
    summary.set_metadata(topic=topic, workflow="paper", source_type="paper")

    paper_record = fetch_arxiv_paper(target)
    if not paper_record:
        summary.add_issue("paper-fetch", "Could not fetch paper metadata", context=target)
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)

    console.print(f"\n[bold]{paper_record.title}[/bold]")
    if paper_record.authors:
        console.print(f"[dim]{', '.join(paper_record.authors[:6])}[/dim]")

    completed = _completed_paper_artifacts(config, topic, paper_record.paper_id)
    if completed is not None and not force:
        _paper_dir, paper_path, insights_path = completed
        console.print(
            "[dim]Already complete for this exact arXiv version. Reusing existing "
            "artifacts; pass --force to reanalyze.[/dim]"
        )
        console.print(f"  paper           {paper_path.relative_to(config.library_dir)}")
        console.print(f"  insights        {insights_path.relative_to(config.library_dir)}")
        return

    router_config = RouterConfig()
    projected_cost = estimate_paper_workflow_cost(
        1,
        synthesis_calls=_paper_tail_calls(topic, config),
        router_config=router_config,
    )
    enforce_projected_workflow_budget(config, "paper", projected_cost)
    summary.estimated_cost = projected_cost
    _papers_run_projection(
        1,
        synthesis_calls=_paper_tail_calls(topic, config),
        projected_cost=projected_cost,
        config=config,
        router_config=router_config,
    )
    _require_model()
    insights, document = analyze_paper(
        paper_record,
        config,
        tracker=tracker,
        intent=_resolve_intent(config, topic),
    )
    try:
        paper_dir = _write_paper_artifacts(topic, paper_record, config, insights, document)
    except PaperPublicationRefusedError as exc:
        summary.add_issue("paper-publication", str(exc), context=paper_record.paper_id)
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1) from exc
    summary.add_output(find_artifact(paper_dir, "paper"))
    summary.add_output(find_artifact(paper_dir, "insights"))
    synthesis = synthesize_papers(topic, config, tracker=tracker)
    if synthesis:
        summary.add_output(
            find_artifact(config.topic_dir(topic), "paper_synthesis", identity=topic)
        )
    corpus_synth = synthesize_corpus(topic, config, tracker=tracker)
    if corpus_synth:
        summary.add_output(
            find_artifact(config.topic_dir(topic), "corpus_synthesis", identity=topic)
        )
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


def _papers_usage(message: str) -> None:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(int(ExitCode.USAGE_ERROR))


def _deterministic_rank_notice() -> None:
    console.print(
        "[yellow]No model configured; used deterministic ranking fallback "
        "(set a cloud key or DISTILL_PROVIDER=ollama for LLM reranking)[/yellow]"
    )


def _expanded_paper_queries(
    query: str,
    *,
    config: DistillConfig,
    tracker: CostTracker,
    expand: bool,
    limit: int,
    preview: bool,
) -> list[str]:
    try:
        queries = _expand_paper_queries(query, config=config, tracker=tracker, expand=expand)
    except CostPolicyError:
        if not preview:
            raise
        console.print(
            "[yellow]Query expansion skipped under no-metered. Using the original query.[/yellow]"
        )
        queries = [query]
    if not queries:
        queries = [query]
    return queries[: max(2, limit)]


def _rank_for_run(
    query: str,
    candidates: list[PaperRecord],
    config: DistillConfig,
    tracker: CostTracker,
    *,
    limit: int,
    rerank: bool,
    rigor: str,
    preview: bool,
) -> list[RankedPaper]:
    use_llm = rerank
    if preview and rerank:
        try:
            if not model_available("rerank"):
                use_llm = False
        except CostPolicyError:
            use_llm = False
    pool_n = len(candidates) if (rerank and rigor != "off") else limit
    try:
        ranked = rerank_papers(
            query,
            candidates,
            config,
            tracker=tracker,
            top_n=pool_n,
            use_llm=use_llm,
        )
    except CostPolicyError:
        if not preview:
            raise
        use_llm = False
        ranked = rerank_papers(
            query,
            candidates,
            config,
            tracker=tracker,
            top_n=pool_n,
            use_llm=False,
        )
    if rerank and (not use_llm or not model_available("rerank")):
        _deterministic_rank_notice()
    return ranked


def _analysis_model_label(router_config: RouterConfig) -> str:
    provider, model = router_config.resolve("analysis")
    return f"{provider}/{model}"


def _save_preview_shortlist(
    config: DistillConfig,
    *,
    topic: str,
    query: str,
    expansion_queries: list[str],
    router_config: RouterConfig,
    ranked: list[RankedPaper],
    search_receipts: tuple[SearchReceipt, ...] = (),
):
    from distill.pipeline.paper_shortlist import save_paper_shortlist

    return save_paper_shortlist(
        config,
        topic=topic,
        query=query,
        expansion_queries=expansion_queries,
        model=_analysis_model_label(router_config),
        ranked=ranked,
        search_receipts=search_receipts,
    )


def _run_paper_ingest(
    *,
    ranked: list[RankedPaper],
    query: str,
    topic_name: str,
    config: DistillConfig,
    router_config: RouterConfig,
    tracker: CostTracker,
    summary: RunSummary,
    lens: str,
    workers: int,
    concepts_flag: bool,
) -> None:
    if lens:
        _persist_lens(config, topic_name, query, lens)
    records = [item.paper for item in ranked]
    projected_cost = estimate_paper_workflow_cost(
        len(records),
        synthesis_calls=_paper_tail_calls(topic_name, config),
        router_config=router_config,
    )
    enforce_projected_workflow_budget(config, "papers", projected_cost)
    summary.estimated_cost = projected_cost
    _display_ranked_papers(ranked, title="Selected Papers")
    console.print()
    _papers_run_projection(
        len(records),
        synthesis_calls=_paper_tail_calls(topic_name, config),
        projected_cost=projected_cost,
        config=config,
        router_config=router_config,
    )
    console.print(f"[dim]Analyzing {len(records)} paper(s)[/dim]\n")
    completed = _analyze_paper_batch(
        records,
        topic=topic_name,
        config=config,
        tracker=tracker,
        router_config=router_config,
        workers=workers,
        summary=summary,
    )
    if completed == 0:
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)
    synthesis = synthesize_papers(topic_name, config, tracker=tracker)
    if synthesis:
        summary.add_output(
            find_artifact(config.topic_dir(topic_name), "paper_synthesis", identity=topic_name)
        )
    corpus_synth = synthesize_corpus(topic_name, config, tracker=tracker)
    if corpus_synth:
        summary.add_output(
            find_artifact(config.topic_dir(topic_name), "corpus_synthesis", identity=topic_name)
        )
    if concepts_flag:
        _run_concepts_after_ingest(topic_name, tracker=tracker)
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
    if any(issue.severity == "error" for issue in summary.issues):
        raise typer.Exit(1)


def _ingest_saved_shortlist(
    config: DistillConfig,
    *,
    topic: str,
    shortlist_id: str,
    limit: int,
    lens: str,
    workers: int,
    concepts_flag: bool,
) -> None:
    loaded = _load_saved_shortlist(config, topic, shortlist_id)
    topic_name = topic or loaded.topic
    _require_model()
    router_config = RouterConfig()
    tracker = budgeted_cost_tracker(config, "papers")
    summary = RunSummary(command="papers")
    summary.set_metadata(topic=topic_name, workflow="papers", source_type="paper")
    chosen = list(loaded.papers[: max(limit, 0)])
    from distill.library.ingested import ingested_source_ids
    from distill.pipeline.discovery import filter_ingested_candidates

    score_by_id = dict(
        zip((paper.paper_id for paper in loaded.papers), loaded.scores, strict=False)
    )
    chosen, _, _ = filter_ingested_candidates(
        chosen, [], ingested=ingested_source_ids(config.topic_dir(topic_name))
    )
    scores = [score_by_id.get(paper.paper_id, 0.0) for paper in chosen]
    console.print(f"\n[bold]Papers: {loaded.query}[/bold]")
    console.print(
        f"[dim]Topic: {topic_name} | Shortlist: {loaded.id} | "
        f"Limit: {limit} | Workers: {workers}[/dim]\n"
    )
    console.print("[dim]Using the saved preview. No arXiv search and no rerank.[/dim]")
    report_search_coverage(loaded.search_receipts, summary)
    if report_revision_candidates(chosen, topic_dir=config.topic_dir(topic_name)):
        console.print(
            "Revision publication requires a reviewed history-preserving update; corpus unchanged."
        )
        raise typer.Exit(1)
    if not chosen:
        summary.add_issue(
            "paper-search", "Saved shortlist is empty at this limit", context=loaded.id
        )
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)
    ranked = [
        RankedPaper(
            paper=paper,
            final_score=scores[index] if index < len(scores) else 0.0,
            relevance_score=scores[index] if index < len(scores) else 0.0,
            depth_score=0.0,
            novelty_score=0.0,
            credibility_score=0.0,
            rationale="saved preview",
            selected_by="shortlist",
        )
        for index, paper in enumerate(chosen)
    ]
    _run_paper_ingest(
        ranked=ranked,
        query=loaded.query,
        topic_name=topic_name,
        config=config,
        router_config=router_config,
        tracker=tracker,
        summary=summary,
        lens=lens,
        workers=workers,
        concepts_flag=concepts_flag,
    )


def _load_saved_shortlist(config: DistillConfig, topic: str, shortlist_id: str):
    from distill.pipeline.paper_shortlist import (
        PaperShortlist,
        PaperShortlistError,
        load_library_last,
        load_topic_latest,
        load_topic_shortlist,
    )

    try:
        loaded: PaperShortlist
        if shortlist_id:
            if topic:
                loaded = load_topic_shortlist(config, topic, shortlist_id)
            else:
                loaded = load_library_last(config)
                if loaded.id != shortlist_id:
                    raise PaperShortlistError(
                        "Pass --topic to load that shortlist. "
                        "The library's last preview has a different id."
                    )
        elif topic:
            loaded = load_topic_latest(config, topic)
        else:
            loaded = load_library_last(config)
        return loaded
    except PaperShortlistError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def papers(  # noqa: C901 — legacy, will refactor
    query: str | None = typer.Argument(
        None,
        help="Paper topic query. Omit with --from-shortlist or --run-last-preview.",
    ),
    topic: str = typer.Option("", "--topic", "-t", help="Topic to file under"),
    limit: int = typer.Option(10, "--limit", "-n", help="How many papers to analyze"),
    sort: str = typer.Option(
        "relevance",
        "--sort",
        help="Candidate order from arXiv: relevance or date",
    ),
    expand: bool = typer.Option(
        True,
        "--expand/--no-expand",
        help="Expand the query into multiple arXiv searches (default: on)",
    ),
    rerank: bool = typer.Option(
        True,
        "--rerank/--no-rerank",
        help="Use LLM reranking to pick the best papers (default: on)",
    ),
    rigor: str = typer.Option(
        "off",
        "--rigor",
        help="Quality bar on the rerank score: strict | balanced | loose | off (default off). "
        "Drops candidates below the per-source threshold before the --limit cap; needs --rerank.",
    ),
    lens: str = typer.Option(
        "",
        "--lens",
        help="Analysis lens for per-source insights: research | practitioner | competitive | "
        "academic | general. Persists as the topic's intent so later ingests inherit it. "
        "Default: the topic's saved intent, else neutral 'general'.",
    ),
    verify: str = typer.Option(
        "",
        "--verify",
        help="Claim-grounding mode for this run: warn | strict | off "
        "(default: the DISTILL_VERIFY setting, else warn).",
    ),
    preview: bool = typer.Option(
        False,
        "--preview",
        help="Preview the selected set without processing it",
    ),
    concepts_flag: bool = typer.Option(
        False,
        "--concepts",
        help="Run the concept playbook extraction over the topic after ingest succeeds",
    ),
    workers: int = typer.Option(
        1,
        "--workers",
        min=1,
        max=MAX_INGEST_WORKERS,
        help="Concurrent independent paper analyses (1-3; default 1 for conservative spend).",
    ),
    from_shortlist: str = typer.Option(
        "",
        "--from-shortlist",
        help="Ingest a saved preview shortlist id instead of searching again",
    ),
    run_last_preview: bool = typer.Option(
        False,
        "--run-last-preview",
        help="Ingest the latest saved paper preview",
    ),
):
    """Search arXiv and ingest a paper set into the topic corpus."""
    from distill.pipeline.discovery import RIGOR_LEVELS_WITH_OFF

    if from_shortlist and run_last_preview:
        _papers_usage("Pass only one of --from-shortlist or --run-last-preview.")
    if preview and (from_shortlist or run_last_preview):
        _papers_usage("--preview cannot be combined with a saved shortlist.")
    if query is None and not from_shortlist and not run_last_preview:
        _papers_usage("Pass a query, --from-shortlist, or --run-last-preview.")
    if sort not in {"relevance", "date"}:
        console.print("[red]--sort must be 'relevance' or 'date'[/red]")
        raise typer.Exit(1)
    if rigor not in RIGOR_LEVELS_WITH_OFF:
        console.print(
            f"[red]Unknown --rigor '{rigor}'.[/red] Choose: {', '.join(RIGOR_LEVELS_WITH_OFF)}."
        )
        raise typer.Exit(1)
    _apply_verify_override(verify)

    config = get_config()
    if from_shortlist or run_last_preview:
        _ingest_saved_shortlist(
            config,
            topic=topic,
            shortlist_id=from_shortlist,
            limit=limit,
            lens=lens,
            workers=workers,
            concepts_flag=concepts_flag,
        )
        return
    assert query is not None
    topic_name = topic or _topic_from_query(query)
    router_config = RouterConfig()
    if not preview:
        projected_limit_cost = estimate_paper_workflow_cost(
            max(0, limit),
            synthesis_calls=_paper_tail_calls(topic_name, config),
            router_config=router_config,
        )
        enforce_projected_workflow_budget(config, "papers", projected_limit_cost)
    if not preview:
        _require_model()
    tracker = budgeted_cost_tracker(config, "papers")
    summary = RunSummary(command="papers")
    summary.set_metadata(topic=topic_name, workflow="papers", source_type="paper")

    console.print(f"\n[bold]Papers: {query}[/bold]")
    console.print(
        f"[dim]Topic: {topic_name} | Sort: {sort} | Expand: {'on' if expand else 'off'} "
        f"| Rerank: {'on' if rerank else 'off'} | Limit: {limit} | Workers: {workers}[/dim]\n"
    )

    queries = _expanded_paper_queries(
        query,
        config=config,
        tracker=tracker,
        expand=expand,
        limit=limit,
        preview=preview,
    )
    if preview:
        console.print(
            f"[dim]Planned arXiv searches: {len(queries)} "
            "(spaced at the documented 3 second minimum).[/dim]"
        )
    for idx, variant in enumerate(queries, 1):
        console.print(f"[dim]Candidate search {idx}/{len(queries)}: {variant}[/dim]")

    # Pull 2x limit per query so reranking has meaningful candidate pool, but
    # cap per-query to keep arXiv requests polite.
    per_query_cap = max(limit, 10)
    try:
        if len(queries) > 1:
            candidates = search_arxiv_multi(queries, limit_per_query=per_query_cap, sort=sort)
        else:
            candidates = search_arxiv_papers(queries[0], limit=per_query_cap, sort=sort)
    except Exception as exc:
        console.print(
            f"[red]arXiv search failed: {exc}[/red]\n"
            "[dim]Discovery failed; no conclusion about corpus currency is available.[/dim]"
        )
        summary.add_issue("paper-search", f"arXiv request failed: {exc}", context=query)
        report_search_coverage((SearchReceipt.capture(queries[0], 0, error=str(exc)),), summary)
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1) from exc

    search_receipts = candidates.receipts if isinstance(candidates, PaperSearchResults) else ()
    report_search_coverage(search_receipts, summary)
    if not candidates:
        summary.add_issue("paper-search", "No papers found for query", context=query)
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)

    # Corpus-aware dedup: skip papers the topic already has (version-insensitive,
    # so an ingested v1 blocks the v2 search hit) before paying for the rerank.
    from distill.library.ingested import ingested_source_ids
    from distill.pipeline.discovery import filter_ingested_candidates

    candidates, _, excluded_ingested = filter_ingested_candidates(
        candidates, [], ingested=ingested_source_ids(config.topic_dir(topic_name))
    )
    if (
        report_revision_candidates(candidates, topic_dir=config.topic_dir(topic_name))
        and not preview
    ):
        console.print(
            "Review revisions with --preview; automatic revision publication is unavailable."
        )
        raise typer.Exit(1)
    if excluded_ingested:
        console.print(
            f"[dim]Excluded {excluded_ingested} paper(s) already in '{topic_name}'.[/dim]"
        )
    if not candidates:
        # Every search hit is already ingested -- a converged corpus, not an error.
        console.print(
            f"[dim]Every returned paper is already in '{topic_name}'; "
            "this does not certify corpus currency.[/dim]"
        )
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        return

    console.print(
        f"[dim]Found {len(candidates)} candidate paper(s) across {len(queries)} search(es)[/dim]\n"
    )

    ranked = _rank_for_run(
        query,
        candidates,
        config,
        tracker,
        limit=limit,
        rerank=rerank,
        rigor=rigor,
        preview=preview,
    )
    ranked = _apply_source_rigor(ranked, source="paper", rigor=rigor, rerank_on=rerank, limit=limit)
    ranked = ranked[: max(limit, 0)]

    if preview:
        _display_ranked_papers(ranked, title="Paper Best-Pick Learning Set")
        saved = _save_preview_shortlist(
            config,
            topic=topic_name,
            query=query,
            expansion_queries=queries,
            router_config=router_config,
            ranked=ranked,
            search_receipts=search_receipts,
        )
        projected_cost = estimate_paper_workflow_cost(
            len(ranked),
            synthesis_calls=_paper_tail_calls(topic_name, config),
            router_config=router_config,
        )
        console.print()
        _papers_run_projection(
            len(ranked),
            synthesis_calls=_paper_tail_calls(topic_name, config),
            projected_cost=projected_cost,
            config=config,
            router_config=router_config,
        )
        console.print(
            f"[dim]Saved shortlist {saved.id}. Ingest this exact set with "
            f"`distill papers --from-shortlist {saved.id} --topic {topic_name}`.[/dim]"
        )
        console.print("[dim]Or rerun it with `distill papers --run-last-preview`.[/dim]")
        display_summary(
            summary,
            cost_tracker=tracker,
            console=console,
            log_dir=config.library_dir,
            preview=True,
        )
        return

    _run_paper_ingest(
        ranked=ranked,
        query=query,
        topic_name=topic_name,
        config=config,
        router_config=router_config,
        tracker=tracker,
        summary=summary,
        lens=lens,
        workers=workers,
        concepts_flag=concepts_flag,
    )


def register(app: typer.Typer) -> None:
    """Attach the paper ingestion commands to the app (called from distill.cli)."""
    app.command(rich_help_panel="Discover")(paper)
    app.command(rich_help_panel="Discover")(papers)
