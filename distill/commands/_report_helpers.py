# pyright: strict
"""Report command helpers kept out of the shared command helper module."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from contextlib import suppress

from distill._console import console
from distill.config import DistillConfig
from distill.pipeline.costs import (
    BudgetExceededError,
    CostTracker,
    estimate_routed_video_workflow_cost,
    save_run_log,
)
from distill.pipeline.summary import RunSummary


def run_scope_report(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker,
    scope: str,
    channel_name: str | None = None,
    test: bool = False,
    summary: RunSummary | None = None,
    focus: str | None = None,
) -> None:
    if not config.gemini_api_key:
        message = "GEMINI_API_KEY required for report generation -- skipping"
        console.print(f"[yellow]{message}[/yellow]")
        if summary is not None:
            summary.add_issue("report", message, context=topic, severity="warning")
        return

    console.print("\n[bold cyan]Generating report...[/bold cyan]")
    from distill.commands import _helpers as helpers
    from distill.pipeline.report.accordion import run_accordion_research
    from distill.pipeline.report.deep_research import _get_report_path

    start_entry_count = len(tracker.entries)
    start_gemini_queries = tracker.gemini_queries
    report_metadata = {
        "topic": topic,
        "workflow": "report",
        "scope": scope,
        "channel": channel_name or "",
    }

    result = _run_accordion_report_with_budget_log(
        topic=topic,
        config=config,
        scope=scope,
        channel_name=channel_name,
        test=test,
        tracker=tracker,
        focus=focus,
        summary=summary,
        start_entry_count=start_entry_count,
        start_gemini_queries=start_gemini_queries,
        metadata=report_metadata,
        run_accordion_research=run_accordion_research,
    )

    if not result:
        message = "Research did not produce results"
        console.print(f"[red]{message}[/red]")
        if summary is not None:
            summary.add_issue(
                "report",
                message,
                context=topic,
                details={"scope": scope, "channel": channel_name or ""},
            )
        _log_report_cost_delta(
            config,
            tracker,
            start_entry_count=start_entry_count,
            start_gemini_queries=start_gemini_queries,
            metadata=report_metadata,
        )
        return

    console.print("\n[bold green]Report complete![/bold green]")
    console.print(f"[dim]{len(result.split()):,} words[/dim]")

    suffix = f"{topic}-{channel_name}" if channel_name else topic
    md_source = _get_report_path(topic, config, scope, channel_name)
    if summary is not None:
        helpers.record_output_or_issue(
            summary,
            md_source,
            stage="report",
            context=topic,
            details={"scope": scope, "channel": channel_name or ""},
            missing_message="Report markdown was not written",
        )
    if not md_source.exists():
        _log_report_cost_delta(
            config,
            tracker,
            start_entry_count=start_entry_count,
            start_gemini_queries=start_gemini_queries,
            metadata=report_metadata,
        )
        return

    md_out = helpers.output_path(config, f"report-{suffix}.md")
    shutil.copy2(md_source, md_out)
    console.print(f"[green]Markdown: {md_out}[/green]")
    if summary is not None:
        summary.add_output(md_out)

    docx_path = helpers.output_path(config, f"report-{suffix}.docx")

    try:
        from distill.library.export import export_report

        title = f"Strategic Intelligence: {channel_name or topic}"
        export_report(md_source, docx_path=docx_path, title=title)
        console.print(f"[green]DOCX:     {docx_path}[/green]")
        if summary is not None:
            summary.add_output(docx_path)
    except Exception as e:
        console.print(f"[yellow]DOCX export failed: {e}[/yellow]")
        helpers.record_exception_issue(
            summary,
            stage="report-docx",
            exc=e,
            context=topic,
            details={"scope": scope, "channel": channel_name or "", "output": str(docx_path)},
        )

    _log_report_cost_delta(
        config,
        tracker,
        start_entry_count=start_entry_count,
        start_gemini_queries=start_gemini_queries,
        metadata=report_metadata,
    )


def _run_accordion_report_with_budget_log(
    *,
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
    test: bool,
    tracker: CostTracker,
    focus: str | None,
    summary: RunSummary | None,
    start_entry_count: int,
    start_gemini_queries: int,
    metadata: dict[str, str],
    run_accordion_research: Callable[..., str | None],
) -> str | None:
    try:
        return run_accordion_research(
            topic=topic,
            config=config,
            scope=scope,
            channel_name=channel_name,
            test=test,
            tracker=tracker,
            focus=focus,
        )
    except BudgetExceededError as exc:
        if summary is not None:
            summary.add_issue("report-budget", str(exc), context=topic)
        if not getattr(tracker, "budget_failure_logged", False):
            _log_report_cost_delta(
                config,
                tracker,
                start_entry_count=start_entry_count,
                start_gemini_queries=start_gemini_queries,
                metadata=metadata,
            )
        raise


def _log_report_cost_delta(
    config: DistillConfig,
    tracker: CostTracker,
    *,
    start_entry_count: int,
    start_gemini_queries: int,
    metadata: dict[str, str],
) -> None:
    report_tracker = CostTracker(
        entries=list(tracker.entries[start_entry_count:]),
        gemini_queries=max(tracker.gemini_queries - start_gemini_queries, 0),
    )
    if not report_tracker.entries and not report_tracker.gemini_queries:
        return
    with suppress(Exception):
        save_run_log(
            config.library_dir,
            "report",
            report_tracker,
            estimated_cost=estimate_routed_video_workflow_cost(include_report=True),
            metadata=metadata,
        )
