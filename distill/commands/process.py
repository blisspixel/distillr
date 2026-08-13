# pyright: strict
"""Process commands: ``video``, ``channel``, and ``run``.

Extracted from the _logic.py monolith (Process slice). These commands
transcribe and analyze YouTube videos and channels and drive the multi-step
``run`` pipeline. Shared helpers that other commands also use
(_process_video, _ensure_channel_context, _run_scope_report) live in helper
modules and are imported back here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import typer
from rich.markup import escape
from rich.panel import Panel

from distill import cli_shared
from distill.cli_shared import (
    SHORTS_THRESHOLD,
    console,
)
from distill.cli_shared import format_date as _format_date
from distill.cli_shared import print_markdown_safely as _print_markdown_safely
from distill.cli_shared import print_text_safely as _print_text_safely
from distill.cli_shared import require_model as _require_model
from distill.cli_shared import safe_console_text as _safe_console_text
from distill.cli_shared import strip_frontmatter as _strip_frontmatter
from distill.commands._helpers import (
    budgeted_cost_tracker,
    duration_str,
    enforce_projected_workflow_budget,
    file_link,
    get_config,
    run_preflight,
)
from distill.commands._helpers import (
    ensure_channel_context as _ensure_channel_context,
)
from distill.commands._helpers import (
    process_video as _process_video,
)
from distill.commands._helpers import (
    resolve_video_channel_name as _resolve_video_channel_name,
)
from distill.commands._helpers import (
    run_scope_report as _run_scope_report,
)
from distill.commands._topic_resolution import (
    resolve_required_topic_for_channel as _resolve_required_topic_for_channel,
)
from distill.config import DistillConfig
from distill.ingestors.net import url_for_diagnostic
from distill.ingestors.youtube.discovery import (
    discover_videos,
    get_video_info,
    resolve_channel_name,
)
from distill.library import Library
from distill.library.paths import find_artifact
from distill.library.state import ChannelState
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.video import (
    generate_channel_context,
)
from distill.pipeline.costs import (
    BudgetExceededError,
    estimate_routed_video_workflow_cost,
    estimate_run_cost,
)
from distill.pipeline.summary import (
    ETATracker,
    RunSummary,
    display_estimate,
    display_summary,
)
from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic
from distill.youtube_urls import (
    normalize_youtube_channel_url,
    normalize_youtube_video_url,
)

_duration_str = duration_str
_file_link = file_link
_preflight = run_preflight


def _nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _completed_video_artifacts(
    config: DistillConfig,
    topic: str,
    video_id: str,
) -> tuple[Path, Path, Path] | None:
    """Return the completed receipt pair for an exact YouTube identity."""
    channels_dir = config.topic_dir(topic) / "channels"
    if not channels_dir.exists():
        return None
    for metadata_path in sorted(channels_dir.glob("*/videos/*/metadata.json")):
        try:
            raw_metadata: object = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw_metadata, dict):
            continue
        metadata = cast("dict[str, object]", raw_metadata)
        if metadata.get("video_id") != video_id:
            continue
        video_dir = metadata_path.parent
        transcript = find_artifact(video_dir, "transcript", extension="txt")
        insights = find_artifact(video_dir, "insights")
        if _nonempty(transcript) and _nonempty(insights):
            return video_dir, transcript, insights
    return None


def _print_reused_video(
    info: object,
    channel_name: str,
    transcript_file: Path,
    insights_file: Path,
    *,
    show: bool,
) -> None:
    title = str(getattr(info, "title", "Video"))
    upload_date = str(getattr(info, "upload_date", ""))
    console.print(
        "[dim]Already complete for this video ID. Reusing existing artifacts; "
        "pass --force to reanalyze.[/dim]"
    )
    if show:
        content = _strip_frontmatter(insights_file.read_text(encoding="utf-8"))
        _print_markdown_safely(console, content)
    console.print()
    console.print(f"  transcript      {_file_link(transcript_file)}")
    console.print(f"  insights        {_file_link(insights_file)}")
    if not show:
        console.print("  [dim]Use --show to print the analysis inline[/dim]")
    console.print(f"  [dim]{title} | {_format_date(upload_date)} | {channel_name}[/dim]")


def video(
    url: str = typer.Argument(help="YouTube video URL"),
    topic: str = typer.Option("ai", "--topic", "-t", help="Topic to file under"),
    show: bool = typer.Option(
        False,
        "--show",
        help="Print the analysis inline instead of just linking transcript and insights files.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Reanalyze even when this exact video already has complete artifacts.",
    ),
):
    """Transcribe and analyze a single YouTube video.

    By default this writes transcript + analysis artifacts and keeps console output concise.
    Replays converge: an exact completed video ID is reused without a model call.
    Use --force to reanalyze it, or --show to print the existing analysis inline.
    """
    normalized_url = normalize_youtube_video_url(url)
    if not normalized_url:
        displayed_url = escape(url_for_diagnostic(url))
        console.print(f"[red]Refusing invalid YouTube video URL from {displayed_url}.[/red]")
        raise typer.Exit(2)
    url = normalized_url
    config = get_config()

    tracker = budgeted_cost_tracker(config, "video")
    summary = RunSummary(command="video")

    console.print("\n[bold]Fetching video info...[/bold]")
    info = get_video_info(url)
    if not info:
        summary.add_issue(
            "video-info",
            "Could not get video info. Check the URL.",
            context=url_for_diagnostic(url),
            details={"topic": topic},
        )
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        console.print("[red]Could not get video info. Check the URL.[/red]")
        raise typer.Exit(1)

    channel_name = _resolve_video_channel_name(url, info, resolve_channel_name)
    console.print(f"[bold]{info.title}[/bold]")
    console.print(f"[dim]{_format_date(info.upload_date)} | {_duration_str(info.duration)}[/dim]\n")

    completed = _completed_video_artifacts(config, topic, info.video_id)
    if completed is not None and not force:
        _video_dir, transcript_file, insights_file = completed
        _print_reused_video(
            info,
            channel_name,
            transcript_file,
            insights_file,
            show=show,
        )
        return

    _require_model()

    projected_cost = estimate_routed_video_workflow_cost(
        full_videos=0 if info.duration <= SHORTS_THRESHOLD else 1,
        shorts=1 if info.duration <= SHORTS_THRESHOLD else 0,
    )
    enforce_projected_workflow_budget(config, "video", projected_cost)
    summary.estimated_cost = projected_cost

    success = _process_video(topic, channel_name, info, config, tracker, summary)
    if not success:
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        raise typer.Exit(1)

    video_dir = config.video_dir_slug(topic, channel_name, info.title, info.video_id)
    transcript_file = find_artifact(video_dir, "transcript", extension="txt")
    insights_file = find_artifact(video_dir, "insights")

    try:
        console.print(
            Panel(
                _safe_console_text(
                    console,
                    f"[bold]{info.title}[/bold]\n[dim]{_format_date(info.upload_date)} | {channel_name}[/dim]",
                ),
                border_style="cyan",
            )
        )
    except Exception as exc:
        cli_shared.record_exception_issue(
            summary,
            stage="render-preview-panel",
            exc=exc,
            context=info.video_id,
            details={"channel": channel_name, "title": info.title},
            severity="warning",
        )
        _print_text_safely(
            console, f"{info.title}\n{_format_date(info.upload_date)} | {channel_name}"
        )

    if show:
        content = _strip_frontmatter(insights_file.read_text(encoding="utf-8"))
        _print_markdown_safely(
            console,
            content,
            summary=summary,
            stage="render-preview-content",
            context=info.video_id,
            details={"channel": channel_name, "title": info.title},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    console.print()
    console.print(f"  transcript      {_file_link(transcript_file)}")
    console.print(f"  insights        {_file_link(insights_file)}")
    if not show:
        console.print("  [dim]Use --show to print the analysis inline[/dim]")
    console.print(
        f"  [dim]distill synthesis {channel_name}  |  distill videos {channel_name}[/dim]"
    )


def channel_cmd(  # noqa: C901 — legacy, will refactor
    url: str = typer.Argument(help="YouTube channel URL"),
    topic: str = typer.Option("ai", "--topic", "-t", help="Topic to file under"),
    months: int | None = typer.Option(
        None, "--months", "-m", help="Lookback window in months (default: 1)"
    ),
    report: bool = typer.Option(
        False, "--report", "-r", help="Also generate a full report after processing"
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Max videos to process"),
    shorts: bool = typer.Option(
        True, "--shorts/--no-shorts", help="Include YouTube Shorts (default: yes)"
    ),
    test: bool = typer.Option(False, "--test", help="Test mode for research (cheaper)"),
):
    """Process a full YouTube channel -- discover, transcribe, analyze.

    Adds the channel to your library, discovers recent videos, gets transcripts,
    and runs 2-pass analysis on each through the configured route. Use --report
    to also generate a full report.

    Examples:
      distill channel https://www.youtube.com/@NateBJones
      distill channel https://www.youtube.com/@SecurityGuy --topic security --months 6
      distill channel https://www.youtube.com/@NateBJones --report
    """
    normalized_url = normalize_youtube_channel_url(url)
    if not normalized_url:
        displayed_url = escape(url_for_diagnostic(url))
        console.print(f"[red]Refusing invalid YouTube channel URL from {displayed_url}.[/red]")
        raise typer.Exit(2)
    url = normalized_url
    _preflight()
    config = get_config()
    _require_model()

    lookback = months if months is not None else config.distill_default_months
    name = resolve_channel_name(url)
    console.print(f"\n[bold]Channel: {name}[/bold]")
    console.print(f"[dim]Topic: {topic} | Lookback: {lookback} months[/dim]\n")

    lib = Library(config)
    if lib.add_channel(topic, url, name):
        console.print(f"[green]Added {name} to {topic}[/green]")
    else:
        console.print(f"[dim]{name} already in {topic}[/dim]")

    console.print("Discovering videos...")
    videos = discover_videos(url, lookback, include_shorts=shorts)
    console.print(f"[green]Found {len(videos)} videos[/green]")

    if limit:
        videos = videos[:limit]
        console.print(f"[dim]Limited to {limit} videos[/dim]")

    if not videos:
        console.print("[yellow]No videos found in date range[/yellow]")
        return

    state = ChannelState(config.channel_dir(topic, name) / "state.json")

    # Pre-run estimate
    new_vids = [v for v in videos if not state.is_processed(v.video_id)]
    full_est = sum(1 for v in new_vids if v.duration > SHORTS_THRESHOLD)
    short_est = sum(1 for v in new_vids if v.duration <= SHORTS_THRESHOLD)
    router_config = RouterConfig()
    ledger_estimate = estimate_routed_video_workflow_cost(
        full_videos=full_est,
        shorts=short_est,
        synthesis_calls=1,
        router_config=router_config,
    )
    projected_cost = estimate_routed_video_workflow_cost(
        full_videos=full_est,
        shorts=short_est,
        include_report=report,
        synthesis_calls=1,
        router_config=router_config,
    )
    enforce_projected_workflow_budget(config, "channel", projected_cost)

    tracker = budgeted_cost_tracker(config, "channel")
    summary = RunSummary(command="channel")
    summary.estimated_cost = ledger_estimate
    if new_vids:
        display_estimate(
            full_est,
            short_est,
            console=console,
            include_report=report,
            synthesis_calls=1,
            router_config=router_config,
        )

    _ensure_channel_context(topic, name, videos, config, tracker)
    eta = ETATracker(total=len(new_vids))

    for i, vid in enumerate(videos, 1):
        if state.is_processed(vid.video_id):
            console.print(f"  [{i}/{len(videos)}] [dim]Already done: {vid.title[:60]}[/dim]")
            continue

        eta_hint = f"  [dim]{eta.eta_str}[/dim]" if eta.eta_str else ""
        console.print(f"\n  [{i}/{len(videos)}] [bold]{vid.title}[/bold]")
        console.print(
            f"  [dim]{_format_date(vid.upload_date)} | {_duration_str(vid.duration)}[/dim]{eta_hint}"
        )
        _process_video(topic, name, vid, config, tracker, summary, state=state, eta=eta)

    console.print(f"\nSynthesizing {name}...")
    try:
        synthesize_channel(topic, name, config, tracker=tracker)
        synth_file = find_artifact(
            config.channel_dir(topic, name),
            "synthesis",
            identity=f"{topic}_{name}",
        )
        if synth_file.exists():
            summary.add_output(synth_file)
        else:
            summary.add_issue(
                "channel-synthesis", "No synthesis output written", context=f"{topic}/{name}"
            )
    except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
        raise
    except Exception as e:
        console.print(f"[red]Synthesis failed: {e}[/red]")
        summary.add_exception(
            "channel-synthesis",
            e,
            context=f"{topic}/{name}",
            details={"topic": topic, "channel": name},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    if not report:
        console.print("\n  [dim]What's next:[/dim]")
        console.print(f"  [dim]  distill show {name}                          View insights[/dim]")
        console.print(f"  [dim]  distill synthesis {name}                     Read synthesis[/dim]")
        console.print(
            f"  [dim]  distill report {name}                         Deep research report[/dim]"
        )
        console.print(
            f"  [dim]  distill watch add {videos[0].channel_url if videos and videos[0].channel_url else '<url>'}  Track this channel[/dim]"
        )

    if report:
        _run_scope_report(
            topic,
            config,
            tracker,
            scope="channel",
            channel_name=name,
            test=test,
        )


def run(  # noqa: C901 — legacy, will refactor
    topic: str | None = typer.Argument(None, help="Topic or channel name"),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Process only this channel"),
    months: int | None = typer.Option(None, "--months", "-m", help="Lookback window in months"),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Only process new videos since last run"
    ),
    all_topics: bool = typer.Option(False, "--all", help="Process all topics"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be processed"),
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Max videos to process per channel"
    ),
    shorts: bool = typer.Option(False, "--shorts", help="Also include YouTube Shorts (<60s)"),
):
    """Process videos -- discover, transcribe, and analyze."""
    config = get_config()
    lib = Library(config)
    if topic:
        topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)
    lookback = months if months is not None else config.distill_default_months

    if not topic and not all_topics:
        console.print("[red]Specify a topic or use --all[/red]")
        raise typer.Exit(1)

    if all_topics:
        topics = lib.get_topics()
    else:
        topics = [cast(str, topic)]

    tracker = budgeted_cost_tracker(config, "run")
    summary = RunSummary(command="run")
    total_new = 0
    total_analyzed = 0

    for t in topics:
        channels = lib.get_channels(t)
        if channel:
            channels = [ch for ch in channels if ch.name == channel]

        if not channels:
            console.print(f"[yellow]No channels found for topic '{t}'[/yellow]")
            continue

        console.print(f"\n[bold]Topic: {t}[/bold]")

        for ch in channels:
            console.print(f"\n[bold cyan]Channel: {ch.name}[/bold cyan]")

            # Discover videos
            console.print(f"  Discovering videos (past {lookback} months)...")
            videos = discover_videos(ch.url, lookback, include_shorts=shorts)
            console.print(f"  [green]Found {len(videos)} videos[/green]")

            # Filter already processed
            state_file = config.channel_dir(t, ch.name) / "state.json"
            state = ChannelState(state_file)

            if refresh:
                videos = [v for v in videos if not state.is_processed(v.video_id)]
                console.print(f"  [dim]{len(videos)} new since last refresh[/dim]")

            if limit:
                videos = videos[:limit]
                console.print(f"  [dim]Limited to {limit} videos[/dim]")

            if not videos:
                console.print("  [dim]Nothing new to process[/dim]")
                continue

            if dry_run:
                new_videos = [v for v in videos if not state.is_processed(v.video_id)]
                for v in videos:
                    status = "SKIP" if state.is_processed(v.video_id) else "NEW"
                    is_s = v.duration <= SHORTS_THRESHOLD
                    kind = " [dim](Short)[/dim]" if is_s else ""
                    console.print(
                        f"  [{status}] {_format_date(v.upload_date)} | {v.title} ({_duration_str(v.duration)}){kind}"
                    )
                full = sum(1 for v in new_videos if v.duration > SHORTS_THRESHOLD)
                short = sum(1 for v in new_videos if v.duration <= SHORTS_THRESHOLD)
                if new_videos:
                    console.print(
                        f"\n  {estimate_run_cost(full, short, router_config=RouterConfig())}"
                    )
                total_new += len(new_videos)
                continue

            # Pre-run estimate
            new_to_process = [v for v in videos if not state.is_processed(v.video_id)]
            full_count = sum(1 for v in new_to_process if v.duration > SHORTS_THRESHOLD)
            short_count = sum(1 for v in new_to_process if v.duration <= SHORTS_THRESHOLD)
            projected_channel_cost = estimate_routed_video_workflow_cost(
                full_videos=full_count,
                shorts=short_count,
                synthesis_calls=1,
            )
            projected_total = (summary.estimated_cost or 0.0) + projected_channel_cost
            enforce_projected_workflow_budget(config, "run", projected_total)
            summary.estimated_cost = projected_total
            if new_to_process:
                display_estimate(
                    full_count,
                    short_count,
                    console=console,
                    synthesis_calls=1,
                )

            # Generate channel context if we don't have one
            ctx_file = config.channel_dir(t, ch.name) / "channel_context.md"
            ctx_file.parent.mkdir(parents=True, exist_ok=True)
            if not ctx_file.exists():
                console.print("  Generating channel context...")
                ctx = generate_channel_context(
                    ch.name, [v.title for v in videos], config, tracker=tracker
                )
                ctx_file.write_text(ctx, encoding="utf-8")
                console.print("  [green]Saved channel context[/green]")

            # Process each video
            run_eta = ETATracker(total=len(new_to_process)) if new_to_process else None
            for i, video in enumerate(videos, 1):
                if state.is_processed(video.video_id):
                    console.print(
                        f"  [{i}/{len(videos)}] [dim]Already processed: {video.title[:60]}[/dim]"
                    )
                    continue

                run_eta_hint = (
                    f"  [dim]{run_eta.eta_str}[/dim]" if run_eta and run_eta.eta_str else ""
                )
                console.print(f"\n  [{i}/{len(videos)}] [bold]{video.title}[/bold]")
                console.print(
                    f"  [dim]{_format_date(video.upload_date)} | {_duration_str(video.duration)}[/dim]{run_eta_hint}"
                )

                if _process_video(
                    t,
                    ch.name,
                    video,
                    config,
                    tracker,
                    summary,
                    state=state,
                    eta=run_eta,
                ):
                    total_analyzed += 1

            # Channel synthesis
            console.print(f"\n  Synthesizing channel: {ch.name}...")
            try:
                synthesize_channel(t, ch.name, config, tracker=tracker)
                synth_file = find_artifact(
                    config.channel_dir(t, ch.name),
                    "synthesis",
                    identity=f"{t}_{ch.name}",
                )
                cli_shared.record_output_or_issue(
                    summary,
                    synth_file,
                    stage="channel-synthesis",
                    context=f"{t}/{ch.name}",
                    details={"topic": t, "channel": ch.name},
                    missing_message="No synthesis output written",
                )
            except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
                raise
            except Exception as e:
                console.print(f"  [red]Channel synthesis failed: {e}[/red]")
                cli_shared.record_exception_issue(
                    summary,
                    stage="channel-synthesis",
                    exc=e,
                    context=f"{t}/{ch.name}",
                    details={"topic": t, "channel": ch.name},
                )

        if dry_run:
            continue

        # Topic synthesis
        projected_topic_cost = estimate_routed_video_workflow_cost(synthesis_calls=1)
        projected_total = (summary.estimated_cost or 0.0) + projected_topic_cost
        enforce_projected_workflow_budget(config, "run", projected_total)
        summary.estimated_cost = projected_total
        try:
            synthesize_topic(t, config, tracker=tracker)
            topic_synth = find_artifact(config.topic_dir(t), "topic_synthesis", identity=t)
            cli_shared.record_output_or_issue(
                summary,
                topic_synth,
                stage="topic-synthesis",
                context=t,
                details={"topic": t},
                missing_message="No topic synthesis output written",
            )
        except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
            raise
        except Exception as e:
            console.print(f"  [red]Topic synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="topic-synthesis",
                exc=e,
                context=t,
                details={"topic": t},
            )

    if dry_run:
        console.print(f"\n[bold]Dry run: {total_new} videos would be processed[/bold]")
    else:
        display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)
        # `--all` against an empty library leaves `topics` empty; skip the
        # "What's next" hints rather than indexing into an empty list.
        if topics:
            t_name = topics[0]
            console.print("\n  [dim]What's next:[/dim]")
            console.print(
                f"  [dim]  distill show {t_name}                       View video insights[/dim]"
            )
            console.print(
                f"  [dim]  distill synthesis {t_name}                  Read the synthesis[/dim]"
            )
            console.print(
                f"  [dim]  distill report {t_name}                     Deep research report[/dim]"
            )


def register(app: typer.Typer) -> None:
    """Attach the Process commands to the given Typer app."""
    app.command(rich_help_panel="Process")(video)
    app.command(name="channel", rich_help_panel="Process")(channel_cmd)
    app.command(rich_help_panel="Process")(run)
