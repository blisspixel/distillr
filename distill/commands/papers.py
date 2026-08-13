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
from distill.commands._learning import (
    apply_source_rigor,
    display_ranked_papers,
    expand_paper_queries,
)
from distill.commands._paper_artifacts import write_paper_artifacts as _write_paper_artifacts
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import (
    PaperRecord,
    fetch_arxiv_paper,
    search_arxiv_multi,
    search_arxiv_papers,
)
from distill.library.intent import CorpusIntent
from distill.library.paths import find_artifact
from distill.llm.availability import model_available
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.concurrency import (
    MAX_INGEST_WORKERS,
    BoundedTaskResult,
    iter_bounded,
)
from distill.pipeline.costs import BudgetExceededError, CostTracker, estimate_paper_workflow_cost
from distill.pipeline.ranking import rerank_papers
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
) -> None:
    """Analyze independent papers concurrently and serialize all shared writes."""

    intent: CorpusIntent | None = _resolve_intent(config, topic)
    item_estimate = estimate_paper_workflow_cost(
        1,
        synthesis_calls=0,
        router_config=router_config,
    )
    progress = BatchProgress("paper", len(records), tracker)
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
        except (OSError, json.JSONDecodeError):
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
    _require_model()
    insights, document = analyze_paper(
        paper_record,
        config,
        tracker=tracker,
        intent=_resolve_intent(config, topic),
    )
    paper_dir = _write_paper_artifacts(topic, paper_record, config, insights, document)
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


def papers(  # noqa: C901 — legacy, will refactor
    query: str = typer.Argument(help="Paper topic query for arXiv discovery"),
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
):
    """Search arXiv and ingest a paper set into the topic corpus."""
    from distill.pipeline.discovery import RIGOR_LEVELS_WITH_OFF

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
    topic_name = topic or _topic_from_query(query)
    router_config = RouterConfig()
    if not preview:
        projected_limit_cost = estimate_paper_workflow_cost(
            max(0, limit),
            synthesis_calls=_paper_tail_calls(topic_name, config),
            router_config=router_config,
        )
        enforce_projected_workflow_budget(config, "papers", projected_limit_cost)
    _require_model()
    tracker = budgeted_cost_tracker(config, "papers")
    if lens:
        _persist_lens(config, topic_name, query, lens)
    summary = RunSummary(command="papers")
    summary.set_metadata(topic=topic_name, workflow="papers", source_type="paper")

    console.print(f"\n[bold]Papers: {query}[/bold]")
    console.print(
        f"[dim]Topic: {topic_name} | Sort: {sort} | Expand: {'on' if expand else 'off'} "
        f"| Rerank: {'on' if rerank else 'off'} | Limit: {limit} | Workers: {workers}[/dim]\n"
    )

    queries = _expand_paper_queries(query, config=config, tracker=tracker, expand=expand)
    if not queries:
        queries = [query]
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
            "[dim]arXiv rate-limits aggressively. If you're seeing 429 errors, wait a few minutes and try again.[/dim]"
        )
        summary.add_issue("paper-search", f"arXiv request failed: {exc}", context=query)
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1) from exc

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
    if excluded_ingested:
        console.print(
            f"[dim]Excluded {excluded_ingested} paper(s) already in '{topic_name}'.[/dim]"
        )
    if not candidates:
        # Every search hit is already ingested -- a converged corpus, not an error.
        console.print(
            f"[green]Corpus is current: every paper found is already in '{topic_name}'.[/green]"
        )
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        return

    console.print(
        f"[dim]Found {len(candidates)} candidate paper(s) across {len(queries)} search(es)[/dim]\n"
    )

    # With a rigor bar, rerank the whole candidate pool so the threshold has
    # something to drop; otherwise keep the cheap top-N behavior.
    pool_n = len(candidates) if (rerank and rigor != "off") else limit
    ranked = rerank_papers(
        query,
        candidates,
        config,
        tracker=tracker,
        top_n=pool_n,
        use_llm=rerank,
    )
    if rerank and not model_available("rerank"):
        console.print(
            "[yellow]No model configured; used deterministic ranking fallback "
            "(set a cloud key or DISTILL_PROVIDER=ollama for LLM reranking)[/yellow]"
        )
    ranked = _apply_source_rigor(ranked, source="paper", rigor=rigor, rerank_on=rerank, limit=limit)

    if preview:
        _display_ranked_papers(ranked, title="Paper Best-Pick Learning Set")
        console.print("\n[dim]Run without `--preview` to process this set.[/dim]")
        display_summary(
            summary,
            cost_tracker=tracker,
            console=console,
            log_dir=config.library_dir,
            preview=True,
        )
        return

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

    console.print(f"[dim]Analyzing {len(records)} paper(s)[/dim]\n")
    _analyze_paper_batch(
        records,
        topic=topic_name,
        config=config,
        tracker=tracker,
        router_config=router_config,
        workers=workers,
        summary=summary,
    )

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


def register(app: typer.Typer) -> None:
    """Attach the paper ingestion commands to the app (called from distill.cli)."""
    app.command(rich_help_panel="Discover")(paper)
    app.command(rich_help_panel="Discover")(papers)
