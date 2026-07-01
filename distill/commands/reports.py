# pyright: strict
"""The `distill report` + `distill export` commands.

report runs the 4-phase Deep Research pipeline into a topic/channel report;
export packages a topic into a Word document or a portable corpus zip (the
deepr/bundle formats). Reports-panel verbs. Registered via register() from
distill.cli.
"""

from __future__ import annotations

from pathlib import Path

import typer

from distill._console import console
from distill.cli_shared import output_path as _output_path
from distill.commands._helpers import (
    _complete_topics,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
)
from distill.commands._topic_resolution import (
    resolve_required_topic_for_channel as _resolve_required_topic_for_channel,
)
from distill.commands.topic import (
    _collect_topic_bundle_files,
    _export_topic_bundle,
)
from distill.config import DistillConfig
from distill.library import Library
from distill.library.citations import collect_paper_citations, render_citations
from distill.library.export import markdown_to_docx
from distill.library.okf import export_okf_bundle
from distill.library.paths import find_artifact
from distill.pipeline.costs import report_deep_research_estimate
from distill.pipeline.report.deep_research import run_deep_research
from distill.pipeline.summary import RunSummary, display_summary

__all__ = ["export", "register", "report"]


def _export_okf_bundle_cli(config: DistillConfig, topic: str) -> None:
    try:
        result = export_okf_bundle(config, topic)
    except FileNotFoundError:
        console.print(f"[yellow]Topic not found: {topic}[/yellow]")
        raise typer.Exit(1) from None
    if not result.validation.ok:
        console.print(f"[red]OKF export failed validation: {result.output_dir}[/red]")
        for issue in result.validation.errors:
            console.print(f"  [dim]{issue.path}[/dim]: {issue.message}")
        raise typer.Exit(1)
    console.print(f"[green]Exported OKF bundle: {result.output_dir}[/green]")
    console.print(f"[dim]{result.files_written} files written[/dim]")
    if result.validation.warnings:
        console.print(f"[yellow]{len(result.validation.warnings)} OKF warning(s)[/yellow]")
    console.print(f"\n  [dim]distill okf validate {result.output_dir}[/dim]")


def _export_zip_bundle_cli(config: DistillConfig, topic: str, bundle_format: str) -> None:
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        console.print(f"[yellow]Topic not found: {topic}[/yellow]")
        raise typer.Exit(1)
    files = _collect_topic_bundle_files(config, topic)
    if not files:
        console.print(f"[yellow]No exportable corpus files found for topic: {topic}[/yellow]")
        raise typer.Exit(1)
    zip_path = _export_topic_bundle(config, topic, bundle_format)
    console.print(f"[green]Exported bundle: {zip_path}[/green]")
    console.print(f"[dim]{zip_path.stat().st_size / 1024:.1f} KB[/dim]")
    console.print(f"\n  [dim]distill open {topic}  to inspect the source corpus[/dim]")


def _export_citations_cli(config: DistillConfig, topic: str, export_format: str) -> None:
    normalized_format = "bibtex" if export_format == "bundle" else export_format
    try:
        content = render_citations(collect_paper_citations(config, topic), normalized_format)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from None
    if not content:
        console.print(f"[yellow]No paper citations found for topic: {topic}[/yellow]")
        raise typer.Exit(1)
    extension = "ris" if normalized_format.strip().lower() == "ris" else "bib"
    citation_path = _output_path(config, f"citations-{topic}.{extension}")
    citation_path.write_text(content, encoding="utf-8")
    console.print(f"[green]Exported citations: {citation_path}[/green]")
    console.print(f"[dim]{len(content.splitlines())} lines[/dim]")


def _export_markdown_source(
    config: DistillConfig,
    topic: str,
    channel: str | None,
    what: str,
) -> tuple[Path, str]:
    if what == "report":
        if channel:
            return (
                find_artifact(
                    config.channel_dir(topic, channel), "report", identity=f"{topic}_{channel}"
                ),
                f"Report: {channel}",
            )
        return find_artifact(
            config.topic_dir(topic), "report", identity=topic
        ), f"Strategic Intelligence: {topic}"

    if what == "synthesis":
        if channel:
            return (
                find_artifact(
                    config.channel_dir(topic, channel),
                    "synthesis",
                    identity=f"{topic}_{channel}",
                ),
                f"Channel Synthesis: {channel}",
            )
        return find_artifact(
            config.topic_dir(topic), "topic_synthesis", identity=topic
        ), f"Topic Synthesis: {topic}"

    console.print(
        f"[red]Unknown export type: {what}. Use: report, synthesis, bundle, citations[/red]"
    )
    raise typer.Exit(1)


