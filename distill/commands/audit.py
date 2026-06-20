"""``distill audit`` -- the self-maintaining health check, with a report artifact.

Composes the scattered health signals (``distill health`` warnings, contested
concepts, ``doctor --links`` integrity, ``research_gaps`` coverage, and the
0.10 verify sidecars) into one run that writes ``<topic>_Audit.md`` and, in
interactive mode, offers the safe follow-up actions. ``--report-only`` is the
scheduled/loop-friendly path: artifact out, exit code reflects findings, no
prompts. ``distill health`` remains as the fast console-only view.

Deterministic and free: no model calls anywhere in an audit run.
"""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from distill._console import console, set_json_mode
from distill.commands._helpers import _complete_topics, get_config, tty_prompt
from distill.commands._json import emit_json, json_mode_active, set_json_active
from distill.library import Library
from distill.pipeline.audit import (
    AuditReport,
    NextActionPlan,
    build_next_action_plan,
    collect_library_hygiene,
    collect_staleness,
    collect_synthesis_freshness,
    collect_verify_rollup,
    render_library_audit_md,
    write_audit_artifact,
)
from distill.pipeline.dedup import collect_near_duplicates

__all__ = ["audit_cmd", "register"]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_next_action_mode(json_output: bool, next_actions: bool) -> tuple[bool, bool]:
    """Return ``(next_actions, wants_json)`` and activate command-local JSON."""
    if json_output:
        set_json_mode(True)
        set_json_active(True)
    wants_json = json_output or json_mode_active()
    return next_actions or wants_json, wants_json


def _emit_empty_plan(config, topic: str, generated_at: str) -> None:
    emit_json(
        build_next_action_plan(
            config.library_dir,
            [],
            topic=topic,
            generated_at=generated_at,
        ).to_dict()
    )


def _build_report(config, lib, topic: str, broken_by_topic: dict) -> AuditReport:
    from distill.concepts.contradictions import find_contested
    from distill.pipeline.dashboard_data import collect_corpus_health_warnings
    from distill.pipeline.gaps import topic_gap_summary

    topic_dir = config.topic_dir(topic)
    contested = [
        {
            "name": c.name,
            "kind": "entity" if c.is_entity else "concept",
            "helpful": c.helpful_count,
            "harmful": c.harmful_count,
            "sources": c.source_count,
        }
        for c in (find_contested(topic_dir) if topic_dir.exists() else [])
    ]
    try:
        gap_summary = topic_gap_summary(config, topic)
    except Exception:
        gap_summary = {"gaps": [], "next_actions": []}
    return AuditReport(
        topic=topic,
        health_warnings=collect_corpus_health_warnings(config, lib, [topic], limit=50),
        contested=contested,
        broken_links=broken_by_topic.get(topic, []),
        gaps=list(gap_summary.get("gaps", [])),
        next_actions=list(gap_summary.get("next_actions", [])),
        verify=collect_verify_rollup(topic_dir),
        staleness=collect_staleness(topic_dir),
        near_duplicates=collect_near_duplicates(topic_dir),
        freshness=collect_synthesis_freshness(topic_dir, topic),
    )


