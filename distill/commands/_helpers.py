# ruff: noqa: I001  -- bootstrap must import before rich/typer to set UTF-8 stdio
"""Cross-command UI helpers, shared console, and video-processing utilities.

Migrated from ``distill/cli_shared.py`` during the 0.3 → 0.4 restructure.
All public names that were importable from ``distill.cli_shared`` are
re-exported here so that both old and new import paths work.
"""

import json
import os
import shutil
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

# Side-effect import: reconfigures stdout/stderr to UTF-8 *before* rich.Console
# is constructed below or any other distill module creates its own Console.
# Required for Windows cp1252 consoles to render the preflight banner without
# raising UnicodeEncodeError. Don't move this lower.
from distill import _bootstrap  # noqa: F401  -- imported for stdio side effect

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

from distill.pipeline.analysis.video import (
    analyze_scan,
    analyze_short,
    analyze_video,
    generate_channel_context,
)
from distill.library.paths import (
    base_frontmatter,
    find_artifact,
    sanitize_path_component,
    slugify_title,
    tags_for,
    write_markdown_artifact,
)
from distill.config import DistillConfig
from distill.library import Library
from distill.library.intent import CorpusIntent, load_intent, make_intent, save_intent
from distill.pipeline.costs import CostTracker, save_run_log
from distill.library.state import ChannelState
from distill.pipeline.summary import ETATracker, RunSummary, VideoResult
from distill.ingestors.youtube.transcripts import get_transcript

if TYPE_CHECKING:
    from distill.ingestors.youtube.discovery import VideoInfo

__all__ = [
    "SHORTS_THRESHOLD",
    "_apply_cost_mode_override",
    "_apply_output_mode",
    "_apply_verify_override",
    "_complete_topic_watch_names",
    "_complete_topics",
    "_complete_watched_channels",
    "_persist_lens",
    "_truncate_channel_list",
    "console",
    "duration_str",
    "ensure_channel_context",
    "err_console",
    "format_date",
    "get_config",
    "output_path",
    "print_markdown_safely",
    "print_text_safely",
    "process_video",
    "record_exception_issue",
    "record_output_or_issue",
    "require_api_key",
    "require_model",
    "resolve_intent",
    "resolve_video_channel_name",
    "run_preflight",
    "run_scope_report",
    "safe_console_text",
    "strip_frontmatter",
    "topic_from_query",
    "tty_confirm",
    "tty_prompt",
    "write_video_metadata",
]

# Shorts are <=3 minutes; use lightweight single-pass analysis.
# YouTube Shorts are nominally <=60s but metadata often reports 75-95s.
# Anything under 3 minutes is too thin for 2-pass deep analysis.
SHORTS_THRESHOLD = 180

# The one shared human-output console, imported (not constructed) so every
# module prints through the same object -- this is what lets --json redirect all
# human output to stderr at once. Re-exported here for the legacy
# ``cli_shared.console`` / ``_helpers.console`` import paths and monkeypatch
# targets.
from distill._console import console, err_console  # noqa: E402
from distill.preflight import preflight_ytdlp  # noqa: E402


def get_config() -> DistillConfig:
    """Load ``.env`` and build the runtime config.

    The cross-command config accessor. Lives here (a foundation helpers module
    with no upward imports) rather than in the `_logic` monolith so command
    modules can obtain config without importing `_logic` -- the enabler for
    decomposing `_logic.py` without import cycles (how-we-build.md remediation #1).
    """
    load_dotenv()
    return DistillConfig()


def _apply_verify_override(verify: str) -> None:
    """Apply a per-run ``--verify`` override through the process environment."""
    if not verify:
        return
    value = verify.strip().lower()
    if value not in {"warn", "strict", "off"}:
        console.print(f"[red]Unknown --verify '{verify}'.[/red] Choose: warn, strict, off.")
        raise typer.Exit(1)
    os.environ["DISTILL_VERIFY"] = value


def _apply_cost_mode_override(cost_mode: str) -> None:
    """Apply a per-run ``--cost-mode`` override through the process environment."""
    if not cost_mode:
        return
    from distill.llm.cost_policy import normalize_cost_mode

    try:
        value = normalize_cost_mode(cost_mode)
    except ValueError:
        console.print(
            f"[red]Unknown --cost-mode '{cost_mode}'.[/red] Choose: auto, no-metered, paid-ok."
        )
        raise typer.Exit(1) from None
    os.environ["DISTILL_COST_MODE"] = value


