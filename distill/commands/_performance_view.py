# pyright: strict
"""Narrow Rich rendering for correlated performance evidence."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.table import Table

from distill.pipeline.performance_history import (
    PerformanceCoverage,
    PerformanceEvidence,
    PerformanceRun,
    PerformanceWorkflow,
)


def _seconds(value: float) -> str:
    if value >= 60:
        return f"{int(value // 60)}m {value % 60:.1f}s"
    if 0 < value < 0.1:
        return f"{value:.3f}s"
    return f"{value:.1f}s"


def _bytes(value: int | None) -> str:
    if value is None:
        return "-"
    if value < 1024:
        return f"{value} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KB"
    if value < 1024**3:
        return f"{value / 1024**2:.1f} MB"
    return f"{value / 1024**3:.1f} GB"


def _cost(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:.4f}" if value < 0.01 else f"${value:.2f}"


def _workflow_line(workflow: PerformanceWorkflow | None, *, phases_complete: bool) -> str:
    if workflow is None:
        return (
            "workflow evidence incomplete" if not phases_complete else "workflow artifacts unknown"
        )
    line = (
        f"{workflow['phase']} ({workflow['outcome']}) | "
        f"artifacts {workflow['artifact_count']} / {_bytes(workflow['byte_count'])}"
    )
    return f"{line} | phase evidence incomplete" if not phases_complete else line


def _provider_line(run: PerformanceRun) -> str:
    count = run["provider_call_count"]
    seconds = run["provider_call_seconds_cumulative"]
    if not run["provider_complete"] or count is None or seconds is None:
        return "provider evidence incomplete"
    return f"provider {count} calls / {_seconds(seconds)} cumulative"


def _cost_line(run: PerformanceRun) -> str:
    if not run["cost_complete"] or run["cost_row_count"] is None:
        return "cost evidence incomplete"
    return f"cost {_cost(run['actual_cost_usd'])}"


def _runs_table(runs: list[PerformanceRun], console: Console) -> None:
    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("Run", style="dim", no_wrap=True)
    table.add_column("Evidence")
    for run in runs:
        envelope = run["command_envelope"]
        table.add_row(
            (
                f"{envelope['timestamp'][:16].replace('T', ' ') or '-'}\n"
                f"{run['command'] or '-'} ({envelope['outcome'] or '-'})\n"
                f"{run['run_id'][:8]}"
            ),
            (
                f"wall {_seconds(envelope['wall_seconds'])} | "
                f"process CPU {_seconds(envelope['process_cpu_seconds'])}\n"
                f"process peak {_bytes(envelope['process_peak_rss_bytes'])}\n"
                f"{_workflow_line(run['workflow'], phases_complete=run['phases_complete'])}\n"
                f"{_provider_line(run)} | {_cost_line(run)}"
            ),
        )
    console.print(table)
    console.print(
        "[dim]* Provider time is cumulative call time, not critical-path wall time. "
        "Process peak RSS is the process high-water mark, not phase-attributed memory.\n"
        "Process CPU can include concurrent MCP work and excludes child-process CPU. "
        "Artifact counts come only from a recorded workflow summary. Any schema-invalid "
        "row carrying a run ID makes that run's affected rollup incomplete.[/dim]"
    )


def _coverage(coverage: PerformanceCoverage, console: Console) -> None:
    console.print(
        "[dim]Correlation: "
        f"{coverage['correlated_runs_total']} command run(s); joined "
        f"{coverage['phase_rows_joined']}/{coverage['phase_rows_total']} phase, "
        f"{coverage['provider_rows_joined']}/{coverage['provider_rows_total']} provider, and "
        f"{coverage['cost_rows_joined']}/{coverage['cost_rows_total']} cost row(s) by exact "
        "run_id.[/dim]"
    )
    if coverage["excluded_observer_runs"]:
        console.print(
            f"[dim]Excluded observer runs: {coverage['excluded_observer_runs']} `costs` "
            "command anchor(s).[/dim]"
        )

    legacy = (
        coverage["legacy_unjoinable_phase_rows"],
        coverage["legacy_unjoinable_provider_rows"],
        coverage["legacy_unjoinable_cost_rows"],
    )
    if any(legacy):
        console.print(
            "[dim]Legacy unjoinable rows: "
            f"{legacy[0]} phase, {legacy[1]} provider, {legacy[2]} cost. "
            "Their run IDs are absent; timestamp backfill is never attempted.[/dim]"
        )

    unanchored = (
        coverage["unanchored_phase_rows"],
        coverage["unanchored_provider_rows"],
        coverage["unanchored_cost_rows"],
    )
    if any(unanchored):
        console.print(
            "[dim]Rows with IDs but no command anchor: "
            f"{unanchored[0]} phase, {unanchored[1]} provider, "
            f"{unanchored[2]} cost.[/dim]"
        )

    malformed = (
        coverage["malformed_phase_rows"],
        coverage["malformed_provider_rows"],
        coverage["malformed_cost_rows"],
    )
    if any(malformed):
        console.print(
            "[dim]Skipped malformed or schema-invalid rows: "
            f"{malformed[0]} phase, {malformed[1]} provider, "
            f"{malformed[2]} cost.[/dim]"
        )
    if coverage["unreadable_logs"]:
        console.print(
            f"[dim]Unreadable telemetry logs: {', '.join(coverage['unreadable_logs'])}.[/dim]"
        )
    if coverage["tail_limited_logs"]:
        console.print(
            "[dim]Tail-limited telemetry logs: "
            f"{', '.join(coverage['tail_limited_logs'])}. Counts cover retained rows only; "
            "older rows were excluded and affected rollups fail closed.[/dim]"
        )


def _latest_phases(evidence: PerformanceEvidence, console: Console) -> None:
    latest = evidence["runs"][0]
    nested_phases = evidence["latest_nested_phases"]
    if not latest["phases_complete"]:
        console.print(
            f"[dim]Latest run {latest['run_id'][:8]} has incomplete phase evidence; "
            "valid rows shown below are a subset.[/dim]"
        )
    if not nested_phases:
        if latest["phases_complete"]:
            console.print(
                f"[dim]Latest run {latest['run_id'][:8]} has no nested phase rows yet.[/dim]"
            )
        return

    nested = Table(
        title=f"Latest nested phases: {latest['command']} ({latest['run_id'][:8]})",
        box=box.SIMPLE,
        show_header=True,
    )
    nested.add_column("Phase", no_wrap=True)
    nested.add_column("Evidence")
    for phase in nested_phases:
        nested.add_row(
            f"{phase['phase']}\n{phase['wait_class']} ({phase['outcome']})",
            (
                f"wall {_seconds(phase['wall_seconds'])} | "
                f"process CPU {_seconds(phase['process_cpu_seconds'])}\n"
                f"artifacts {phase['artifact_count']} / {_bytes(phase['byte_count'])}"
            ),
        )
    console.print(nested)


def render_performance_evidence(evidence: PerformanceEvidence, console: Console) -> None:
    """Render correlated evidence without inventing timing or artifact attribution."""
    runs = evidence["runs"]
    coverage = evidence["coverage"]
    console.print()
    console.print("[bold]Performance Evidence[/bold]")
    if runs:
        _runs_table(runs, console)
    elif coverage["correlated_runs_total"] > coverage["excluded_observer_runs"]:
        console.print("[dim]No recent non-observer command-phase rows selected.[/dim]")
    elif coverage["excluded_observer_runs"]:
        console.print("[dim]Only excluded `costs` observer command anchors are present.[/dim]")
    else:
        console.print("[dim]No correlated command-phase evidence yet.[/dim]")
    _coverage(coverage, console)
    if runs:
        _latest_phases(evidence, console)


__all__ = ["render_performance_evidence"]