def audit_cmd(
    topic: str = typer.Argument(
        "all",
        help="Topic to audit, or 'all' for the full library.",
        autocompletion=_complete_topics,
    ),
    report_only: bool = typer.Option(
        False,
        "--report-only",
        help="Write the report artifact(s) and exit without the action menu "
        "(for scheduled/unattended runs).",
    ),
    next_actions: bool = typer.Option(
        False,
        "--next-actions",
        help="Emit a bounded next-action plan instead of opening the interactive action menu.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the next-action plan as JSON. Implies --next-actions.",
    ),
):
    """Audit corpus trust and health into a `<topic>_Audit.md` report artifact.

    One deterministic run bundling verification coverage (the `_Verify.json`
    sidecars), stale/thin warnings, contested concepts, broken wiki-links, and
    coverage gaps -- then an action menu for the safe fixes. No model calls.

    Examples:
      distill audit all --report-only
      distill audit ai --next-actions
      distill --json audit all --next-actions
    """
    from distill.library.links import check_links

    next_actions, wants_json = _resolve_next_action_mode(json_output, next_actions)

    config = get_config()
    lib = Library(config)
    topics = lib.get_topics() if topic == "all" else [topic]
    now_iso = _now_iso()
    if not topics:
        if wants_json:
            _emit_empty_plan(config, topic, now_iso)
        else:
            console.print("[yellow]No topics found to audit.[/yellow]")
        raise typer.Exit(0)

    link_result = check_links(config.library_dir)
    broken_by_topic = _bucket_broken_links(link_result.broken_links)

    reports: list[AuditReport] = []
    for t in topics:
        report = _build_report(config, lib, t, broken_by_topic)
        reports.append(report)
        _write_topic_audit_report(config, report, now_iso=now_iso, quiet=wants_json)

    if topic == "all":
        _write_library_audit(config, now_iso, quiet=wants_json)

    if next_actions:
        plan = build_next_action_plan(
            config.library_dir,
            reports,
            topic=topic,
            generated_at=now_iso,
        )
        if wants_json:
            emit_json(plan.to_dict())
        else:
            _print_next_action_plan(plan)
        return

    total_findings = sum(r.issue_count for r in reports)
    if report_only or total_findings == 0:
        if total_findings == 0:
            console.print("\n[green]Corpus is healthy: no findings.[/green]")
        return

    _action_menu(config, topics, reports, link_result, now_iso)


def _write_topic_audit_report(config, report: AuditReport, *, now_iso: str, quiet: bool) -> None:
    path = write_audit_artifact(config.topic_dir(report.topic), report, now_iso=now_iso)
    if quiet:
        return
    v = report.verify
    s = report.staleness
    console.print(
        f"[bold]{report.topic}[/bold]: {report.issue_count} finding(s) -- "
        f"verify {v.clean}/{v.insights_total} clean, {len(v.flagged)} flagged, "
        f"{v.never_checked} unchecked | {len(s.stale)} stale prompt(s), "
        f"{len(report.freshness.stale)} stale synthesis/es, "
        f"{len(report.near_duplicates)} duplicate group(s) | {len(report.gaps)} gap(s), "
        f"{len(report.broken_links)} broken link(s), {len(report.contested)} contested"
    )
    console.print(f"  [dim]{path}[/dim]")


def _write_library_audit(config, now_iso: str, *, quiet: bool = False) -> None:
    """The library-wide hygiene view that ends every ``audit all`` run."""
    from distill.library.paths import atomic_write_text

    hygiene = collect_library_hygiene(config.library_dir)
    path = config.library_dir / "Library_Audit.md"
    atomic_write_text(path, render_library_audit_md(hygiene, now_iso=now_iso))
    if quiet:
        return
    console.print(
        f"\n[bold]Library[/bold]: {hygiene.healthy} healthy topic(s) | "
        f"{len(hygiene.empty)} empty, {len(hygiene.unreadable)} unreadable, "
        f"{len(hygiene.unindexed)} missing orientation | "
        f"{len(hygiene.test_named)} test-named (informational)"
    )
    console.print(f"  [dim]{path}[/dim]")


def _print_next_action_plan(plan: NextActionPlan) -> None:
    console.print("\n[bold]Next actions[/bold]")
    if not plan.actions:
        console.print("  [green]No bounded next actions found.[/green]")
        return
    for action in plan.actions:
        command = " ".join(action.command)
        console.print(f"  [cyan]{action.id}[/cyan] [{action.severity}] {action.rationale}")
        console.print(f"    command: {command}")
        console.print(f"    verifier: {' '.join(action.verifier.command)}")