def _apply_output_mode(
    ctx: typer.Context,
    *,
    quiet: bool,
    verbose: bool,
    debug: bool,
    json_output: bool,
    model: str,
) -> bool:
    """Apply global output options and return the effective debug flag."""
    if quiet and (verbose or debug):
        console.print("[red]--quiet cannot be combined with --verbose or --debug[/red]")
        raise typer.Exit(2)

    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "json": json_output,
            "model": model,
            "quiet": quiet,
            "verbose": verbose,
        }
    )

    from distill._console import set_json_mode, set_verbosity
    from distill.commands._json import set_json_active

    set_json_mode(json_output)
    set_verbosity(quiet=quiet)
    set_json_active(json_output)
    if model:
        os.environ["DISTILL_MODEL"] = model
    return debug or verbose


def _persist_lens(config: DistillConfig, topic_name: str, fallback_goal: str, lens: str) -> None:
    """Persist an explicit ``--lens`` choice without clobbering existing intent."""
    existing = load_intent(config.topic_dir(topic_name))
    save_intent(
        config.topic_dir(topic_name),
        make_intent(
            goal=existing.goal if existing and existing.goal else fallback_goal,
            lens=lens,
            audience=existing.audience if existing else "",
            rigor=existing.rigor if existing else "",
            budget_usd=existing.budget_usd if existing else None,
        ),
    )


def _complete_watched_channels(incomplete: str) -> list[str]:
    """Autocomplete for watched channel names."""
    try:
        lib = Library(get_config())
        return [
            e.name for e in lib.get_watchlist() if e.name.lower().startswith(incomplete.lower())
        ]
    except Exception:
        return []


def _complete_topic_watch_names(incomplete: str) -> list[str]:
    """Autocomplete for topic-watch names."""
    try:
        lib = Library(get_config())
        return [
            e.name
            for e in lib.get_topic_watchlist()
            if e.name.lower().startswith(incomplete.lower())
        ]
    except Exception:
        return []


def _complete_topics(incomplete: str) -> list[str]:
    """Autocomplete for topic names."""
    try:
        lib = Library(get_config())
        return [t for t in lib.get_topics() if t.lower().startswith(incomplete.lower())]
    except Exception:
        return []


def _file_link(path: Path) -> str:
    """Return a clickable ``file://`` link for terminals that support it."""
    resolved = path.resolve()
    uri = resolved.as_uri() if hasattr(resolved, "as_uri") else f"file:///{resolved}"
    return f"[link={uri}]{resolved}[/link]"


file_link = _file_link


def _detect_ramp_source(target: str) -> str:
    """Classify a ramp-up target into the workflow that should ingest it.

    Structural dispatch on the literal shape of the argument (an existing path,
    an arxiv URL, a YouTube URL, any other URL, or a bare query) — ground truth,
    not a semantic judgment, so it stays a deterministic rule.
    """
    target_path = Path(target)
    if target_path.exists():
        return "website-batch"
    lowered = target.lower()
    if lowered == "arxiv.org" or lowered.startswith(("arxiv.org/", "www.arxiv.org/")):
        return "paper"
    if lowered.startswith("http://") or lowered.startswith("https://"):
        host = (urlparse(target).hostname or "").lower()
        if _host_matches(host, "arxiv.org"):
            return "paper"
        if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
            return "youtube-url"
        return "website"
    return "youtube-query"


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _isatty() -> bool:
    """Whether stdin is an interactive terminal. Indirected so it can be
    forced in tests (CliRunner swaps ``sys.stdin`` for a non-TTY stream)."""
    try:
        return sys.stdin.isatty()
    except (ValueError, OSError):  # closed/detached stdin
        return False


def tty_confirm(message: str, *, default: bool = False) -> bool:
    """``typer.confirm`` that never blocks in a non-interactive context.

    A loop runner or agent shell has no TTY on stdin; calling ``typer.confirm``
    there raises an abort on EOF instead of degrading. This returns *default*
    when stdin is not a TTY (and, when that default would block an action,
    prints the flag to pass), so unattended runs fail predictably rather than
    hanging or crashing. Pass ``--yes`` upstream to skip the gate entirely.
    """
    if not _isatty():
        if not default:
            console.print("[dim]Non-interactive (no TTY): pass --yes to proceed.[/dim]")
        return default
    return typer.confirm(message, default=default)


