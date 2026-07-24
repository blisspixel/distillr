# ruff: noqa: I001  -- bootstrap must import before rich/typer to set UTF-8 stdio
# pyright: strict
"""Cross-command UI helpers, shared console, and video-processing utilities.

Migrated from ``distill/cli_shared.py`` during the 0.3 → 0.4 restructure.
All public names that were importable from ``distill.cli_shared`` are
re-exported here so that both old and new import paths work.
"""

import logging
import math
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

# Side-effect import: reconfigures stdout/stderr to UTF-8 *before* rich.Console
# is constructed below or any other distill module creates its own Console.
# Required for Windows cp1252 consoles to render the preflight banner without
# raising UnicodeEncodeError. Don't move this lower.
from distill import _bootstrap  # noqa: F401  -- imported for stdio side effect  # pyright: ignore[reportUnusedImport] "import applies UTF-8 stdio side effect"

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
from distill.target_safety import is_http_url, require_local_filesystem_target
from distill.commands._report_helpers import run_scope_report
from distill.commands._formatting import (
    duration_str,
    format_date,
    truncate_channel_list as _truncate_channel_list,
)
from distill.commands._video_files import (
    video_verification_evidence as _video_verification_evidence,
    write_video_metadata,
)
from distill.library import Library
from distill.library.intent import load_intent, make_intent, save_intent
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.pipeline.costs import (
    BudgetExceededError,
    CostTracker,
    ProjectedBudgetExceededError,
    save_run_log,
)


from distill.library.state import ChannelState
from distill.pipeline.summary import ETATracker, RunSummary, VideoResult
from distill.ingestors.youtube._yt_dlp_boundary import first_text, info_mapping
from distill.ingestors.youtube.safe_ytdlp import (
    YTDLP_METADATA_RESPONSE_BYTES,
    YTDLP_METADATA_TOTAL_BYTES,
    SafeYoutubeDL,
)
from distill.ingestors.youtube.transcripts import get_transcript
from distill.youtube_urls import (
    normalize_youtube_channel_url,
    normalize_youtube_video_url,
)

if TYPE_CHECKING:
    from distill.ingestors.youtube.discovery import VideoInfo


_SAFE_CLI_ARGUMENT = re.compile(r"^[A-Za-z0-9_./:+,=-]+$")
_PORTABLE_QUOTED_PUNCTUATION = frozenset(" _-./:,+'[]()")


def quote_cli_value(value: str) -> str:
    """Render one literal argument safely across POSIX, PowerShell, and cmd."""
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("command arguments cannot contain control characters")
    if value and _SAFE_CLI_ARGUMENT.fullmatch(value):
        return value
    if not value or any(
        not character.isalnum() and character not in _PORTABLE_QUOTED_PUNCTUATION
        for character in value
    ):
        raise ValueError("argument cannot be represented safely in a portable command")
    return f'"{value}"'


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
    "budgeted_cost_tracker",
    "console",
    "duration_str",
    "enforce_projected_workflow_budget",
    "ensure_channel_context",
    "err_console",
    "format_date",
    "get_config",
    "invoke_command",
    "output_path",
    "print_markdown_safely",
    "print_text_safely",
    "process_video",
    "quote_cli_value",
    "record_exception_issue",
    "record_output_or_issue",
    "require_api_key",
    "require_model",
    "resolve_intent",
    "resolve_video_channel_name",
    "run_preflight",
    "run_scope_report",
    "safe_console_text",
    "save_command_cost",
    "save_synthesis_command_cost",
    "set_command_cost_metadata",
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

logger = logging.getLogger(__name__)

# The one shared human-output console, imported (not constructed) so every
# module prints through the same object -- this is what lets --json redirect all
# human output to stderr at once. Re-exported here for the legacy
# ``cli_shared.console`` / ``_helpers.console`` import paths and monkeypatch
# targets.
from distill._console import console, err_console  # noqa: E402


def get_config() -> DistillConfig:
    """Load ``.env`` and build the runtime config.

    The cross-command config accessor. Lives here (a foundation helpers module
    with no upward imports) rather than in the `_logic` monolith so command
    modules can obtain config without importing `_logic` -- the enabler for
    decomposing `_logic.py` without import cycles (how-we-build.md remediation #1).
    """
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    return DistillConfig()


