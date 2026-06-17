"""arXiv paper ingestion commands, extracted from the _logic monolith.

`distill paper` (single arXiv paper) and `distill papers` (query-expanded,
LLM-reranked multi-paper ingest with cross-paper synthesis). The paper-writing
and shared concept/artifact helpers stay in _logic (used by the MCP papers tool
and other commands) and are imported back. Registered via register().
"""

from __future__ import annotations

import typer

import distill.cli_shared as cli_shared
from distill._console import console
from distill.cli_shared import require_model as _require_model
from distill.cli_shared import topic_from_query as _topic_from_query
from distill.commands._helpers import (
    _apply_verify_override,
    _persist_lens,
    _resolve_intent,
    get_config,
)
from distill.commands._learning import (
    _apply_source_rigor,
    _display_ranked_papers,
    _expand_paper_queries,
)
from distill.commands._logic import (
    _run_concepts_after_ingest,
    _write_paper_artifacts,
)
from distill.ingestors.papers.arxiv import (
    fetch_arxiv_paper,
    search_arxiv_multi,
    search_arxiv_papers,
)
from distill.library.paths import find_artifact
from distill.llm.availability import model_available
from distill.pipeline.analysis.paper import analyze_paper, synthesize_papers
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.ranking import rerank_papers
from distill.pipeline.summary import RunSummary, display_summary
from distill.pipeline.synthesis.corpus import synthesize_corpus

__all__ = ["paper", "papers", "register"]


def paper(
    target: str = typer.Argument(help="arXiv paper URL or paper ID"),
    topic: str = typer.Option("papers", "--topic", "-t", help="Topic to file under"),
):
    """Ingest and analyze a single arXiv paper."""
    config = get_config()
    _require_model()
    tracker = CostTracker()
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
    insights, document = analyze_paper(
        paper_record, config, tracker=tracker, intent=_resolve_intent(config, topic)
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
    _require_model()
    tracker = CostTracker()
    topic_name = topic or _topic_from_query(query)
    if lens:
        _persist_lens(config, topic_name, query, lens)
    summary = RunSummary(command="papers")
    summary.set_metadata(topic=topic_name, workflow="papers", source_type="paper")

    console.print(f"\n[bold]Papers: {query}[/bold]")
    console.print(
        f"[dim]Topic: {topic_name} | Sort: {sort} | Expand: {'on' if expand else 'off'} "
        f"| Rerank: {'on' if rerank else 'off'} | Limit: {limit}[/dim]\n"
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

    _display_ranked_papers(ranked, title="Selected Papers")
    console.print()

    records = [item.paper for item in ranked]
    console.print(f"[dim]Analyzing {len(records)} paper(s)[/dim]\n")
    for idx, record in enumerate(records, 1):
        console.print(f"  [{idx}/{len(records)}] [bold]{record.title}[/bold]")
        try:
            insights, document = analyze_paper(
                record, config, tracker=tracker, intent=_resolve_intent(config, topic_name)
            )
            paper_dir = _write_paper_artifacts(topic_name, record, config, insights, document)
        except BudgetExceededError:
            raise  # the spend cap is a hard stop, never a per-item issue
        except Exception as exc:
            console.print(f"  [red]failed: {exc}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="paper-analysis",
                exc=exc,
                context=record.title,
                details={"topic": topic_name, "paper_id": getattr(record, "paper_id", "")},
            )
            continue
        summary.add_output(find_artifact(paper_dir, "paper"))
        summary.add_output(find_artifact(paper_dir, "insights"))

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
