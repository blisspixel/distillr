"""Operational home screen and HTML dashboard rendering.

The no-argument ``distill`` invocation lands here: ``_show_dashboard`` is the
operational home screen, falling back to ``_show_first_run_home`` when the
library is empty. ``maintain``'s ``dashboard``/``serve`` commands reuse the same
data through ``_dashboard_snapshot`` and render it to HTML with
``_render_dashboard_html``.

Data collection lives in ``distill.pipeline.dashboard_data`` (shared and tested
there); this module is the presentation layer only. Extracted verbatim from
``_logic.py`` during the Phase 2 decomposition -- ``_get_version`` and
``_topic_watch_ranking_strategy`` remain in ``_logic`` (shared with other
commands) and are imported back here; ``_logic``'s root callback imports
``_show_dashboard`` lazily to avoid an import cycle.
"""

from __future__ import annotations

import json
from html import escape

from rich import box
from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table

from distill.cli_shared import console
from distill.commands._helpers import get_config
from distill.commands._logic import _get_version, _topic_watch_ranking_strategy
from distill.commands._topic_changes import _topic_trend_label
from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_exists
from distill.pipeline.dashboard_data import (
    collect_corpus_health_warnings as _collect_corpus_health_warnings,
)
from distill.pipeline.dashboard_data import collect_recent_artifacts as _collect_recent_artifacts
from distill.pipeline.dashboard_data import (
    collect_stale_topic_watches as _collect_stale_topic_watches,
)
from distill.pipeline.dashboard_data import collect_topic_changes as _collect_topic_changes
from distill.pipeline.dashboard_data import count_paper_corpus as _count_paper_corpus
from distill.pipeline.dashboard_data import count_site_corpus as _count_site_corpus
from distill.pipeline.dashboard_data import count_topic_outputs as _count_topic_outputs
from distill.pipeline.dashboard_data import dashboard_snapshot as _shared_dashboard_snapshot
from distill.pipeline.dashboard_data import (
    estimated_topic_watch_sweep as _estimated_topic_watch_sweep,
)
from distill.pipeline.dashboard_data import format_run_timestamp as _format_run_timestamp
from distill.pipeline.dashboard_data import load_all_cost_runs as _load_all_cost_runs
from distill.pipeline.dashboard_data import load_latest_run_payload as _load_latest_run_payload
from distill.pipeline.dashboard_data import source_cost_rollups as _source_cost_rollups
from distill.pipeline.dashboard_data import sum_recent_cost as _sum_recent_cost
from distill.pipeline.dashboard_data import topic_cost_rollups as _topic_cost_rollups
from distill.pipeline.dashboard_data import (
    topic_watch_budget_messages as _topic_watch_budget_messages,
)


def _dashboard_metric(label: str, value: str, note: str = "") -> Panel:
    body = f"[bold]{value}[/bold]"
    if note:
        body += f"\n[dim]{note}[/dim]"
    return Panel(body, title=label, border_style="dim", padding=(0, 1))


def _build_start_here_table() -> Table:
    table = Table.grid(expand=True)
    table.add_column(style="bold cyan", width=23)
    table.add_column()
    table.add_row("Have one YouTube URL?", 'distill video "https://www.youtube.com/watch?v=..."')
    table.add_row(
        "Have one website URL?",
        "distill site https://example.com/page --topic scratch --seed-only",
    )
    table.add_row(
        "Have one paper URL?",
        "distill paper https://arxiv.org/abs/2602.12670 --topic papers",
    )
    table.add_row(
        "Need latest on a topic?",
        'distill latest "Microsoft AI news" --topic microsoft-news',
    )
    table.add_row(
        "Want recurring updates?",
        'distill monitor "Microsoft AI news" --topic microsoft-news',
    )
    return table


