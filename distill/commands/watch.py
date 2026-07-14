# pyright: strict
"""Watch commands: the ``watch`` channel-watchlist sub-app and ``catch-up``.

Extracted from the _logic.py monolith. ``watch`` manages a channel watch list;
``catch-up`` refreshes every watched channel. Shared helpers that other commands
also use (_process_video, _ensure_channel_context, the shell-completion
callbacks) live in helper modules and are imported back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import typer
from rich.markup import escape

from distill import cli_shared
from distill.cli_shared import SHORTS_THRESHOLD, console
from distill.cli_shared import duration_str as _duration_str
from distill.cli_shared import format_date as _format_date
from distill.cli_shared import require_model as _require_model
from distill.cli_shared import strip_frontmatter as _strip_frontmatter
from distill.commands._helpers import (
    _complete_topics,
    _complete_watched_channels,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
    save_command_cost,
)
from distill.commands._helpers import (
    ensure_channel_context as _ensure_channel_context,
)
from distill.commands._helpers import (
    process_video as _process_video,
)
from distill.commands._helpers import (
    run_preflight as _preflight,
)
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import (
    VideoInfo,
    discover_videos,
    resolve_channel_name,
)
from distill.library import Library
from distill.library.paths import find_artifact
from distill.library.state import ChannelState
from distill.llm.availability import model_available
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.pipeline.costs import BudgetExceededError, estimate_routed_video_workflow_cost
from distill.pipeline.summary import (
    ETATracker,
    RunSummary,
    display_estimate,
    display_summary,
)
from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

_ACCENT = "rgb(100,149,237)"

__all__ = [
    "catch_up",
    "register",
    "watch_add",
    "watch_app",
    "watch_days",
    "watch_default",
    "watch_instructions",
    "watch_remove",
]


@dataclass(frozen=True)
class _LatestInsight:
    title: str
    upload_date: str
    video_dir: Path


def _read_metadata(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return cast("dict[str, Any]", data)
    return {}


def _metadata_str(metadata: dict[str, Any], key: str, default: str = "") -> str:
    value = metadata.get(key, default)
    return value if isinstance(value, str) else default


watch_app = typer.Typer(
    help="Manage your channel watch list",
    invoke_without_command=True,
    rich_markup_mode="rich",
)


@watch_app.callback()
def watch_default(ctx: typer.Context) -> None:
    """Show your watch list."""
    if ctx.invoked_subcommand is not None:
        return
    config = get_config()
    lib = Library(config)
    watchlist = lib.get_watchlist()

    if not watchlist:
        console.print()
        console.print("  [dim]No channels on your watch list[/dim]")
        console.print()
        console.print("    distill watch add <url>")
        console.print("    distill watch add <url> --topic ai")
        console.print('    distill watch add <url> --instructions "Extract the best deals..."')
        console.print()
        return

    console.print()
    max_name = min(max(len(e.name) for e in watchlist), 28)
    for e in watchlist:
        display_name = e.name if len(e.name) <= max_name else e.name[: max_name - 2] + ".."
        padding = " " * (max_name - len(display_name) + 2)
        console.print(
            f"  [{_ACCENT}]{display_name}[/{_ACCENT}]{padding}[dim]{e.topic} / {e.days}d[/dim]"
        )
        if e.instructions:
            # Show first 60 chars of instructions
            preview = e.instructions[:57] + "..." if len(e.instructions) > 60 else e.instructions
            approval = "" if e.instructions_approved else " [approval required]"
            console.print(f"  {' ' * max_name}  [dim]{escape(preview)}{approval}[/dim]")

    console.print()
    console.print(f"  [dim]{len(watchlist)} watched  ·  distill catch-up to refresh[/dim]")
    console.print()


def _show_latest_insights(  # noqa: C901 - legacy display helper
    config: DistillConfig, topic: str, channel_name: str, limit: int = 3
) -> None:
    """Print a compact summary of the latest video insights for a channel."""
    videos_dir = config.videos_dir(topic, channel_name)
    if not videos_dir.exists():
        return
    vid_list: list[_LatestInsight] = []
    for vid_dir in videos_dir.iterdir():
        if not vid_dir.is_dir():
            continue
        meta_file = vid_dir / "metadata.json"
        insights_file = find_artifact(vid_dir, "insights")
        if not meta_file.exists() or not insights_file.exists():
            continue
        try:
            meta = _read_metadata(meta_file)
            vid_list.append(
                _LatestInsight(
                    title=_metadata_str(meta, "title", "Unknown"),
                    upload_date=_metadata_str(meta, "upload_date"),
                    video_dir=vid_dir,
                )
            )
        except (OSError, json.JSONDecodeError):
            continue
    if not vid_list:
        return
    vid_list.sort(key=lambda v: v.upload_date, reverse=True)
    selected = vid_list[:limit]

    console.print(f"\n  [bold]Latest from {channel_name}[/bold]\n")
    for i, item in enumerate(selected, 1):
        title = item.title
        date = _format_date(item.upload_date)
        insights_file = find_artifact(item.video_dir, "insights")
        content = insights_file.read_text(encoding="utf-8")
        content = _strip_frontmatter(content)
        summary_text = ""
        in_summary = False
        for line in content.split("\n"):
            if line.strip().lower().startswith("## summary") or line.strip().lower().startswith(
                "## quick take"
            ):
                in_summary = True
                continue
            if in_summary and line.strip().startswith("## "):
                break
            if in_summary:
                summary_text += line + "\n"
        summary_text = summary_text.strip()
        if not summary_text:
            for line in content.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    summary_text = line
                    break
        if len(summary_text) > 300:
            summary_text = summary_text[:297] + "..."

        console.print(f"  [bold]{i}. {title}[/bold]")
        console.print(f"  [dim]{date}[/dim]")
        console.print(f"  {summary_text}\n")

    console.print(f"  [dim]distill show {channel_name}                     Full insights[/dim]")
    console.print(f"  [dim]distill synthesis {channel_name}                Synthesis[/dim]\n")


def _print_goal_refreshes(config: DistillConfig, *, topic_filter: str | None = None) -> list[str]:
    """Print and return the refresh commands for persisted topic goals."""
    from distill.pipeline.goals import goal_refresh_command, load_topic_goals

    goals = load_topic_goals(config.library_dir)
    if topic_filter:
        goals = {t: e for t, e in goals.items() if t == topic_filter}
    lines = [goal_refresh_command(t, e) for t, e in sorted(goals.items())]
    if lines:
        console.print("\n  [dim]Goal-driven topics - refresh against their saved goals:[/dim]")
        for line in lines:
            console.print(f"  [cyan]{line}[/cyan]")
    return lines


@watch_app.command("add")
def watch_add(
    url: str = typer.Argument(help="YouTube channel URL"),
    topic: str = typer.Option("watch", "--topic", "-t", help="Topic to file under"),
    days_opt: int = typer.Option(
        14, "--days", "-d", help="Lookback days for catch-up (default 14)"
    ),
    instructions: str = typer.Option(
        "",
        "--instructions",
        "-i",
        help="Custom analysis instructions for this channel",
    ),
) -> None:
    """Add a channel to your watch list.

    Examples:
      distill watch add https://www.youtube.com/@NateBJones
      distill watch add https://www.youtube.com/@Smokemon07 --days 2 --instructions "Extract top deals"
    """
    config = get_config()
    lib = Library(config)
    existing = next((entry for entry in lib.get_watchlist() if entry.url == url), None)
    if existing is not None:
        console.print(f"  [dim]{existing.name} already on watch list[/dim]")
        return
    name = resolve_channel_name(url)

    suggested_instructions = ""
    # Suggestions derived from public titles are never promoted to operator
    # instructions without a separate, explicit approval command.
    if not instructions and model_available():
        with console.status(
            f"  {name}  [dim]generating analysis focus[/dim]",
            spinner="dots",
        ):
            try:
                vids = discover_videos(url, months=1, quiet=True)
                if vids:
                    titles = [v.title for v in vids[:15]]
                    from distill.pipeline.analysis.video import (
                        generate_watch_instructions,
                    )

                    tracker = budgeted_cost_tracker(config, "watch-add")
                    try:
                        auto = generate_watch_instructions(
                            name,
                            titles,
                            config,
                            tracker=tracker,
                        )
                        if auto and auto.strip():
                            suggested_instructions = auto.strip()[:2048]
                    finally:
                        save_command_cost(
                            config,
                            "watch-add",
                            tracker,
                            metadata={"channel": name, "topic": topic},
                        )
            except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
                raise
            except Exception as exc:
                console.print(f"  [yellow]auto-instructions skipped: {exc}[/yellow]")

    if lib.add_to_watchlist(url, name, topic=topic, instructions=instructions, days=days_opt):
        console.print(f"  Watching [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{topic} / {days_opt}d[/dim]")
        if instructions:
            console.print(f"  [dim]Focus: {escape(instructions[:100])}[/dim]")
        elif suggested_instructions:
            console.print(
                f"  [dim]Suggested focus (not active): {escape(suggested_instructions[:200])}[/dim]"
            )
            console.print(
                f'  [dim]Approve with: distill watch instructions {escape(name)} "..."[/dim]'
            )
        console.print()
        console.print(
            f"  [dim]distill catch-up {name}                    Scan for new videos now[/dim]"
        )
        console.print(
            f'  [dim]distill watch instructions {name} "..."    Change analysis focus[/dim]'
        )
        console.print(
            f"  [dim]distill watch days {name} {days_opt}                  Change lookback window[/dim]"
        )
    else:
        console.print(f"  [dim]{name} already on watch list[/dim]")


@watch_app.command("remove")
def watch_remove(
    name: str = typer.Argument(
        help="Channel name to remove", autocompletion=_complete_watched_channels
    ),
) -> None:
    """Remove a channel from your watch list."""
    config = get_config()
    lib = Library(config)
    if lib.remove_from_watchlist(name):
        console.print(f"  Removed {name} from watch list")
    else:
        console.print(f"  [red]{name} not found on watch list[/red]")


@watch_app.command("instructions")
def watch_instructions(
    name: str = typer.Argument(help="Channel name", autocompletion=_complete_watched_channels),
    instructions: str = typer.Argument(help="New custom instructions (use quotes)"),
) -> None:
    """Set or update custom analysis instructions for a watched channel.

    Examples:
      distill watch instructions Smokemon07 "Extract top 10 deals with prices, links, and why each is a good deal"
    """
    config = get_config()
    lib = Library(config)
    if lib.update_watch_instructions(name, instructions):
        console.print(f"  Updated instructions for [{_ACCENT}]{name}[/{_ACCENT}]")
        console.print(f"  [dim]{instructions[:80]}[/dim]")
    else:
        console.print(f"  [red]{name} not found on watch list[/red]")


@watch_app.command("days")
def watch_days(
    name: str = typer.Argument(help="Channel name", autocompletion=_complete_watched_channels),
    days: int = typer.Argument(help="Lookback days for catch-up"),
) -> None:
    """Set how far back catch-up looks for a channel.

    Examples:
      distill watch days Smokemon07 2
      distill watch days "Guy in a Cube" 14
    """
    config = get_config()
    lib = Library(config)
    if lib.update_watch_days(name, days):
        console.print(f"  [{_ACCENT}]{name}[/{_ACCENT}]  [dim]{days}d lookback[/dim]")
    else:
        console.print(f"  [red]{name} not found on watch list[/red]")


def catch_up(  # noqa: C901 — legacy, will refactor
    channel: str | None = typer.Argument(
        None,
        help="Channel name to refresh (default: all)",
        autocompletion=_complete_watched_channels,
    ),
    topic: str | None = typer.Option(
        None,
        "--topic",
        "-t",
        help="Only refresh channels in this topic",
        autocompletion=_complete_topics,
    ),
    days_override: int | None = typer.Option(None, "--days", "-d", help="Override lookback days"),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Max videos per channel"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without processing"),
    shorts: bool = typer.Option(True, "--shorts/--no-shorts", help="Include Shorts"),
) -> None:
    """Refresh watched channels with lightweight scan analysis.

    Run with no arguments to refresh all watched channels.
    Filter by channel name or topic.

    Examples:
      distill catch-up
      distill catch-up Smokemon07
      distill catch-up --topic ai
      distill catch-up --topic deals --days 1
      distill catch-up --dry-run
    """
    _preflight()
    config = get_config()
    _require_model()
    lib = Library(config)
    watchlist = lib.get_watchlist()

    if not watchlist:
        console.print("  [dim]Watch list is empty. Add channels with:[/dim]")
        console.print("    distill watch add <url>")
        return

    # Filter by channel name
    if channel:
        match = [e for e in watchlist if e.name.lower() == channel.lower()]
        if not match:
            console.print(f"  [red]{channel} not on watch list[/red]")
            console.print("  [dim]distill watch to see your list[/dim]")
            return
        watchlist = match

    # Filter by topic
    if topic:
        watchlist = [e for e in watchlist if e.topic.lower() == topic.lower()]
        if not watchlist:
            console.print(f"  [red]No watched channels in topic '{topic}'[/red]")
            return
    tracker = budgeted_cost_tracker(config, "catch-up")
    summary = RunSummary(command="catch-up")

    # Discover + process per channel (live updates)
    console.print()
    topics_touched: set[str] = set()

    for entry in watchlist:
        ch_days = days_override if days_override is not None else entry.days

        # ── Discovery ─────────────────────────────────────────
        videos: list[VideoInfo] | None = None
        with console.status(
            f"  {entry.name}  [dim]checking past {ch_days}d[/dim]",
            spinner="dots",
        ):
            try:
                videos = discover_videos(
                    entry.url,
                    days=ch_days,
                    include_shorts=shorts,
                    quiet=True,
                )
            except Exception as exc:
                console.print(
                    f"  [{_ACCENT}]{entry.name}[/{_ACCENT}]  [red]discovery failed: {exc}[/red]"
                )

        if videos is None:
            continue

        state = ChannelState(config.channel_dir(entry.topic, entry.name) / "state.json")
        new_vids = [v for v in videos if not state.is_processed(v.video_id)]
        if limit:
            new_vids = new_vids[:limit]

        if not new_vids:
            total = len(videos)
            console.print(
                f"  [{_ACCENT}]{entry.name}[/{_ACCENT}]  [dim]up to date"
                f"  ({total} checked, past {ch_days}d)[/dim]"
            )
            # Single-channel catch-up: show latest insights inline
            if channel:
                _show_latest_insights(config, entry.topic, entry.name, limit=3)
            continue

        # ── Show what we found ────────────────────────────────
        console.print(f"  [{_ACCENT}]{entry.name}[/{_ACCENT}]  {len(new_vids)} new")
        for v in new_vids[:5]:
            console.print(f"    [dim]{v.title[:65]}[/dim]")
        if len(new_vids) > 5:
            console.print(f"    [dim]...and {len(new_vids) - 5} more[/dim]")

        if dry_run:
            scan_count = sum(1 for v in new_vids if v.duration > SHORTS_THRESHOLD)
            short_count = sum(1 for v in new_vids if v.duration <= SHORTS_THRESHOLD)
            display_estimate(
                scan_videos=scan_count,
                shorts=short_count,
                console=console,
            )
            continue

        # ── Process each video ────────────────────────────────
        scan_count = sum(1 for v in new_vids if v.duration > SHORTS_THRESHOLD)
        short_count = sum(1 for v in new_vids if v.duration <= SHORTS_THRESHOLD)
        projected_batch_cost = estimate_routed_video_workflow_cost(
            scan_videos=scan_count,
            shorts=short_count,
            synthesis_calls=1,
        )
        projected_total = (summary.estimated_cost or 0.0) + projected_batch_cost
        enforce_projected_workflow_budget(config, "catch-up", projected_total)
        summary.estimated_cost = projected_total

        _ensure_channel_context(entry.topic, entry.name, new_vids, config, tracker)
        eta = ETATracker(total=len(new_vids))

        for i, vid in enumerate(new_vids, 1):
            title = vid.title[:55] if len(vid.title) > 55 else vid.title
            eta_hint = f"  [dim]{eta.eta_str}[/dim]" if eta.eta_str else ""
            console.print(
                f"    [{i}/{len(new_vids)}] {title}"
                f"  [dim]{_duration_str(vid.duration)}[/dim]{eta_hint}"
            )
            _process_video(
                entry.topic,
                entry.name,
                vid,
                config,
                tracker,
                summary,
                state=state,
                analysis_mode="scan",
                custom_instructions=entry.active_instructions,
                eta=eta,
            )

        # ── Synthesize ────────────────────────────────────────
        with console.status(
            f"    [dim]synthesizing {entry.name}[/dim]",
            spinner="dots",
        ):
            try:
                synthesize_channel(entry.topic, entry.name, config, tracker=tracker)
                synth_file = find_artifact(
                    config.channel_dir(entry.topic, entry.name),
                    "synthesis",
                    identity=f"{entry.topic}_{entry.name}",
                )
                cli_shared.record_output_or_issue(
                    summary,
                    synth_file,
                    stage="channel-synthesis",
                    context=f"{entry.topic}/{entry.name}",
                    details={"topic": entry.topic, "channel": entry.name},
                    missing_message="No synthesis output written",
                )
            except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
                raise
            except Exception as e:
                console.print(f"    [red]synthesis failed: {e}[/red]")
                cli_shared.record_exception_issue(
                    summary,
                    stage="channel-synthesis",
                    exc=e,
                    context=f"{entry.topic}/{entry.name}",
                    details={"topic": entry.topic, "channel": entry.name},
                )

        topics_touched.add(entry.topic)

    # Synthesize each topic. Use a distinct loop variable: rebinding `topic`
    # here would clobber the `--topic` filter that `_print_goal_refreshes`
    # reads below, silently narrowing the goal-refresh output to one topic.
    for touched in topics_touched:
        with console.status(
            f"  [dim]synthesizing topic '{touched}'[/dim]",
            spinner="dots",
        ):
            try:
                synthesize_topic(touched, config, tracker=tracker)
                topic_synth = find_artifact(
                    config.topic_dir(touched),
                    "topic_synthesis",
                    identity=touched,
                )
                cli_shared.record_output_or_issue(
                    summary,
                    topic_synth,
                    stage="topic-synthesis",
                    context=touched,
                    details={"topic": touched},
                    missing_message="No topic synthesis output written",
                )
            except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
                raise
            except Exception as e:
                console.print(f"  [red]topic synthesis failed: {e}[/red]")
                cli_shared.record_exception_issue(
                    summary,
                    stage="topic-synthesis",
                    exc=e,
                    context=touched,
                    details={"topic": touched},
                )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    # Single-channel catch-up with new videos: show the new insights inline
    if channel and topics_touched:
        entry_match = [e for e in lib.get_watchlist() if e.name.lower() == channel.lower()]
        if entry_match:
            _show_latest_insights(config, entry_match[0].topic, entry_match[0].name, limit=5)
    elif topics_touched:
        t_example = next(iter(topics_touched))
        console.print("\n  [dim]What's next:[/dim]")
        console.print(
            f"  [dim]  distill show {t_example}                       View video insights[/dim]"
        )
        console.print(
            f"  [dim]  distill synthesis {t_example}                  Read the synthesis[/dim]"
        )
        console.print("  [dim]  distill costs                               Review spending[/dim]")

    # Goal-driven topics refresh on the same cadence: surface the exact
    # preview command per saved goal (spend surfaced, never auto-committed;
    # re-runs are convergent, so a refresh only shows what's new).
    _print_goal_refreshes(config, topic_filter=topic)


def register(app: typer.Typer) -> None:
    """Attach the watch sub-app and catch-up command to the given Typer app."""
    app.add_typer(watch_app, name="watch")
    app.command(name="catch-up", rich_help_panel="Watch")(catch_up)