def tty_prompt(message: str, *, default: str, non_tty_default: str | None = None) -> str:
    """``typer.prompt`` with a safe non-interactive fallback.

    Interactive menus (the audit action menu, discover sizing) must resolve
    under a loop/agent rather than aborting on EOF. ``default`` is the
    interactive default (what pressing enter selects); ``non_tty_default``, when
    given, is what to return with no TTY -- use it where the interactive default
    would *act* (e.g. spend) but the safe unattended choice is to cancel.
    """
    if not _isatty():
        return non_tty_default if non_tty_default is not None else default
    return typer.prompt(message, default=default)


def format_date(date_str: str) -> str:
    """Format YYYYMMDD or ISO date to readable format."""
    if not date_str:
        return "Unknown"
    try:
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%b %d, %Y %I:%M %p")
        if len(date_str) == 8:
            dt = datetime.strptime(date_str, "%Y%m%d")
            return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        pass
    return date_str


def _truncate_channel_list(names: list[str], max_width: int, extra_count: int = 0) -> str:
    """Build a comma-separated channel list that fits within max_width."""
    if not names:
        return ""
    result = names[0]
    shown = 1
    for name in names[1:]:
        candidate = result + ", " + name
        if len(candidate) > max_width:
            break
        result = candidate
        shown += 1
    remaining = len(names) - shown + extra_count
    if remaining > 0:
        result += f" +{remaining} more"
    return result


def duration_str(seconds: int | float | None) -> str:
    """Format seconds to human readable duration."""
    if seconds is None or not isinstance(seconds, (int, float)):
        return "?"
    seconds = int(seconds)
    if seconds < 0:
        return "?"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining = minutes % 60
    return f"{hours}h {remaining}m"


def output_path(config: DistillConfig, filename: str) -> Path:
    """Return a path inside the output/ folder, creating it if needed."""
    out_dir = config.library_dir.parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_filename = sanitize_path_component(str(filename)).lstrip(". ") or "untitled"
    return out_dir / safe_filename


def topic_from_query(query: str) -> str:
    """Derive a stable topic slug from a learning query."""
    slug = slugify_title(query, max_len=40)
    return "research" if slug == "untitled" else slug


