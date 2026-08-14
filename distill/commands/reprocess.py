# pyright: strict
"""The `distill resynthesize` + `distill reanalyze` corpus-reprocessing commands.

Re-run synthesis (resynthesize: rebuild a topic/channel/corpus synthesis, e.g. in
a new register style) or re-run analysis (reanalyze: re-extract insights over a
topic's existing sources) without re-ingesting. Both are Maintain-panel
maintenance verbs over an existing corpus. Registered via register() from
distill.cli.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import typer

import distill.cli_shared as cli_shared
from distill._console import console
from distill.cli_shared import is_youtube_short
from distill.cli_shared import require_model as _require_model
from distill.commands._helpers import (
    _complete_topics,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
)
from distill.commands._helpers import format_date as _format_date
from distill.commands._helpers import (
    process_video as _process_video,
)
from distill.commands._json import ExitCode
from distill.commands._topic_resolution import (
    resolve_required_topic_for_channel as _resolve_required_topic_for_channel,
)
from distill.config import DistillConfig
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library import ChannelInfo, Library
from distill.library.paths import find_artifact
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.llm.router import RouterConfig
from distill.pipeline.costs import (
    BudgetExceededError,
    estimate_routed_video_workflow_cost,
    estimate_run_cost,
)
from distill.pipeline.summary import (
    RunSummary,
    display_estimate,
    display_summary,
)
from distill.pipeline.synthesis.corpus import has_two_pass_synthesis_inputs, synthesize_corpus
from distill.pipeline.synthesis.topic import synthesize_channel, synthesize_topic

__all__ = ["reanalyze", "register", "resynthesize"]

type _ReanalysisVideo = tuple[str, Path, dict[str, Any], bool]


def _resolve_resynthesis_scope(
    config: DistillConfig,
    topic: str,
    channel: str | None,
    *,
    two_pass: bool,
) -> tuple[str, list[ChannelInfo]]:
    """Resolve channels while allowing evidence-backed two-pass-only topics."""
    lib = Library(config)
    resolved_topic, resolved_channel = _resolve_required_topic_for_channel(lib, topic, channel)
    channels = lib.get_channels(resolved_topic)

    if resolved_channel:
        channels = [ch for ch in channels if ch.name == resolved_channel]
        if not channels:
            console.print(
                f"[red]Channel '{resolved_channel}' not found in topic '{resolved_topic}'[/red]"
            )
            raise typer.Exit(code=ExitCode.NOT_FOUND)
    elif not channels:
        if not two_pass:
            console.print(f"[red]No channels found for topic '{resolved_topic}'[/red]")
            raise typer.Exit(code=ExitCode.NOT_FOUND)
        if not has_two_pass_synthesis_inputs(resolved_topic, config):
            console.print(
                "[red]No insight artifacts or extracted claims found for topic "
                f"'{resolved_topic}'[/red]"
            )
            raise typer.Exit(code=ExitCode.NOT_FOUND)

    return resolved_topic, channels


def _read_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, RecursionError, UnicodeError, ValueError):
        return {}
    if isinstance(data, dict):
        return cast("dict[str, Any]", data)
    return {}


def _metadata_str(metadata: dict[str, Any], key: str, default: str = "") -> str:
    value = metadata.get(key, default)
    return value if isinstance(value, str) else default


def _metadata_int(metadata: dict[str, Any], key: str, default: int = 0) -> int:
    value = metadata.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def resynthesize(  # noqa: C901 - orchestration branches mirror independent synthesis scopes
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Limit to one channel"),
    style: str = typer.Option(
        "",
        "--style",
        help="Topic-synthesis register: exec | pop | landscape | disagreements-only (default: standard).",
    ),
    two_pass: bool = typer.Option(
        False,
        "--two-pass",
        help="Claim-based corpus synthesis: extract claims to claims.jsonl, then synthesize over the claim set (opt-in).",
    ),
) -> None:
    """Regenerate synthesis from existing insights -- no re-analysis.

    Rebuilds channel synthesis and topic synthesis from existing insight artifacts
    already on disk. Fast and cheap -- useful after manual edits or to refresh
    synthesis with updated prompts. ``--style`` selects an emphasis register for
    the topic synthesis. With ``--two-pass``, topics do not need YouTube channels:
    every per-source insight under the topic participates recursively.

    ``--two-pass`` adds a claim-based corpus synthesis: it extracts atomic claims
    from every insight into a per-topic ``claims.jsonl`` (one cheap LLM call per
    new source), then synthesizes over the claim set so the result clusters
    claims, names contradictions, and cites each statement back to its source.
    Opt-in; single-pass synthesis remains the default.

    Examples:
      distill resynthesize ai
      distill resynthesize ai --style exec
      distill resynthesize ai --two-pass
      distill resynthesize NateBJones
    """
    from distill.prompts.synthesis import STYLE_NAMES

    if style and style not in STYLE_NAMES:
        console.print(
            f"[red]Unknown --style '{style}'.[/red] Choose one of: {', '.join(STYLE_NAMES)}."
        )
        raise typer.Exit(2)

    config = get_config()
    topic, channels = _resolve_resynthesis_scope(config, topic, channel, two_pass=two_pass)

    _require_model()

    # synthesis_calls = 1 per channel + 1 for topic
    num_calls = len(channels) + 1 if channels else 0
    if two_pass:
        from distill.claims.pipeline import pending_claim_extraction_count

        claim_extraction_calls = pending_claim_extraction_count(config.topic_dir(topic))
    else:
        claim_extraction_calls = 0
    projected_cost = estimate_routed_video_workflow_cost(
        synthesis_calls=num_calls + (1 if two_pass else 0),
        claim_extraction_calls=claim_extraction_calls,
    )
    enforce_projected_workflow_budget(config, "resynthesize", projected_cost)
    display_estimate(
        synthesis_calls=num_calls + (1 if two_pass else 0),
        claim_extraction_calls=claim_extraction_calls,
        console=console,
    )

    tracker = budgeted_cost_tracker(config, "resynthesize")
    summary = RunSummary(command="resynthesize")
    summary.estimated_cost = projected_cost

    for ch in channels:
        console.print(f"  Synthesizing [bold]{ch.name}[/bold]...")
        try:
            synthesize_channel(topic, ch.name, config, tracker=tracker)
            synth_file = find_artifact(
                config.channel_dir(topic, ch.name),
                "synthesis",
                identity=f"{topic}_{ch.name}",
            )
            ok = cli_shared.record_output_or_issue(
                summary,
                synth_file,
                stage="channel-synthesis",
                context=f"{topic}/{ch.name}",
                details={"topic": topic, "channel": ch.name},
                missing_message="No synthesis output written",
            )
            console.print("  [dim]done[/dim]" if ok else "  [yellow]no synthesis output[/yellow]")
        except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
            raise
        except Exception as e:
            console.print(f"  [red]Failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="channel-synthesis",
                exc=e,
                context=f"{topic}/{ch.name}",
                details={"topic": topic, "channel": ch.name},
            )

    if channels:
        console.print(f"  Synthesizing topic [bold]{topic}[/bold]...")
        try:
            synthesize_topic(topic, config, tracker=tracker, style=style)
            topic_synth = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
            ok = cli_shared.record_output_or_issue(
                summary,
                topic_synth,
                stage="topic-synthesis",
                context=topic,
                details={"topic": topic},
                missing_message="No topic synthesis output written",
            )
            console.print(
                "  [dim]done[/dim]" if ok else "  [yellow]no topic synthesis output[/yellow]"
            )
        except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
            raise
        except Exception as e:
            console.print(f"  [red]Topic synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="topic-synthesis",
                exc=e,
                context=topic,
                details={"topic": topic},
            )

    if two_pass:
        console.print(f"  Two-pass corpus synthesis for [bold]{topic}[/bold] (claims)...")
        try:
            synthesize_corpus(topic, config, tracker=tracker, style=style, two_pass=True)
            corpus_synth = find_artifact(
                config.topic_dir(topic), "corpus_synthesis", identity=topic
            )
            ok = cli_shared.record_output_or_issue(
                summary,
                corpus_synth,
                stage="corpus-synthesis-two-pass",
                context=topic,
                details={"topic": topic, "two_pass": True},
                missing_message="No corpus synthesis output written",
            )
            console.print(
                "  [dim]done[/dim]" if ok else "  [yellow]no corpus synthesis output[/yellow]"
            )
        except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
            raise
        except Exception as e:
            console.print(f"  [red]Two-pass corpus synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="corpus-synthesis-two-pass",
                exc=e,
                context=topic,
                details={"topic": topic},
            )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


def reanalyze(  # noqa: C901 — legacy, will refactor
    topic: str = typer.Argument(help="Topic or channel name", autocompletion=_complete_topics),
    channel: str | None = typer.Option(None, "--channel", "-c", help="Limit to one channel"),
    deep: bool = typer.Option(
        False, "--deep", help="Only upgrade scan-analyzed videos to full 2-pass"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be reanalyzed"),
) -> None:
    """Re-run configured-model analysis on transcripts, without re-downloading.

    Walks all video directories that have a transcript artifact, re-runs the
    2-pass (full) or 1-pass (Short) analysis, overwrites the insight artifact,
    then resynthesizes channel and topic.

    Use --deep to upgrade only scan-analyzed videos to full 2-pass analysis.

    Examples:
      distill reanalyze ai
      distill reanalyze NateBJones --deep
      distill reanalyze ai --dry-run
    """
    config = get_config()
    _require_model()
    lib = Library(config)
    topic, channel = _resolve_required_topic_for_channel(lib, topic, channel)

    channels = lib.get_channels(topic)
    if not channels:
        console.print(f"[red]No channels found for topic '{topic}'[/red]")
        raise typer.Exit(code=ExitCode.NOT_FOUND)
    if channel:
        channels = [ch for ch in channels if ch.name == channel]
        if not channels:
            console.print(f"[red]Channel '{channel}' not found in topic '{topic}'[/red]")
            raise typer.Exit(code=ExitCode.NOT_FOUND)

    # Scan for videos with transcripts
    all_videos: list[_ReanalysisVideo] = []
    for ch in channels:
        vdir = config.videos_dir(topic, ch.name)
        if not vdir.exists():
            continue
        for d in sorted(vdir.iterdir()):
            if not d.is_dir():
                continue
            transcript = find_artifact(d, "transcript", extension="txt")
            meta_file = d / "metadata.json"
            if not transcript.exists() or transcript.stat().st_size == 0:
                continue
            meta = _read_metadata(meta_file)
            duration = _metadata_int(meta, "duration")
            is_short = is_youtube_short(duration)
            all_videos.append((ch.name, d, meta, is_short))

    # --deep: only upgrade scan-analyzed videos to full 2-pass
    if deep:
        all_videos = [
            (ch_name, d, meta, is_s)
            for ch_name, d, meta, is_s in all_videos
            if meta.get("analysis_mode") == "scan" and not is_s
        ]

    if not all_videos:
        msg = "No scan-analyzed videos to upgrade" if deep else "No videos with transcripts found"
        console.print(f"[dim]{msg}[/dim]")
        return

    full_count = sum(1 for _, _, _, s in all_videos if not s)
    short_count = sum(1 for _, _, _, s in all_videos if s)

    if dry_run:
        console.print()
        for _ch_name, vid_dir, meta, is_short in all_videos:
            title = _metadata_str(meta, "title", vid_dir.name)[:65]
            kind = "[dim](Short)[/dim]" if is_short else ""
            date = _format_date(_metadata_str(meta, "upload_date"))
            console.print(f"  {date}  {title} {kind}")
        console.print()
        console.print(
            f"  [{full_count} full + {short_count} Shorts]  ·  "
            f"[dim]{estimate_run_cost(full_count, short_count, router_config=RouterConfig())}[/dim]"
        )
        return

    projected_cost = estimate_routed_video_workflow_cost(
        full_videos=full_count,
        shorts=short_count,
        synthesis_calls=len(channels) + 1,
    )
    enforce_projected_workflow_budget(config, "reanalyze", projected_cost)
    display_estimate(
        full_count,
        short_count,
        console=console,
        synthesis_calls=len(channels) + 1,
    )

    tracker = budgeted_cost_tracker(config, "reanalyze")
    summary = RunSummary(command="reanalyze")
    summary.estimated_cost = projected_cost
    current_channel = None

    for ch_name, vid_dir, meta, is_short in all_videos:
        if ch_name != current_channel:
            current_channel = ch_name
            console.print(f"\n  [bold]{ch_name}[/bold]")

        title = _metadata_str(meta, "title", vid_dir.name)
        video = VideoInfo(
            video_id=_metadata_str(meta, "video_id", vid_dir.name),
            title=title,
            upload_date=_metadata_str(meta, "upload_date"),
            duration=_metadata_int(meta, "duration"),
            url=_metadata_str(meta, "url"),
            channel_name=ch_name,
        )

        label = "Short" if is_short else "Analyzing"
        console.print(f"    {label}: {title[:60]}...")
        _process_video(
            topic,
            ch_name,
            video,
            config,
            tracker,
            summary,
            analysis_mode="short" if is_short else "full",
            video_dir=vid_dir,
        )

    # Resynthesize after all analysis
    for ch in channels:
        console.print(f"\n  Synthesizing {ch.name}...")
        try:
            synthesize_channel(topic, ch.name, config, tracker=tracker)
            synth_file = find_artifact(
                config.channel_dir(topic, ch.name),
                "synthesis",
                identity=f"{topic}_{ch.name}",
            )
            cli_shared.record_output_or_issue(
                summary,
                synth_file,
                stage="channel-synthesis",
                context=f"{topic}/{ch.name}",
                details={"topic": topic, "channel": ch.name},
                missing_message="No synthesis output written",
            )
        except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
            raise
        except Exception as e:
            console.print(f"  [red]Synthesis failed: {e}[/red]")
            cli_shared.record_exception_issue(
                summary,
                stage="channel-synthesis",
                exc=e,
                context=f"{topic}/{ch.name}",
                details={"topic": topic, "channel": ch.name},
            )

    console.print(f"\n  Synthesizing topic '{topic}'...")
    try:
        synthesize_topic(topic, config, tracker=tracker)
        topic_synth = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
        cli_shared.record_output_or_issue(
            summary,
            topic_synth,
            stage="topic-synthesis",
            context=topic,
            details={"topic": topic},
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
            context=topic,
            details={"topic": topic},
        )

    display_summary(summary, cost_tracker=tracker, console=console, log_dir=config.library_dir)


def register(app: typer.Typer) -> None:
    """Attach the reprocessing commands to the app (called from distill.cli)."""
    app.command(rich_help_panel="Maintain")(resynthesize)
    app.command(rich_help_panel="Maintain")(reanalyze)