def _show_first_run_home(version: str, help_hint: str = "distill --help for all commands") -> None:
    console.print(f"  [dim]v{version}[/dim]  ·  [bold]Distill Start[/bold]")
    console.print("  [dim]Distill one thing first. Build the library later.[/dim]")
    console.print()
    console.print(
        Panel(
            _build_start_here_table(),
            title="Pick A Starting Point",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()

    notes = Table.grid(expand=True)
    notes.add_column(style="bold cyan", width=14)
    notes.add_column()
    notes.add_row("What happens", "Each command saves artifacts into your library for reuse later.")
    notes.add_row(
        "Use --topic", "Choose where the output gets filed. Default topic: [bold]ai[/bold]."
    )
    notes.add_row(
        "Then",
        "Open the generated files, run [bold]distill videos <topic>[/bold], or generate synthesis/report later.",
    )
    console.print(Panel(notes, title="How Distill Works", border_style="green", box=box.ROUNDED))
    console.print()
    console.print(f"  [dim]{help_hint}[/dim]")


def _show_dashboard():  # noqa: C901 — legacy, will refactor
    """Show an operational home screen when running `distill` with no arguments."""
    version = _get_version()

    try:
        config = get_config()
    except Exception:
        _show_first_run_home(version)
        return

    lib = Library(config)
    topics = lib.get_topics()
    watchlist = lib.get_watchlist()
    topic_watchlist = lib.get_topic_watchlist()

    total_channels = sum(len(lib.get_channels(t)) for t in topics)
    total_videos = 0
    full_videos = 0
    scan_videos = 0
    for topic in topics:
        for ch in lib.get_channels(topic):
            vdir = config.channel_dir(topic, ch.name) / "videos"
            if not vdir.exists():
                continue
            for d in vdir.iterdir():
                if not d.is_dir() or not artifact_exists(d, "insights"):
                    continue
                total_videos += 1
                meta_path = d / "metadata.json"
                try:
                    if meta_path.exists():
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        if meta.get("analysis_mode") == "scan":
                            scan_videos += 1
                        else:
                            full_videos += 1
                    else:
                        full_videos += 1
                except (OSError, json.JSONDecodeError):
                    full_videos += 1

    site_count, page_count = _count_site_corpus(config, topics)
    paper_count = _count_paper_corpus(config, topics)
    report_count, brief_count, synthesis_count = _count_topic_outputs(config, topics)
    # Check new location first, fall back to old
    _ops_log = config.library_dir / ".distill" / "cost_log.jsonl"
    _legacy_log = config.library_dir / "cost_log.jsonl"
    _cost_log = _ops_log if _ops_log.exists() else _legacy_log
    all_cost_entries = _load_all_cost_runs(_cost_log)
    recent_runs = all_cost_entries[-6:]
    recent_spend = _sum_recent_cost(recent_runs)
    latest_run = _load_latest_run_payload(config.library_dir)
    latest_results = latest_run.get("results", {}) if latest_run else {}
    latest_issues = latest_run.get("issues", []) if latest_run else []
    recent_artifacts = _collect_recent_artifacts(config, topics, limit=6)
    topic_changes = _collect_topic_changes(config, lib, topics, topic_watchlist, limit=6)
    stale_topic_watches = _collect_stale_topic_watches(topic_watchlist)
    corpus_health_warnings = _collect_corpus_health_warnings(config, lib, topics, limit=6)
    next_sweep_cost = _estimated_topic_watch_sweep(topic_watchlist)
    due_topic_watches = len(stale_topic_watches)
    topic_spend_rollups = _topic_cost_rollups(all_cost_entries, days=30, limit=4)
    source_spend_rollups = _source_cost_rollups(all_cost_entries, days=30)
    budget_messages = []
    for entry in topic_watchlist:
        budget_messages.extend(_topic_watch_budget_messages(entry, all_cost_entries))

    is_first_run = not any(
        [
            topics,
            watchlist,
            topic_watchlist,
            total_videos,
            site_count,
            paper_count,
            all_cost_entries,
        ]
    )
    if is_first_run:
        _show_first_run_home(version)
        return

    console.print(
        f"  [dim]v{version}[/dim]  ·  [bold]Distill Home[/bold]  "
        f"[dim]stay current / learn fast / build corpus[/dim]"
    )
    console.print(
        '  [dim]Quick commands: distill video "https://www.youtube.com/watch?v=..."  |  '
        'distill latest "Microsoft AI news" --topic microsoft-news  |  distill --help[/dim]'
    )
    console.print()

    overview_cards = [
        _dashboard_metric("Topics", str(len(topics)), "tracked research buckets"),
        _dashboard_metric("Channels", str(total_channels), "YouTube sources in corpus"),
        _dashboard_metric(
            "Videos",
            str(total_videos),
            f"{full_videos} full / {scan_videos} scan"
            if total_videos
            else "no analyzed videos yet",
        ),
        _dashboard_metric(
            "Sites",
            str(site_count),
            f"{page_count} captured pages" if page_count else "no site pages captured",
        ),
        _dashboard_metric("Papers", str(paper_count), "captured paper records"),
        _dashboard_metric("Channel Watch", str(len(watchlist)), "recurring creator monitoring"),
        _dashboard_metric("Topic Watch", str(len(topic_watchlist)), "recurring topic monitoring"),
        _dashboard_metric(
            "Recent Spend",
            f"${recent_spend:.2f}",
            f"last {len(recent_runs)} run{'s' if len(recent_runs) != 1 else ''}"
            if recent_runs
            else "no cost log yet",
        ),
        _dashboard_metric(
            "Next Sweep",
            f"${next_sweep_cost:.2f}",
            "topic-watch estimate" if topic_watchlist else "add topic watches to estimate",
        ),
    ]
    console.print(Columns(overview_cards, equal=True, expand=True))
    console.print()

    stay_current = Table.grid(expand=True)
    stay_current.add_column(style="bold cyan", width=14)
    stay_current.add_column()
    if topics:
        topic_lines = []
        for topic in topics[:6]:
            ch_count = len(lib.get_channels(topic))
            topic_lines.append(
                f"{topic} [dim]({ch_count} channel{'s' if ch_count != 1 else ''})[/dim]"
            )
        if len(topics) > 6:
            topic_lines.append(f"[dim]+{len(topics) - 6} more[/dim]")
        stay_current.add_row("Topics", "\n".join(topic_lines))
    else:
        stay_current.add_row("Topics", "[dim]No topics yet[/dim]")
    if watchlist:
        channel_lines = []
        for entry in watchlist[:5]:
            suffix = " / custom" if entry.instructions else ""
            channel_lines.append(f"{entry.name} [dim]{entry.topic} / {entry.days}d{suffix}[/dim]")
        if len(watchlist) > 5:
            channel_lines.append(f"[dim]+{len(watchlist) - 5} more[/dim]")
        stay_current.add_row("Channel Watch", "\n".join(channel_lines))
    else:
        stay_current.add_row("Channel Watch", "[dim]No channel watches configured[/dim]")
    if topic_watchlist:
        topic_watch_lines = []
        for entry in topic_watchlist[:5]:
            mode = "report" if entry.report else "learn"
            ranking_label = _topic_watch_ranking_strategy(entry.ranking_mode)["label"]
            trend_label = _topic_trend_label(config, entry.topic)
            last = (
                f" / last {_format_run_timestamp(entry.last_run_at)}" if entry.last_run_at else ""
            )
            budget_bits = []
            if entry.max_run_cost:
                budget_bits.append(f"max ${entry.max_run_cost:.2f}/run")
            if entry.monthly_budget:
                budget_bits.append(f"${entry.monthly_budget:.2f}/30d")
            if entry.paused:
                budget_bits.append("paused")
            budget_suffix = f" / {', '.join(budget_bits)}" if budget_bits else ""
            trend_suffix = f" / {trend_label}" if trend_label else ""
            topic_watch_lines.append(
                f"{entry.name} [dim]{entry.topic} / {entry.cadence} / {entry.days}d / {entry.limit} picks / {ranking_label} / {mode}{budget_suffix}{last}{trend_suffix}[/dim]"
            )
        if len(topic_watchlist) > 5:
            topic_watch_lines.append(f"[dim]+{len(topic_watchlist) - 5} more[/dim]")
        stay_current.add_row("Topic Watch", "\n".join(topic_watch_lines))
    else:
        stay_current.add_row("Topic Watch", "[dim]No topic watches configured[/dim]")
    stay_current.add_row(
        "Run Health",
        (
            f"[bold]{due_topic_watches}[/bold] due topic watch{'es' if due_topic_watches != 1 else ''}"
            if topic_watchlist
            else "[dim]Add topic watches to monitor spaces, not just creators[/dim]"
        ),
    )

    recent = Table.grid(expand=True, padding=(0, 2))
    recent.add_column(style="bold dim", width=16)
    recent.add_column(style="bold dim")
    recent.add_column(style="bold dim", justify="right", width=8)
    recent.add_column(style="bold dim", justify="right", width=9)
    recent.add_row("When", "Command", "Cost", "Time")
    if recent_runs:
        for entry in reversed(recent_runs):
            recent.add_row(
                _format_run_timestamp(entry.get("timestamp", "")),
                str(entry.get("command", "unknown")),
                f"${float(entry.get('actual_cost') or 0):.2f}",
                f"{float(entry.get('elapsed_seconds') or 0):.1f}s",
            )
    else:
        recent.add_row("-", "No runs logged yet", "-", "-")

    changed = Table.grid(expand=True)
    changed.add_column(style="bold cyan", width=14)
    changed.add_column()
    if topic_changes:
        for topic, summary in topic_changes:
            trend_label = _topic_trend_label(config, topic)
            if trend_label:
                summary = f"{summary} [dim]({trend_label})[/dim]"
            changed.add_row(topic, summary)
    elif recent_artifacts:
        for mtime, kind, label in recent_artifacts:
            changed.add_row(kind, f"{label} [dim]{mtime.strftime('%b %d %I:%M %p')}[/dim]")
    else:
        changed.add_row("Artifacts", "[dim]No recent synthesis/report artifacts detected[/dim]")

    learn_fast = Table.grid(expand=True)
    learn_fast.add_column(style="bold cyan", width=14)
    learn_fast.add_column()
    learn_fast.add_row(
        "Outputs",
        (f"{synthesis_count} topic syntheses\n{report_count} reports / {brief_count} briefs"),
    )
    if recent_artifacts:
        top_artifacts = []
        for _mtime, kind, label in recent_artifacts[:4]:
            top_artifacts.append(f"{label} [dim]({kind})[/dim]")
        learn_fast.add_row("Newest Work", "\n".join(top_artifacts))
    else:
        learn_fast.add_row("Newest Work", "[dim]No recent synthesis or reports yet[/dim]")
    if recent_runs:
        last_command = recent_runs[-1].get("command", "unknown")
        last_cost = float(recent_runs[-1].get("actual_cost") or 0)
        learn_fast.add_row("Last Run", f"{last_command} [dim]${last_cost:.2f} actual[/dim]")
    else:
        learn_fast.add_row("Last Run", "[dim]No runs logged yet[/dim]")

    build_corpus = Table.grid(expand=True)
    build_corpus.add_column(style="bold cyan", width=14)
    build_corpus.add_column()
    build_corpus.add_row(
        "Corpus Mix",
        (
            f"{total_videos} video insight{'s' if total_videos != 1 else ''} [dim]({full_videos} full / {scan_videos} scan)[/dim]\n"
            f"{page_count} site page{'s' if page_count != 1 else ''} across {site_count} site{'s' if site_count != 1 else ''}\n"
            f"{paper_count} paper{'s' if paper_count != 1 else ''}"
        ),
    )
    build_corpus.add_row(
        "Coverage",
        (
            f"{len(topics)} topic{'s' if len(topics) != 1 else ''}\n"
            f"{total_channels} channel source{'s' if total_channels != 1 else ''}"
        ),
    )
    build_corpus.add_row(
        "Spend",
        f"[bold]${recent_spend:.2f}[/bold] [dim]recent actual[/dim]\n"
        + (
            f"[bold]~${next_sweep_cost:.2f}[/bold] [dim]next topic-watch sweep[/dim]"
            if topic_watchlist
            else "[dim]No topic-watch spend forecast yet[/dim]"
        ),
    )
    if topic_spend_rollups:
        build_corpus.add_row(
            "Top Spend",
            "\n".join(
                f"{topic} [dim]${cost:.2f} / {runs} run{'s' if runs != 1 else ''}[/dim]"
                for topic, cost, runs in topic_spend_rollups
            ),
        )
    if source_spend_rollups:
        build_corpus.add_row(
            "By Source",
            "\n".join(
                f"{source} [dim]${cost:.2f} / {runs} run{'s' if runs != 1 else ''}[/dim]"
                for source, cost, runs in source_spend_rollups[:4]
            ),
        )

    attention = Table.grid(expand=True)
    attention.add_column(style="bold cyan", width=14)
    attention.add_column()
    if latest_results.get("failed"):
        attention.add_row(
            "Failures",
            f"[yellow]{latest_results.get('failed')} failed video items in latest run[/yellow]",
        )
    if latest_issues:
        attention.add_row(
            "Issues",
            f"[yellow]{len(latest_issues)} persisted run issue{'s' if len(latest_issues) != 1 else ''}[/yellow]",
        )
    if stale_topic_watches:
        for idx, item in enumerate(stale_topic_watches[:3]):
            attention.add_row("Stale" if idx == 0 else "", f"[yellow]{item}[/yellow]")
    if corpus_health_warnings:
        for idx, item in enumerate(corpus_health_warnings[:3]):
            attention.add_row("Corpus" if idx == 0 else "", f"[yellow]{item}[/yellow]")
    if budget_messages:
        for idx, item in enumerate(budget_messages[:3]):
            attention.add_row("Budget" if idx == 0 else "", f"[yellow]{item}[/yellow]")
    if not watchlist and not topic_watchlist:
        attention.add_row("Watch State", "[dim]No recurring watches configured yet[/dim]")
    if attention.row_count == 0:
        attention.add_row(
            "Status", "[green]No immediate issues detected from the latest run logs[/green]"
        )
    attention.add_row(
        "Artifacts", "[dim]library/latest_run.json · library/latest_run_errors.md[/dim]"
    )

    top_row = Columns(
        [
            Panel(stay_current, title="Stay Current", border_style="blue"),
            Panel(learn_fast, title="Learn Fast", border_style="green"),
            Panel(build_corpus, title="Build Corpus", border_style="magenta"),
        ],
        equal=True,
        expand=True,
    )
    bottom_row = Columns(
        [
            Panel(recent, title="Recent Activity", border_style="white"),
            Panel(changed, title="What Changed", border_style="cyan"),
            Panel(attention, title="Needs Attention", border_style="yellow"),
        ],
        equal=True,
        expand=True,
    )
    console.print(top_row)
    console.print()
    console.print(bottom_row)
    console.print()

    if topics:
        primary_topic = topics[0]
        next_actions = [
            ("distill topic-watch run", "Refresh recurring topic watches"),
            ("distill catch-up", "Refresh watched channels with scan analysis"),
            (f"distill run {primary_topic} --refresh", "Resume deep processing for a topic"),
            (f"distill report {primary_topic}", "Build or refresh a deep research report"),
        ]
    else:
        next_actions = [
            (
                'distill latest "Microsoft AI latest news" --topic microsoft-news',
                "Create a fresh stay-current topic",
            ),
            (
                'distill topic-watch add "Microsoft AI news" --topic microsoft-news --cadence daily',
                "Start a recurring topic watch",
            ),
            ("distill watch add https://www.youtube.com/@YourChannel", "Track a creator you trust"),
            (
                "distill site-batch configs/example_seeds.json --topic example --seed-only",
                "Analyze a curated website source set",
            ),
        ]

    actions = Table.grid(expand=True, padding=(0, 2))
    actions.add_column(style="bold dim", width=32)
    actions.add_column(style="bold dim")
    actions.add_row("Next Command", "Why")
    for cmd, why in next_actions:
        actions.add_row(cmd, why)
    console.print(Panel(actions, title="Recommended Next Actions", border_style="cyan"))
    console.print()
    console.print("  [dim]distill --help for all commands[/dim]")


def _dashboard_snapshot(config: DistillConfig) -> dict:
    return _shared_dashboard_snapshot(config)


def _render_dashboard_html(version: str, snapshot: dict) -> str:  # noqa: C901 — legacy, will refactor
    def list_items(items: list[str]) -> str:
        if not items:
            return "<li>None</li>"
        return "".join(f"<li>{escape(item)}</li>" for item in items)

    metrics = [
        ("Topics", str(len(snapshot["topics"]))),
        ("Channels", str(snapshot["total_channels"])),
        ("Videos", str(snapshot["total_videos"])),
        ("Sites", str(snapshot["site_count"])),
        ("Papers", str(snapshot["paper_count"])),
        ("Recent Spend", f"${snapshot['recent_spend']:.2f}"),
        ("Next Sweep", f"${snapshot['next_sweep_cost']:.2f}"),
    ]
    metric_cards = "".join(
        f"<div class='card metric'><div class='label'>{escape(label)}</div><div class='value'>{escape(value)}</div></div>"
        for label, value in metrics
    )

    topic_lines = [
        f"{topic} ({len(snapshot['lib'].get_channels(topic))} channels)"
        for topic in snapshot["topics"][:8]
    ]
    channel_watch_lines = [
        f"{entry.name} - {entry.topic} / {entry.days}d" for entry in snapshot["watchlist"][:8]
    ]
    topic_watch_lines = []
    for entry in snapshot["topic_watchlist"][:8]:
        bits = [entry.topic, entry.cadence, f"{entry.days}d", f"{entry.limit} picks"]
        if entry.max_run_cost:
            bits.append(f"max ${entry.max_run_cost:.2f}/run")
        if entry.monthly_budget:
            bits.append(f"${entry.monthly_budget:.2f}/30d")
        if entry.paused:
            bits.append("paused")
        trend_label = (snapshot.get("topic_trends") or {}).get(entry.topic)
        if trend_label:
            bits.append(trend_label)
        topic_watch_lines.append(f"{entry.name} - {' / '.join(bits)}")

    recent_rows = (
        "".join(
            "<tr>"
            f"<td>{escape(_format_run_timestamp(entry.get('timestamp', '')))}</td>"
            f"<td>{escape(str(entry.get('command', 'unknown')))}</td>"
            f"<td>${float(entry.get('actual_cost') or 0):.2f}</td>"
            f"<td>{float(entry.get('elapsed_seconds') or 0):.1f}s</td>"
            "</tr>"
            for entry in reversed(snapshot["recent_runs"])
        )
        or "<tr><td>-</td><td>No runs logged yet</td><td>-</td><td>-</td></tr>"
    )

    changed_lines = []
    for topic, summary in snapshot["topic_changes"]:
        trend_label = (snapshot.get("topic_trends") or {}).get(topic)
        if trend_label:
            changed_lines.append(f"{topic}: {summary} ({trend_label})")
        else:
            changed_lines.append(f"{topic}: {summary}")
    if not changed_lines:
        changed_lines = [
            f"{kind}: {label} {mtime.strftime('%b %d %I:%M %p')}"
            for mtime, kind, label in snapshot["recent_artifacts"]
        ]
    attention_lines = []
    if snapshot["latest_results"].get("failed"):
        attention_lines.append(
            f"Latest run failed items: {snapshot['latest_results'].get('failed')}"
        )
    if snapshot["latest_issues"]:
        attention_lines.append(f"Latest run issues: {len(snapshot['latest_issues'])}")
    attention_lines.extend(snapshot["stale_topic_watches"][:5])
    attention_lines.extend(snapshot["corpus_health_warnings"][:5])
    attention_lines.extend(snapshot["budget_messages"][:5])
    if not attention_lines:
        attention_lines = ["No immediate issues detected"]

    topic_spend_lines = [
        f"{topic} - ${cost:.2f} / {runs} runs"
        for topic, cost, runs in snapshot["topic_spend_rollups"]
    ]
    source_spend_lines = [
        f"{source} - ${cost:.2f} / {runs} runs"
        for source, cost, runs in snapshot["source_spend_rollups"]
    ]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Distill Dashboard</title>
  <style>
    :root {{
      --bg: #f6f2e9;
      --panel: #fffdf8;
      --ink: #1c1f26;
      --muted: #6b7280;
      --line: #d9cfbf;
      --accent: #0f766e;
      --accent2: #b45309;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Georgia, 'Times New Roman', serif; background: linear-gradient(180deg, #f4efe4 0%, var(--bg) 100%); color: var(--ink); }}
    .wrap {{ max-width: 1400px; margin: 0 auto; padding: 28px; }}
    h1 {{ margin: 0; font-size: 2.1rem; }}
    .sub {{ color: var(--muted); margin-top: 8px; }}
    .grid {{ display: grid; gap: 16px; }}
    .metrics {{ grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 24px 0; }}
    .cols3 {{ grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 18px; box-shadow: 0 8px 24px rgba(28,31,38,0.05); }}
    .metric .label {{ font-size: 0.85rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
    .metric .value {{ font-size: 2rem; margin-top: 8px; }}
    h2 {{ margin: 0 0 12px 0; font-size: 1.15rem; }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 6px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--line); }}
    th {{ color: var(--muted); font-weight: 600; }}
    .footer {{ margin-top: 20px; color: var(--muted); font-size: 0.9rem; }}
    .accent {{ color: var(--accent); }}
    .warn {{ color: var(--accent2); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Distill Dashboard</h1>
    <div class="sub">v{escape(version)} · stay current / learn fast / build corpus</div>
    <div class="grid metrics">{metric_cards}</div>

    <div class="grid cols3">
      <section class="card">
        <h2>Stay Current</h2>
        <ul>{list_items(topic_lines)}</ul>
        <h2 style="margin-top:16px;">Channel Watches</h2>
        <ul>{list_items(channel_watch_lines)}</ul>
        <h2 style="margin-top:16px;">Topic Watches</h2>
        <ul>{list_items(topic_watch_lines)}</ul>
      </section>

      <section class="card">
        <h2>Learn Fast</h2>
        <ul>
          <li>{snapshot["synthesis_count"]} topic syntheses</li>
          <li>{snapshot["report_count"]} reports / {snapshot["brief_count"]} briefs</li>
          <li>{snapshot["page_count"]} site pages</li>
        </ul>
        <h2 style="margin-top:16px;">What Changed</h2>
        <ul>{list_items(changed_lines)}</ul>
      </section>

      <section class="card">
        <h2>Build Corpus</h2>
        <ul>
          <li>{snapshot["total_videos"]} video insights ({snapshot["full_videos"]} full / {snapshot["scan_videos"]} scan)</li>
          <li>{snapshot["site_count"]} sites / {snapshot["page_count"]} pages</li>
          <li>{len(snapshot["topics"])} topics / {snapshot["total_channels"]} channels</li>
        </ul>
        <h2 style="margin-top:16px;">Top Spend (30d)</h2>
        <ul>{list_items(topic_spend_lines)}</ul>
        <h2 style="margin-top:16px;">By Source (30d)</h2>
        <ul>{list_items(source_spend_lines)}</ul>
      </section>
    </div>

    <div class="grid cols3" style="margin-top:16px;">
      <section class="card" style="grid-column: span 2;">
        <h2>Recent Activity</h2>
        <table>
          <thead><tr><th>When</th><th>Command</th><th>Cost</th><th>Time</th></tr></thead>
          <tbody>{recent_rows}</tbody>
        </table>
      </section>
      <section class="card">
        <h2>Needs Attention</h2>
        <ul>{list_items(attention_lines)}</ul>
      </section>
    </div>

    <div class="footer">
      Source artifacts: <span class="accent">library/latest_run.json</span>,
      <span class="accent">library/latest_run_errors.md</span>,
      <span class="accent">library/library_Latest_Changes.md</span>
    </div>
  </div>
</body>
</html>"""