def write_video_metadata(
    vid_dir: Path, video, channel_name: str = "", analysis_mode: str = "full"
) -> None:
    meta = {
        "video_id": video.video_id,
        "title": video.title,
        "upload_date": video.upload_date,
        "duration": video.duration,
        "url": video.url,
        "channel": getattr(video, "channel_name", "") or channel_name or "",
        "analysis_mode": analysis_mode,
    }
    (vid_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def require_api_key(value: str | object, message: str) -> None:
    if not value:
        console.print(f"[red]{message}[/red]")
        raise typer.Exit(1)


def require_model(workload: str = "", hint: str = "") -> None:
    """Exit cleanly unless a model is configured for ``workload``.

    The "use what they have" replacement for ``require_api_key(config.xai_api_key,
    ...)``: a keyless local provider (Ollama / LM Studio) satisfies it, so a
    local-only user is not blocked from a workload their own model can serve. Only
    use ``require_api_key`` directly where a *specific* cloud key is genuinely
    required (e.g. Grok speech-to-text, a grok-only eval judge).
    """
    from distill.llm.availability import model_available

    if model_available(workload):
        return
    target = f" for {workload}" if workload else ""
    extra = f" {hint}" if hint else ""
    console.print(
        f"[red]No model configured{target}.[/red] Set a cloud key "
        f"(XAI_API_KEY / GEMINI_API_KEY) or a local provider (DISTILL_PROVIDER=ollama)."
        f"{extra}"
    )
    raise typer.Exit(1)


def strip_frontmatter(content: str) -> str:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


def safe_console_text(console: Console, text: str) -> str:
    """Return a plain-text fallback that is safe on legacy Windows consoles."""
    del console
    return text.encode("ascii", errors="replace").decode("ascii")


def print_text_safely(console: Console, text: str) -> None:
    """Print plain text without letting terminal encoding kill the command."""
    try:
        console.print(text, markup=False)
    except UnicodeEncodeError:
        console.print(safe_console_text(console, text), markup=False)


def print_markdown_safely(
    console: Console,
    content: str,
    *,
    summary: RunSummary | None = None,
    stage: str = "render",
    context: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """Render markdown when safe, otherwise fall back to console-safe plain text."""
    if getattr(console, "legacy_windows", False):
        print_text_safely(console, safe_console_text(console, content))
        return
    try:
        console.print(Markdown(content))
    except Exception as exc:
        fallback_details = dict(details or {})
        fallback_details.setdefault("fallback", "plain-text")
        fallback_details.setdefault("content_length", len(content))
        record_exception_issue(
            summary,
            stage=stage,
            exc=exc,
            context=context,
            details=fallback_details,
            severity="warning",
        )
        print_text_safely(console, safe_console_text(console, content))


def resolve_video_channel_name(
    url: str,
    video_info: "VideoInfo",
    fallback_resolver: Callable[[str], str],
) -> str:
    if "/@" in url:
        return fallback_resolver(url)

    channel_name = getattr(video_info, "channel_name", "") or ""
    if channel_name:
        return channel_name

    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            full_info = ydl.extract_info(url, download=False)
            if not isinstance(full_info, dict):
                return "standalone"
            candidate = full_info.get("channel") or full_info.get("uploader")
            return candidate if isinstance(candidate, str) and candidate else "standalone"
    except Exception:
        return "standalone"


def ensure_channel_context(
    topic: str,
    channel_name: str,
    videos: Sequence["VideoInfo"],
    config: DistillConfig,
    tracker: CostTracker,
) -> None:
    ctx_file = config.channel_dir(topic, channel_name) / "channel_context.md"
    ctx_file.parent.mkdir(parents=True, exist_ok=True)
    if ctx_file.exists():
        return
    console.print("Generating channel context...")
    ctx = generate_channel_context(channel_name, [v.title for v in videos], config, tracker=tracker)
    ctx_file.write_text(ctx, encoding="utf-8")
    console.print("[green]Channel context saved[/green]")


def record_output_or_issue(
    summary: RunSummary | None,
    output_path: Path,
    *,
    stage: str,
    context: str,
    details: dict[str, Any] | None = None,
    missing_message: str,
    severity: str = "error",
) -> bool:
    """Record an output if it exists, otherwise persist a structured missing-artifact issue."""
    if output_path.exists():
        if summary is not None:
            summary.add_output(output_path)
        return True
    if summary is not None:
        summary.add_issue(
            stage,
            missing_message,
            context=context,
            severity=severity,
            details=details,
        )
    return False


def record_exception_issue(
    summary: RunSummary | None,
    *,
    stage: str,
    exc: BaseException,
    context: str,
    details: dict[str, Any] | None = None,
    severity: str = "error",
) -> None:
    """Persist a structured exception-backed run issue when a summary exists."""
    if summary is not None:
        summary.add_exception(
            stage,
            exc,
            context=context,
            severity=severity,
            details=details,
        )


def _tick_video_eta(eta: ETATracker | None, start_time: float, *, success: bool) -> None:
    if eta is None:
        return
    try:
        eta.tick(start_time, success=success)
    except TypeError:
        eta.tick(start_time)


def _print_video_progress(eta: ETATracker | None, tracker: CostTracker) -> None:
    parts = ["progress"]
    if eta is not None and hasattr(eta, "completed") and hasattr(eta, "total"):
        parts.append(f"completed {eta.completed}/{eta.total}")
        parts.append(f"failed {getattr(eta, 'failed', 0)}")
    parts.append(f"spent {tracker.format_cost()}")
    console.print(f"    [dim]{' | '.join(parts)}[/dim]")


def _eta_progress_str(eta: ETATracker, step: str, tracker: CostTracker) -> str:
    try:
        return eta.progress_str(step, cost_tracker=tracker)
    except TypeError:
        return eta.progress_str(step)


def process_video(  # noqa: C901 — legacy, will refactor
    topic: str,
    channel_name: str,
    video: "VideoInfo",
    config: DistillConfig,
    tracker: CostTracker,
    summary: RunSummary,
    state: ChannelState | None = None,
    analysis_mode: str = "auto",
    custom_instructions: str = "",
    eta: ETATracker | None = None,
) -> bool:
    vid_start = eta.start() if eta else 0
    vid_dir = config.video_dir_slug(topic, channel_name, video.title, video.video_id)
    vid_dir.mkdir(parents=True, exist_ok=True)

    is_short = video.duration <= SHORTS_THRESHOLD
    if analysis_mode == "auto":
        effective_mode = "short" if is_short else "full"
    elif analysis_mode == "scan" and is_short:
        effective_mode = "short"
    else:
        effective_mode = analysis_mode

    _ACCENT = "rgb(100,149,237)"
    write_video_metadata(vid_dir, video, channel_name, analysis_mode=effective_mode)

    transcript_file = find_artifact(vid_dir, "transcript", extension="txt")
    transcript_bytes = transcript_file.stat().st_size if transcript_file.exists() else 0

    if not transcript_file.exists():
        _ts_label = (
            f"    {_eta_progress_str(eta, 'transcript', tracker)}"
            if eta
            else "    [dim]transcript[/dim]"
        )
        with console.status(_ts_label, spinner="dots"):
            success = get_transcript(
                video.url, video.video_id, transcript_file, config, tracker=tracker
            )
        if not success:
            console.print("    [red]no transcript[/red]")
            summary.add_result(
                VideoResult(
                    video.video_id,
                    video.title,
                    False,
                    error="No transcript",
                    duration=video.duration,
                )
            )
            _tick_video_eta(eta, vid_start, success=False)
            _print_video_progress(eta, tracker)
            return False
        transcript_bytes = transcript_file.stat().st_size

    transcript = transcript_file.read_text(encoding="utf-8")
    if not transcript.strip():
        console.print("    [red]empty transcript[/red]")
        summary.add_result(
            VideoResult(
                video.video_id,
                video.title,
                False,
                error="Empty transcript",
                duration=video.duration,
            )
        )
        _tick_video_eta(eta, vid_start, success=False)
        _print_video_progress(eta, tracker)
        return False

    labels = {
        "short": "quick insight",
        "scan": "scanning",
        "full": "analyzing",
    }
    step_label = labels.get(effective_mode, "analyzing")
    try:
        _an_label = (
            f"    {_eta_progress_str(eta, step_label, tracker)}"
            if eta
            else f"    [dim]{step_label}[/dim]"
        )
        _intent = load_intent(config.topic_dir(topic))
        with console.status(_an_label, spinner="dots"):
            if effective_mode == "short":
                insights = analyze_short(
                    video.title,
                    video.upload_date,
                    channel_name,
                    transcript,
                    config,
                    tracker=tracker,
                    intent=_intent,
                )
            elif effective_mode == "scan":
                insights = analyze_scan(
                    video.title,
                    video.upload_date,
                    channel_name,
                    transcript,
                    config,
                    tracker=tracker,
                    custom_instructions=custom_instructions,
                    intent=_intent,
                )
            else:
                insights = analyze_video(
                    video.title,
                    video.upload_date,
                    channel_name,
                    transcript,
                    config,
                    tracker=tracker,
                    custom_instructions=custom_instructions,
                    intent=_intent,
                )
        # Write-time verify hook: ground the insight's numeric claims against
        # the transcript receipt *before* committing it; strict mode refuses.
        from distill.library.paths import artifact_path as _artifact_path
        from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

        outcome = run_verify_hook(
            vid_dir,
            insights,
            transcript,
            mode=resolve_verify_mode(config.distill_verify),
            insight_name=_artifact_path(vid_dir, "insights").name,
            source_name=transcript_file.name,
        )
        if outcome is not None and not outcome.report.ok:
            style = "red" if outcome.refused else "yellow"
            console.print(f"    [{style}]{outcome.summary_line}[/{style}]")
        if outcome is not None and outcome.refused:
            summary.add_result(
                VideoResult(
                    video.video_id,
                    video.title,
                    False,
                    error=f"verify strict: {len(outcome.report.unsupported)} unsupported claim(s)",
                    duration=video.duration,
                )
            )
            _tick_video_eta(eta, vid_start, success=False)
            _print_video_progress(eta, tracker)
            return False

        meta = {
            "video_id": video.video_id,
            "title": video.title,
            "upload_date": video.upload_date,
            "duration": video.duration,
            "url": video.url,
            "channel": getattr(video, "channel_name", "") or channel_name or "",
            "analysis_mode": effective_mode,
        }
        insights_file = write_markdown_artifact(
            vid_dir,
            "insights",
            insights,
            frontmatter=base_frontmatter(
                artifact_type="insights",
                title=video.title,
                topic=topic,
                source="youtube",
                source_id=video.video_id,
                url=video.url,
                date=video.upload_date,
                tags=tags_for(topic, "youtube", effective_mode),
                synthesis_scope="single-source",
                extra={
                    "channel": meta["channel"],
                    "duration_seconds": video.duration,
                    "analysis_mode": effective_mode,
                    "legacy_filename": "insights.md",
                },
            ),
        )
        size = f"{transcript_bytes:,}b" if transcript_bytes else ""
        _tick_video_eta(eta, vid_start, success=True)
        console.print(f"    [{_ACCENT}]done[/{_ACCENT}]  [dim]{size}[/dim]")
        _print_video_progress(eta, tracker)
        if state is not None:
            state.mark_processed(
                video.video_id,
                video.title,
                video.upload_date,
                analysis_mode=effective_mode,
            )
        summary.add_result(
            VideoResult(
                video.video_id,
                video.title,
                True,
                is_short=is_short,
                transcript_bytes=transcript_bytes,
                duration=video.duration,
            )
        )
        summary.add_output(insights_file)
        return True
    except Exception as e:
        console.print(f"    [red]failed: {e}[/red]")
        summary.add_result(
            VideoResult(
                video.video_id,
                video.title,
                False,
                is_short=is_short,
                error=str(e),
                duration=video.duration,
            )
        )
        _tick_video_eta(eta, vid_start, success=False)
        _print_video_progress(eta, tracker)
        return False


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

    result = run_accordion_research(
        topic=topic,
        config=config,
        scope=scope,
        channel_name=channel_name,
        test=test,
        tracker=tracker,
        focus=focus,
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
        record_output_or_issue(
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

    md_out = output_path(config, f"report-{suffix}.md")
    shutil.copy2(md_source, md_out)
    console.print(f"[green]Markdown: {md_out}[/green]")
    if summary is not None:
        summary.add_output(md_out)

    docx_path = output_path(config, f"report-{suffix}.docx")

    try:
        from distill.library.export import export_report

        title = f"Strategic Intelligence: {channel_name or topic}"
        export_report(md_source, docx_path=docx_path, title=title)
        console.print(f"[green]DOCX:     {docx_path}[/green]")
        if summary is not None:
            summary.add_output(docx_path)
    except Exception as e:
        console.print(f"[yellow]DOCX export failed: {e}[/yellow]")
        record_exception_issue(
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
        save_run_log(config.library_dir, "report", report_tracker, metadata=metadata)


# ── Cross-command dispatch + startup helpers (moved from _logic, decomposition Phase 2) ──


def _preflight() -> None:
    """Non-blocking startup nudges: a stale-yt-dlp warning and a distillr
    update-available notice. Both cached daily and individually opt-out-able
    (DISTILL_NO_PREFLIGHT / DISTILL_NO_UPDATE_CHECK)."""
    try:
        library_dir = get_config().library_dir
    except Exception:
        library_dir = None
    preflight_ytdlp(console, library_dir)
    try:
        from distill.update import check_for_update

        check_for_update(console, library_dir)
    except Exception:
        # An update check must never break a command.
        pass


def run_preflight() -> None:
    """Public command startup hook for shared non-blocking preflight checks."""
    _preflight()


def _invoke_command(fn, **overrides):
    """Call a typer command as a plain Python function from another command.

    Typer command parameters default to ``typer.Option(...)`` / ``typer.Argument(...)``
    sentinel objects, which are truthy. Calling such a function directly and omitting
    any parameter leaks that sentinel into the body, so guards like ``if channel:`` or
    ``sort not in {...}`` misfire. This resolves every unspecified parameter to its real
    default (the sentinel's ``.default``) so internal dispatch behaves like the CLI.
    """
    import inspect

    kwargs = dict(overrides)  # always honor the caller's explicit values
    for name, param in inspect.signature(fn).parameters.items():
        if name in kwargs or param.kind in (
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            continue
        default = param.default
        if isinstance(default, (typer.models.OptionInfo, typer.models.ArgumentInfo)):
            kwargs[name] = default.default
        elif default is not inspect.Parameter.empty:
            kwargs[name] = default
        # A required param with no default is left out; fn raises if truly missing.
    return fn(**kwargs)


def resolve_intent(config: DistillConfig, topic: str) -> CorpusIntent | None:
    """Public intent-loading seam for command helpers."""
    return _resolve_intent(config, topic)


def _resolve_intent(config: DistillConfig, topic: str) -> CorpusIntent | None:
    """Load the persisted CorpusIntent for a topic, if any.

    Returns ``None`` when the topic has no saved intent so analysis falls back to
    the neutral default lens. A topic created via ``discover`` saves its intent,
    so subsequent ingests into that topic inherit the same lens automatically.
    """
    if not topic:
        return None
    return load_intent(config.topic_dir(topic))