class _CommandCostTracker(CostTracker):
    """Cost tracker that persists the call which crosses a CLI budget."""

    def __init__(
        self,
        config: DistillConfig,
        command: str,
        budget: float | None,
    ) -> None:
        super().__init__(budget=budget)
        self._config = config
        self._command = command
        self._terminal_metadata: dict[str, Any] = {}
        self.budget_failure_logged = False

    def update_terminal_metadata(self, metadata: dict[str, str]) -> None:
        self._terminal_metadata.update({key: value for key, value in metadata.items() if value})

    def _check_budget(self) -> None:
        try:
            super()._check_budget()
        except BudgetExceededError:
            if not self.budget_failure_logged:
                try:
                    save_run_log(
                        self._config.library_dir,
                        self._command,
                        self,
                        metadata={
                            "workflow": self._command,
                            "terminal": "budget_exceeded",
                            **self._terminal_metadata,
                        },
                    )
                except Exception:
                    logger.debug("Failed to persist budget-exceeded cost row", exc_info=True)
                else:
                    self.budget_failure_logged = True
            raise


def budgeted_cost_tracker(config: DistillConfig, command: str) -> CostTracker:
    """Create a run tracker with the configured workflow cap, if any."""
    budget = _workflow_budget_usd(config, command)
    normalized_command = " ".join(command.split()).strip().lower()
    return _CommandCostTracker(config, normalized_command, budget)


def set_command_cost_metadata(tracker: CostTracker, **metadata: str) -> None:
    """Attach known command context to a possible terminal budget ledger row."""
    if isinstance(tracker, _CommandCostTracker):
        tracker.update_terminal_metadata(metadata)


def _workflow_budget_usd(config: DistillConfig, command: str) -> float | None:
    normalized = " ".join(command.split()).strip().lower()
    return config.cost_workflow_budgets_usd.get(normalized)


def enforce_projected_workflow_budget(
    config: DistillConfig,
    command: str,
    projected_cost: float,
) -> None:
    """Refuse a workflow before execution when its credible estimate exceeds its cap."""
    budget = _workflow_budget_usd(config, command)
    if budget is None:
        return
    if not math.isfinite(projected_cost) or projected_cost <= 0:
        return
    if projected_cost > budget:
        raise ProjectedBudgetExceededError(projected_cost, budget)


def save_command_cost(
    config: DistillConfig,
    command: str,
    tracker: CostTracker,
    *,
    metadata: dict[str, Any] | None = None,
    estimated_cost: float | None = None,
) -> None:
    """Persist a command ledger row when a direct workflow recorded usage."""
    if getattr(tracker, "budget_failure_logged", False):
        return
    if not (tracker.entries or tracker.gemini_queries or tracker.transcriptions):
        return
    save_run_log(
        config.library_dir,
        command,
        tracker,
        estimated_cost=estimated_cost,
        metadata=metadata,
    )