def _bucket_broken_links(broken_links: list) -> dict[str, list]:
    """Bucket one library-wide link scan per topic by source-file path."""
    by_topic: dict[str, list] = {}
    for bl in broken_links:
        parts = bl.source_file.parts
        if "topics" in parts and parts.index("topics") + 1 < len(parts):
            by_topic.setdefault(parts[parts.index("topics") + 1], []).append(bl)
    return by_topic


def _act_fix_links(config, topics, reports, link_result, now_iso):
    from distill.library.links import fix_broken_links

    fixed = fix_broken_links(config.library_dir, link_result.broken_links)
    console.print(f"[green]Fixed {fixed} link(s).[/green]")


def _act_orientation(config, topics, reports, link_result, now_iso):
    from distill.library import claude_md

    for t in topics:
        claude_md.write_topic_claude_md(config.topic_dir(t), t, now_iso=now_iso)
    claude_md.write_library_claude_md(config.library_dir, now_iso=now_iso)
    console.print("[green]Orientation files regenerated.[/green]")


def _act_gaps(config, topics, reports, link_result, now_iso):
    for r in reports:
        if r.gaps:
            console.print(
                f"  [cyan]distill discover --from-gaps --topic {r.topic} --preview[/cyan]"
            )


def _act_stale(config, topics, reports, link_result, now_iso):
    from distill.pipeline.audit import reanalysis_commands

    for r in reports:
        if r.staleness.stale:
            for line in reanalysis_commands(config.library_dir, r.topic, r.staleness.stale):
                console.print(f"  [cyan]{line}[/cyan]")


def _act_freshness(config, topics, reports, link_result, now_iso):
    for r in reports:
        if r.freshness.stale:
            console.print(f"  [cyan]distill corpus {r.topic}[/cyan]")
        for item in r.freshness.shadowed_legacy:
            legacy_path = config.topic_dir(r.topic) / item["legacy"]
            console.print(
                f"  [dim]superseded by {item['active']}; remove by hand:[/dim] {legacy_path}"
            )


_ACTIONS = {
    "fix-links": _act_fix_links,
    "orientation": _act_orientation,
    "gaps": _act_gaps,
    "stale": _act_stale,
    "freshness": _act_freshness,
}


def _action_menu(config, topics: list[str], reports: list[AuditReport], link_result, now_iso: str):
    """Phase 2: only safe, free actions execute directly; anything that would
    spend money is printed as a command, never run."""
    options: list[tuple[str, str]] = []
    if any(r.broken_links for r in reports):
        options.append(("fix-links", "Fix broken wiki-links (deterministic rewrite)"))
    options.append(("orientation", "Regenerate CLAUDE.md / AGENTS.md orientation files"))
    if any(r.gaps for r in reports):
        options.append(("gaps", "Show the gap-fill discover commands (costs money; not auto-run)"))
    if any(r.staleness.stale for r in reports):
        options.append(
            ("stale", "Show re-analysis commands for stale artifacts (costs money; not auto-run)")
        )
    if any(r.freshness.stale or r.freshness.shadowed_legacy for r in reports):
        options.append(
            (
                "freshness",
                "Show re-synthesis commands for stale syntheses (costs money; not auto-run)",
            )
        )

    console.print("\n[bold]Actions[/bold]")
    for i, (_, label) in enumerate(options, 1):
        console.print(f"  {i}. {label}")
    console.print("  q. Done")
    choice = tty_prompt("Choose", default="q").strip().lower()
    selected = (
        options[int(choice) - 1][0] if choice.isdigit() and 0 < int(choice) <= len(options) else "q"
    )
    handler = _ACTIONS.get(selected)
    if handler is not None:
        handler(config, topics, reports, link_result, now_iso)


def register(app: typer.Typer) -> None:
    """Register ``audit`` on the given app."""
    app.command(name="audit", rich_help_panel="Maintain")(audit_cmd)
