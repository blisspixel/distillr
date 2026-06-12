"""Learning command execution helpers for the Distill CLI."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from typing import Any

import typer

import distill.cli_shared as cli_shared
from distill.cli_shared import SHORTS_THRESHOLD, console
from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import find_artifact
from distill.library.state import ChannelState
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.summary import ETATracker, RunSummary, display_estimate, display_summary


def validate_learning_options(
    sort: str, limit: int, days: int, per_channel_cap: int, hours: int | None = None
) -> None:
    if sort not in {"relevance", "date"}:
        console.print("[red]--sort must be 'relevance' or 'date'[/red]")
        raise typer.Exit(1)
    if limit <= 0 or days <= 0 or per_channel_cap <= 0:
        console.print("[red]--limit, --days, and --channel-cap must be positive[/red]")
        raise typer.Exit(1)
    if hours is not None and hours <= 0:
        console.print("[red]--hours must be positive[/red]")
        raise typer.Exit(1)


def preview_learning_selection(
    query: str,
    *,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    header: str,
    table_title: str,
    get_config: Callable[[], DistillConfig],
    cost_tracker_factory: Callable[[], CostTracker],
    auto_skeptical_mode: Callable[..., bool],
    window_label: Callable[[int, int | None], str],
    select_learning_videos: Callable[..., tuple[Any, Any]],
    display_ranked_videos: Callable[..., None],
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    top_by_date: bool = False,
    rigor: str = "off",
):
    config = get_config()
    tracker = cost_tracker_factory()
    skeptical_mode = (
        auto_skeptical_mode(query, hours=hours, days=days) if skeptical is None else skeptical
    )
    console.print(f"\n[bold]{header}: {query}[/bold]")
    if top_by_date:
        # When the user asked for strict chronological semantics, the rerank /
        # skeptical knobs are bypassed entirely — say so up front so the table
        # output isn't confusing.
        console.print(
            f"[dim]Window: {window_label(days, hours)} | Best picks: {limit} | "
            f"Mode: top-by-date (no rerank) | Channel cap: {per_channel_cap}[/dim]\n"
        )
    else:
        console.print(
            f"[dim]Window: {window_label(days, hours)} | Best picks: {limit} | Candidate order: {sort} | "
            f"Channel cap: {per_channel_cap} | Rerank: {'on' if rerank else 'off'} | Skeptical: {'on' if skeptical_mode else 'off'}[/dim]\n"
        )

    effective_expand = expand and not top_by_date
    _, selected = select_learning_videos(
        query,
        config,
        tracker,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        hours=hours,
        skeptical=skeptical_mode,
        expand=effective_expand,
        top_by_date=top_by_date,
        rigor=rigor,
    )
    if not selected:
        console.print("[yellow]No recent videos matched the search criteria[/yellow]")
        raise typer.Exit(0)

    display_ranked_videos(selected, title=table_title)
    return config, tracker, selected


def run_learning_command(
    query: str,
    *,
    topic: str | None,
    days: int,
    limit: int,
    sort: str,
    per_channel_cap: int,
    shorts: bool,
    rerank: bool,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    header: str,
    get_config: Callable[[], DistillConfig],
    cost_tracker_factory: Callable[[], CostTracker],
    topic_from_query: Callable[[str], str],
    auto_skeptical_mode: Callable[..., bool],
    default_report_focus: Callable[..., str | None],
    window_label: Callable[[int, int | None], str],
    select_learning_videos: Callable[..., tuple[Any, Any]],
    display_ranked_videos: Callable[..., None],
    process_learning_selection: Callable[..., None],
    hours: int | None = None,
    skeptical: bool | None = None,
    expand: bool = True,
    focus: str | None = None,
    top_by_date: bool = False,
    post_ingest_callback: Callable[[str, CostTracker], None] | None = None,
    rigor: str = "off",
) -> None:
    config = get_config()
    if not config.xai_api_key:
        console.print("[red]XAI_API_KEY required[/red]")
        raise typer.Exit(1)

    topic_name = topic or topic_from_query(query)
    tracker = cost_tracker_factory()
    skeptical_mode = (
        auto_skeptical_mode(query, hours=hours, days=days) if skeptical is None else skeptical
    )
    report_focus = focus or default_report_focus(query, skeptical=skeptical_mode)
    console.print(f"\n[bold]{header}: {query}[/bold]")
    if top_by_date:
        console.print(
            f"[dim]Topic: {topic_name} | Window: {window_label(days, hours)} | Best picks: {limit} | "
            f"Mode: top-by-date (no rerank) | Channel cap: {per_channel_cap}[/dim]\n"
        )
    else:
        console.print(
            f"[dim]Topic: {topic_name} | Window: {window_label(days, hours)} | Best picks: {limit} | Candidate order: {sort} | "
            f"Channel cap: {per_channel_cap} | Rerank: {'on' if rerank else 'off'} | Skeptical: {'on' if skeptical_mode else 'off'}[/dim]\n"
        )
    if skeptical_mode and not top_by_date:
        console.print(
            "[yellow]Suspicion-aware discovery enabled for rumor-heavy or April 1 style coverage[/yellow]\n"
        )

    effective_expand = expand and not top_by_date
    _, selected = select_learning_videos(
        query,
        config,
        tracker,
        days=days,
        limit=limit,
        sort=sort,
        per_channel_cap=per_channel_cap,
        shorts=shorts,
        rerank=rerank,
        hours=hours,
        skeptical=skeptical_mode,
        expand=effective_expand,
        top_by_date=top_by_date,
        rigor=rigor,
    )
    if not selected:
        console.print("[yellow]No recent videos matched the search criteria[/yellow]")
        raise typer.Exit(0)

    display_ranked_videos(selected, title="Selected Learning Set")
    process_learning_selection(
        topic_name,
        config,
        tracker,
        selected,
        save=save,
        report=report,
        test=test,
        generate_brief=generate_brief,
        report_focus=report_focus,
        post_ingest_callback=post_ingest_callback,
    )


def process_learning_selection(  # noqa: C901 — legacy, will refactor
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    selected,
    *,
    save: bool,
    report: bool,
    test: bool,
    generate_brief: bool,
    library_factory: Callable[[DistillConfig], Library],
    run_summary_factory: Callable[..., RunSummary],
    output_path: Callable[[DistillConfig, str], Any],
    ensure_channel_context: Callable[..., None],
    process_video: Callable[..., Any],
    synthesize_channel: Callable[..., Any],
    synthesize_topic: Callable[..., Any],
    synthesize_corpus: Callable[..., Any],
    run_scope_report: Callable[..., None],
    generate_and_export_topic_brief: Callable[..., None],
    report_focus: str | None = None,
    post_ingest_callback: Callable[[str, CostTracker], None] | None = None,
) -> None:
    grouped = {}
    for item in selected:
        video = item.video
        channel_name = (video.channel_name or "unknown").strip() or "unknown"
        grouped.setdefault(channel_name, []).append(video)

    lib = library_factory(config)
    summary = run_summary_factory(command="learn")
    summary.set_metadata(topic=topic_name, workflow="learn", source_type="youtube")

    all_vids = [item.video for item in selected]
    full_est = sum(1 for v in all_vids if v.duration > SHORTS_THRESHOLD)
    short_est = sum(1 for v in all_vids if v.duration <= SHORTS_THRESHOLD)
    display_estimate(full_est, short_est, console=console, include_report=report)

    console.print(f"  Processing {len(selected)} best-pick videos across {len(grouped)} channels")

    for channel_name, videos in grouped.items():
        channel_url = next((v.channel_url for v in videos if v.channel_url), "")
        if save and channel_url:
            if lib.add_channel(topic_name, channel_url, channel_name):
                console.print(f"[green]Added {channel_name} to {topic_name}[/green]")
            else:
                console.print(f"[dim]{channel_name} already in {topic_name}[/dim]")
        elif save:
            console.print(
                f"[yellow]Could not resolve a stable channel URL for {channel_name}; processing without library registration[/yellow]"
            )

        console.print(f"\n[bold]Channel: {channel_name}[/bold]")
        state = ChannelState(config.channel_dir(topic_name, channel_name) / "state.json")
        ensure_channel_context(topic_name, channel_name, videos, config, tracker)
        eta = ETATracker(total=len(videos))

        for i, video in enumerate(videos, 1):
            if state.is_processed(video.video_id):
                console.print(f"  [{i}/{len(videos)}] [dim]Already done: {video.title[:60]}[/dim]")
                continue

            eta_hint = f"  [dim]{eta.eta_str}[/dim]" if eta.eta_str else ""
            console.print(f"\n  [{i}/{len(videos)}] [bold]{video.title}[/bold]")
            console.print(
                f"  [dim]{cli_shared.format_date(video.upload_date)} | {cli_shared.duration_str(video.duration)}[/dim]{eta_hint}"
            )
            try:
                process_video(
                    topic_name,
                    channel_name,
                    video,
                    config,
                    tracker,
                    summary,
                    state=state,
                    eta=eta,
                )
            except BudgetExceededError:
                raise  # the spend cap is a hard stop, never a per-item issue
            except Exception as exc:
                # One crashed video must not kill the channel sweep: record it,
                # move on; state.json leaves it unprocessed so a re-run retries
                # exactly this item.
                console.print(f"  [red]failed: {exc}[/red]")
                cli_shared.record_exception_issue(
                    summary,
                    stage="video-analysis",
                    exc=exc,
                    context=video.title,
                    details={"topic": topic_name, "channel": channel_name},
                )

        console.print(f"\nSynthesizing {channel_name}...")
        try:
            synthesize_channel(topic_name, channel_name, config, tracker=tracker)
            synth_file = find_artifact(
                config.channel_dir(topic_name, channel_name),
                "synthesis",
                identity=f"{topic_name}_{channel_name}",
            )
            cli_shared.record_output_or_issue(
                summary,
                synth_file,
                stage="channel-synthesis",
                context=f"{topic_name}/{channel_name}",
                details={"topic": topic_name, "channel": channel_name},
                missing_message="No synthesis output written",
            )
        except Exception as e:
            console.print(f"[red]Synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="channel-synthesis",
                exc=e,
                context=f"{topic_name}/{channel_name}",
                details={"topic": topic_name, "channel": channel_name},
            )

    if grouped:
        console.print(f"\nSynthesizing topic '{topic_name}'...")
        try:
            synthesize_topic(topic_name, config, tracker=tracker)
            topic_synth = find_artifact(
                config.topic_dir(topic_name),
                "topic_synthesis",
                identity=topic_name,
            )
            cli_shared.record_output_or_issue(
                summary,
                topic_synth,
                stage="topic-synthesis",
                context=topic_name,
                details={"topic": topic_name},
                missing_message="No topic synthesis output written",
            )
        except Exception as e:
            console.print(f"[red]Topic synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="topic-synthesis",
                exc=e,
                context=topic_name,
                details={"topic": topic_name},
            )
    try:
        corpus_synth = synthesize_corpus(topic_name, config, tracker=tracker)
        if corpus_synth:
            summary.add_output(
                find_artifact(
                    config.topic_dir(topic_name),
                    "corpus_synthesis",
                    identity=topic_name,
                )
            )
    except Exception as e:
        cli_shared.record_exception_issue(
            summary,
            stage="corpus-synthesis",
            exc=e,
            context=topic_name,
            details={"topic": topic_name},
        )

    # Post-ingest hook lets callers (e.g. `distill latest --concepts`)
    # attach extra LLM work to the same tracker so spend is captured in
    # the run's cost log instead of going untracked.
    if post_ingest_callback is not None:
        try:
            post_ingest_callback(topic_name, tracker)
        except Exception as e:
            cli_shared.record_exception_issue(
                summary,
                stage="post-ingest-callback",
                exc=e,
                context=topic_name,
                details={"topic": topic_name},
            )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)

    if not generate_brief and not report:
        console.print("\n  [dim]What's next:[/dim]")
        console.print(
            f"  [dim]  distill show {topic_name}                    View video insights[/dim]"
        )
        console.print(
            f"  [dim]  distill synthesis {topic_name}               Read the synthesis[/dim]"
        )
        console.print(
            f"  [dim]  distill report {topic_name}                  Deep research report[/dim]"
        )
        console.print(
            f"  [dim]  distill videos {topic_name}                  List all processed videos[/dim]"
        )

    if generate_brief:
        generate_and_export_topic_brief(topic_name, config, tracker)

    if report:
        run_scope_report(
            topic_name,
            config,
            tracker,
            scope="topic",
            test=test,
            summary=summary,
            focus=report_focus,
        )


def generate_and_export_topic_brief(
    topic_name: str,
    config: DistillConfig,
    tracker: CostTracker,
    *,
    generate_topic_brief: Callable[..., Any],
    output_path: Callable[[DistillConfig, str], Any],
):
    console.print(f"\n[bold cyan]Generating brief for {topic_name}...[/bold cyan]")
    brief_path = generate_topic_brief(topic_name, config, tracker=tracker)
    if not brief_path:
        console.print("[yellow]Brief generation did not produce content[/yellow]")
        return

    output_copy = output_path(config, f"brief-{topic_name}.md")
    shutil.copy2(brief_path, output_copy)
    console.print(f"[green]Brief:   {brief_path}[/green]")
    console.print(f"[green]Output:  {output_copy}[/green]")