def save_synthesis_command_cost(
    config: DistillConfig,
    topic: str,
    channel: str | None,
    tracker: CostTracker,
    *,
    estimated_cost: float | None = None,
) -> None:
    metadata = {"topic": topic}
    if channel:
        metadata["channel"] = channel
    save_command_cost(
        config,
        "synthesis",
        tracker,
        metadata=metadata,
        estimated_cost=estimated_cost,
    )


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
    provider: str = "",
) -> bool:
    """Apply global output options and return the effective debug flag."""
    if quiet and (verbose or debug):
        console.print("[red]--quiet cannot be combined with --verbose or --debug[/red]")
        raise typer.Exit(2)

    provider_override = provider.strip()
    model_override = model.strip()
    if provider_override:
        from distill.llm.provider_catalog import normalize_provider_name

        try:
            provider_override = normalize_provider_name(provider_override)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(2) from None

    # When only --model is set, route known cloud ids to the matching provider
    # so ``distill -m gemini-3.6-flash ...`` works without a separate --provider.
    if model_override and not provider_override:
        from distill.llm.provider_catalog import infer_cloud_provider_for_model

        provider_override = infer_cloud_provider_for_model(model_override)

    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "json": json_output,
            "model": model_override,
            "provider": provider_override,
            "quiet": quiet,
            "verbose": verbose,
        }
    )

    from distill._console import set_json_mode, set_verbosity
    from distill.commands._json import set_json_active

    set_json_mode(json_output)
    set_verbosity(quiet=quiet)
    set_json_active(json_output)
    if model_override:
        os.environ["DISTILL_MODEL"] = model_override
    if provider_override:
        os.environ["DISTILL_PROVIDER"] = provider_override
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
    """Classify a ramp-up target by structural argument shape."""
    require_local_filesystem_target(target)
    lowered = target.lower()
    if lowered == "arxiv.org" or lowered.startswith(("arxiv.org/", "www.arxiv.org/")):
        return "paper"
    if is_http_url(target):
        host = (urlparse(target).hostname or "").lower()
        if _host_matches(host, "arxiv.org"):
            return "paper"
        if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
            return "youtube-url"
        return "website"
    if Path(target).exists():
        return "website-batch"
    return "youtube-query"


detect_ramp_source = _detect_ramp_source


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def isatty() -> bool:
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
    if not isatty():
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
    if not isatty():
        return non_tty_default if non_tty_default is not None else default
    return typer.prompt(message, default=default)


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
    channel_url = normalize_youtube_channel_url(url)
    if channel_url and "/@" in channel_url:
        return fallback_resolver(channel_url)

    channel_name = getattr(video_info, "channel_name", "") or ""
    if channel_name:
        return channel_name

    canonical_url = normalize_youtube_video_url(url)
    if not canonical_url:
        return "standalone"
    try:
        with SafeYoutubeDL(
            {"quiet": True, "no_warnings": True},
            metadata_byte_limit=YTDLP_METADATA_RESPONSE_BYTES,
            total_byte_limit=YTDLP_METADATA_TOTAL_BYTES,
        ) as ydl:
            full_info = info_mapping(ydl.extract_info(canonical_url, download=False))
            return (
                first_text(full_info, ("channel", "uploader"), "standalone")
                if full_info
                else "standalone"
            )
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
    *,
    video_dir: Path | None = None,
) -> bool:
    vid_start = eta.start() if eta else 0
    vid_dir = video_dir or config.video_dir_slug(topic, channel_name, video.title, video.video_id)
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
        # the fetched metadata and transcript before committing it. Metadata is
        # evidence for facts the analysis prompt receives outside the transcript,
        # such as a video's upload year; strict mode still refuses unsupported
        # claims.
        from distill.library.paths import artifact_path as _artifact_path
        from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

        verification_evidence = _video_verification_evidence(
            video,
            channel_name,
            transcript,
            analysis_mode=effective_mode,
        )
        outcome = run_verify_hook(
            vid_dir,
            insights,
            verification_evidence,
            mode=resolve_verify_mode(config.distill_verify),
            insight_name=_artifact_path(vid_dir, "insights").name,
            source_name=(
                f"metadata.json + {transcript_file.name} (upload date normalized for verification)"
            ),
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
    except (BudgetExceededError, CostPolicyError, ProviderBusyTimeoutError):
        raise
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


# Cross-command dispatch + startup helpers live in a sibling leaf module so this
# file stays under the module-size cap. Re-exported here so every legacy import
# path (`_helpers._preflight`, `_helpers.resolve_intent`, `_helpers.run_preflight`,
# ...) keeps resolving.
from distill.commands._dispatch import (  # noqa: E402
    _invoke_command,  # noqa: F401  # pyright: ignore[reportUnusedImport, reportPrivateUsage]  -- compatibility re-export
    _preflight,  # noqa: F401  # pyright: ignore[reportUnusedImport, reportPrivateUsage]  -- compatibility re-export
    _resolve_intent,  # noqa: F401  # pyright: ignore[reportUnusedImport, reportPrivateUsage]  -- compatibility re-export
    invoke_command,
    resolve_intent,
    run_preflight,
)