def report(  # noqa: C901 - legacy, will refactor
    topic: str = typer.Argument(None, help="Topic or channel name"),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Report on a single channel"),
    all_topics: bool = typer.Option(False, "--all", help="Report on entire library"),
    focus: str | None = typer.Option(None, "--focus", "-f", help="Custom research focus"),
    test: bool = typer.Option(False, "--test", "-t", help="Test mode (cheaper, faster)"),
    legacy: bool = typer.Option(
        False, "--legacy", help="Use single-shot Deep Research (no section writing)"
    ),
    research_only: bool = typer.Option(
        False,
        "--research-only",
        help="Run Phase 1 only (raw research, no section writing)",
    ),
    sections_filter: str | None = typer.Option(
        None, "--sections", "-s", help="Comma-separated section IDs to write"
    ),
    no_qa: bool = typer.Option(False, "--no-qa", help="Skip QA review phase"),
):
    """Generate a strategic intelligence report.

    Default: 4-phase (research + section writing + assembly + QA review).
    Use --legacy for single-shot Deep Research.
    Use --research-only to run only Phase 1.
    Use --no-qa to skip the QA review.

    Examples:
      distill report ai
      distill report ai --focus "migration risks"
      distill report ai --research-only
    """
    config = get_config()
    if topic:
        lib = Library(config)
        topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)

    if not config.gemini_api_key:
        console.print("[red]GEMINI_API_KEY required for deep research[/red]")
        console.print("[dim]Get one at: https://aistudio.google.com/apikey[/dim]")
        raise typer.Exit(1)

    if not topic and not all_topics:
        console.print("[red]Specify a topic or use --all[/red]")
        raise typer.Exit(1)

    scope = "all" if all_topics else ("channel" if channel else "topic")
    scope_label = (
        "entire library"
        if all_topics
        else (f"channel: {channel}" if channel else f"topic: {topic}")
    )
    method = "Legacy (single-shot)" if legacy else "Accordion (4-phase)"

    projected_cost = report_deep_research_estimate(
        include_section_writing=not (legacy or research_only)
    )
    enforce_projected_workflow_budget(config, "report", projected_cost)

    tracker = budgeted_cost_tracker(config, "report")
    summary = RunSummary(command="report")
    summary.estimated_cost = projected_cost
    if topic:
        summary.set_metadata(topic=topic, workflow="report")
    elif all_topics:
        summary.set_metadata(topic="all", workflow="report")

    console.print(f"\n[bold]Report: {scope_label}[/bold]")
    console.print(f"[dim]Method: {method}[/dim]")
    if test:
        console.print("[yellow]Test mode -- truncated corpus, faster/cheaper[/yellow]")
    if focus:
        console.print(f"[dim]Focus: {focus}[/dim]")

    if legacy:
        # Original single-shot deep research
        result = run_deep_research(
            topic=topic or "all",
            config=config,
            scope=scope,
            channel_name=channel,
            focus=focus,
            test=test,
            tracker=tracker,
        )
    else:
        # Accordion method
        from distill.pipeline.report.accordion import run_accordion_research

        filter_list = [s.strip() for s in sections_filter.split(",")] if sections_filter else None

        result = run_accordion_research(
            topic=topic or "all",
            config=config,
            scope=scope,
            channel_name=channel,
            focus=focus,
            test=test,
            dossier_only=research_only,
            sections=filter_list,
            tracker=tracker,
            skip_qa=no_qa,
        )

    if result:
        console.print("\n[bold green]Report complete![/bold green]")
        console.print(
            f"[dim]Output: {len(result):,} characters ({len(result.split()):,} words)[/dim]"
        )

        # Export both MD and DOCX to output/
        import shutil

        from distill.pipeline.report.deep_research import _get_report_path

        md_source = _get_report_path(topic or "all", config, scope, channel)
        summary.add_output(md_source)

        if md_source.exists() and not research_only:
            # Build output filename with channel if scoped
            name_parts = [topic or "all"]
            if channel:
                name_parts.append(channel)
            base_name = "-".join(name_parts)

            # Copy markdown to output/
            md_out = _output_path(config, f"report-{base_name}.md")
            shutil.copy2(md_source, md_out)
            console.print(f"[green]Markdown: {md_out}[/green]")
            summary.add_output(md_out)

            # Export DOCX to output/
            try:
                from distill.library.export import export_report

                docx_path = _output_path(config, f"report-{base_name}.docx")
                export_report(
                    md_source,
                    docx_path=docx_path,
                    title=f"Strategic Intelligence: {(topic or 'all').upper()}",
                )
                console.print(f"[green]DOCX:     {docx_path}[/green]")
                summary.add_output(docx_path)
            except Exception:
                try:
                    docx_path = _output_path(config, f"report-{base_name}.docx")
                    markdown_to_docx(
                        md_source,
                        docx_path=docx_path,
                        title=f"Strategic Intelligence: {topic or 'all'}",
                    )
                    console.print(f"[green]DOCX (basic): {docx_path}[/green]")
                    summary.add_output(docx_path)
                except Exception as e2:
                    console.print(f"[yellow]DOCX export failed: {e2}[/yellow]")

    if not result:
        summary.add_issue(
            "report",
            "Research did not produce results",
            context=topic or "all",
            details={"scope": scope, "channel": channel or "", "research_only": research_only},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    if result:
        ch_flag = f" -c {channel}" if channel else ""
        console.print("\n  [dim]What's next:[/dim]")
        console.print(
            f"  [dim]  distill findings {topic or 'all'}{ch_flag}              Read the report in terminal[/dim]"
        )
        console.print(
            f"  [dim]  distill export {topic or 'all'}{ch_flag}                Export to DOCX[/dim]"
        )
        console.print(
            f"  [dim]  distill open {topic or 'all'}                          Open output folder[/dim]"
        )

    if not result:
        raise typer.Exit(1)


def export(
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    what: str = typer.Option(
        "report", "--what", "-w", help="What to export: report, synthesis, bundle, citations"
    ),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Specific channel"),
    bundle_format: str = typer.Option(
        "bundle", "--format", help="Bundle or citation format: bundle, deepr, okf, bibtex, ris"
    ),
):
    """Export reports, syntheses, or a portable topic corpus bundle.

    Examples:
      distill export ai
      distill export ai --what synthesis
      distill export ai --what bundle --format okf
      distill export ai --what citations --format bibtex
    """
    config = get_config()
    lib = Library(config)
    if bundle_format == "okf" and what == "report":
        what = "bundle"
    if not (
        (what == "bundle" and bundle_format == "okf" and topic.lower() == "all")
        or (what == "citations" and topic.lower() == "all")
    ):
        topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)

    if what == "bundle":
        if bundle_format == "okf":
            _export_okf_bundle_cli(config, topic)
        else:
            _export_zip_bundle_cli(config, topic, bundle_format)
        return

    if what == "citations":
        if channel:
            console.print("[red]Citation export is topic-level. Omit --channel.[/red]")
            raise typer.Exit(1)
        _export_citations_cli(config, topic, bundle_format)
        return

    md_path, title = _export_markdown_source(config, topic, channel, what)

    if not md_path.exists():
        console.print(f"[yellow]File not found: {md_path}[/yellow]")
        console.print("[dim]Run the appropriate command first to generate it.[/dim]")
        raise typer.Exit(1)

    # Build output filename from what + topic/channel
    out_name = f"{what}-{topic}-{channel}.docx" if channel else f"{what}-{topic}.docx"
    docx_path = _output_path(config, out_name)

    markdown_to_docx(md_path, docx_path=docx_path, title=title)
    console.print(f"[green]Exported: {docx_path}[/green]")
    console.print(f"[dim]{docx_path.stat().st_size / 1024:.1f} KB[/dim]")
    console.print(f"\n  [dim]distill open {topic}  to open the output folder[/dim]")


def register(app: typer.Typer) -> None:
    """Attach the report + export commands to the app (called from distill.cli)."""
    app.command(rich_help_panel="Reports")(report)
    app.command(rich_help_panel="Reports")(export)
