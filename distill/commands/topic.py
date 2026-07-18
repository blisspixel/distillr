# pyright: strict
"""The `distill topic` command group."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

import typer
from rich.panel import Panel

from distill.cli_shared import (
    console,
)
from distill.cli_shared import (
    output_path as _output_path,
)
from distill.cli_shared import (
    topic_from_query as _topic_from_query,
)
from distill.commands._helpers import (
    _complete_topics,
    budgeted_cost_tracker,
    enforce_projected_workflow_budget,
    get_config,
    save_command_cost,
)
from distill.commands._helpers import invoke_command as _invoke_command
from distill.commands._helpers import run_preflight as _preflight
from distill.commands._json import ExitCode
from distill.commands._learning import (
    generate_and_export_topic_brief as _generate_and_export_topic_brief,
)
from distill.commands._learning import (
    preview_learning_selection as _preview_learning_selection,
)
from distill.commands._learning import (
    run_learning_command as _run_learning_command,
)
from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import artifact_exists, find_artifact
from distill.library.state import ChannelState
from distill.llm.router import RouterConfig
from distill.pipeline.costs import estimate_synthesis_workflow_cost
from distill.pipeline.dashboard_data import count_paper_corpus as _count_paper_corpus
from distill.pipeline.dashboard_data import count_site_corpus as _count_site_corpus
from distill.pipeline.dashboard_data import count_topic_outputs as _count_topic_outputs

__all__ = [
    "_collect_topic_bundle_files",
    "_export_topic_bundle",
    "_load_topic_profile",
    "_run_topic_workflow",
    "register",
    "topic_app",
]


topic_app = typer.Typer(
    help=(
        "Topic-first workflows.\n\n"
        "Recommended flow:\n"
        '  distill topic create "topic here" --videos 10 --papers 10\n'
        "  distill topic update <topic>\n"
        "  distill topic brief <topic>\n"
        "  distill topic report <topic>\n"
    ),
    rich_markup_mode="rich",
)


def register(app: typer.Typer) -> None:
    app.add_typer(topic_app, name="topic")


_TOPIC_PROFILE_VERSION = 1


@dataclass(frozen=True)
class _TopicWorkflowConfig:
    topic: str
    goal: str
    videos: int
    papers: int
    days: int
    shorts: bool

    @property
    def mixed_sources(self) -> bool:
        return self.papers > 0


def _topic_profile_path(config: DistillConfig, topic: str) -> Path:
    return config.topic_dir(topic) / "topic_profile.json"


def _generate_budgeted_topic_brief(topic: str, config: DistillConfig) -> None:
    projected_cost = estimate_synthesis_workflow_cost(
        router_config=RouterConfig(),
    )
    enforce_projected_workflow_budget(config, "topic-brief", projected_cost)
    tracker = budgeted_cost_tracker(config, "topic-brief")
    try:
        _generate_and_export_topic_brief(topic, config, tracker)
    finally:
        save_command_cost(
            config,
            "topic-brief",
            tracker,
            metadata={"topic": topic},
            estimated_cost=projected_cost,
        )


def _topic_exists(config: DistillConfig, topic: str) -> bool:
    lib = Library(config)
    return topic in lib.get_topics() or config.topic_dir(topic).exists()


def _load_topic_profile(config: DistillConfig, topic: str) -> dict[str, object] | None:
    path = _topic_profile_path(config, topic)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return cast("dict[str, object]", data)


def _profile_str(profile: dict[str, object], key: str, default: str = "") -> str:
    value = profile.get(key, default)
    return value if isinstance(value, str) else default


def _profile_int(profile: dict[str, object], key: str, default: int) -> int:
    value = profile.get(key, default)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _profile_bool(profile: dict[str, object], key: str, default: bool) -> bool:
    value = profile.get(key, default)
    return value if isinstance(value, bool) else default


def _save_topic_profile(
    config: DistillConfig,
    *,
    topic: str,
    goal: str,
    videos: int,
    papers: int,
    days: int,
    shorts: bool,
) -> Path:
    path = _topic_profile_path(config, topic)
    path.parent.mkdir(parents=True, exist_ok=True)
    prior = _load_topic_profile(config, topic) or {}
    created_at = _profile_str(prior, "created_at") or datetime.now().isoformat()
    payload = {
        "version": _TOPIC_PROFILE_VERSION,
        "topic": topic,
        "goal": goal,
        "videos": videos,
        "papers": papers,
        "days": days,
        "shorts": shorts,
        "created_at": created_at,
        "updated_at": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _resolve_topic_workflow_config(
    config: DistillConfig,
    *,
    topic: str,
    goal: str,
    videos: int,
    papers: int,
    days: int,
    shorts: bool,
) -> _TopicWorkflowConfig:
    goal_text = " ".join(goal.split()).strip()
    if not goal_text:
        console.print("[red]Goal cannot be empty[/red]")
        raise typer.Exit(code=ExitCode.USAGE_ERROR)
    if days <= 0:
        console.print("[red]--days must be positive[/red]")
        raise typer.Exit(code=ExitCode.USAGE_ERROR)
    if videos < 0 or papers < 0:
        console.print("[red]--videos and --papers cannot be negative[/red]")
        raise typer.Exit(code=ExitCode.USAGE_ERROR)
    if videos == 0 and papers == 0:
        console.print("[red]Specify at least one source with --videos or --papers[/red]")
        raise typer.Exit(code=ExitCode.USAGE_ERROR)
    topic_name = topic.strip() or _topic_from_query(goal_text[:80])
    return _TopicWorkflowConfig(
        topic=topic_name,
        goal=goal_text,
        videos=videos,
        papers=papers,
        days=days,
        shorts=shorts,
    )


def _run_topic_workflow(
    *,
    goal: str,
    topic: str,
    videos: int,
    papers: int,
    days: int,
    shorts: bool,
    preview: bool,
    brief: bool,
    report_after: bool,
    test: bool,
) -> str:
    config = get_config()
    resolved = _resolve_topic_workflow_config(
        config,
        topic=topic,
        goal=goal,
        videos=videos,
        papers=papers,
        days=days,
        shorts=shorts,
    )
    topic_name = resolved.topic

    if resolved.mixed_sources:
        from distill.commands.discover import discover

        _invoke_command(
            discover,
            goal=resolved.goal,
            goal_file=None,
            topic=topic_name,
            paper_limit=resolved.papers,
            video_limit=resolved.videos,
            days=resolved.days,
            shorts=resolved.shorts,
            preview=preview,
            yes=True,
        )
    elif preview:
        # Videos-only preview must not ingest. _run_learning_command always
        # processes real work, so route to the dry-run preview path instead.
        _preview_learning_selection(
            resolved.goal,
            days=resolved.days,
            limit=resolved.videos,
            sort="relevance",
            per_channel_cap=max(2, min(resolved.videos, 3)),
            shorts=resolved.shorts,
            rerank=True,
            header="Topic Preview",
            table_title="Topic Preview Learning Set",
        )
    else:
        _run_learning_command(
            resolved.goal,
            topic=topic_name,
            days=resolved.days,
            limit=resolved.videos,
            sort="relevance",
            per_channel_cap=max(2, min(resolved.videos, 3)),
            shorts=resolved.shorts,
            rerank=True,
            save=True,
            report=False,
            test=test,
            generate_brief=False,
            header="Topic Create",
        )

    if preview:
        console.print(
            f'\n[dim]Preview only. Run `distill topic create "{resolved.goal}" --topic {topic_name}` to ingest.[/dim]'
        )
        return topic_name

    profile_path = _save_topic_profile(
        config,
        topic=topic_name,
        goal=resolved.goal,
        videos=resolved.videos,
        papers=resolved.papers,
        days=resolved.days,
        shorts=resolved.shorts,
    )
    console.print(f"[dim]Saved topic profile: {profile_path}[/dim]")

    if brief:
        _generate_budgeted_topic_brief(topic_name, config)
    if report_after:
        from distill.commands.reports import report

        _invoke_command(report, topic=topic_name, test=test)
    return topic_name


def _render_topic_summary(topic: str) -> None:
    config = get_config()
    lib = Library(config)
    if topic not in lib.get_topics() and not config.topic_dir(topic).exists():
        console.print(f"[red]Topic not found: {topic}[/red]")
        raise typer.Exit(code=ExitCode.NOT_FOUND)

    channels = lib.get_channels(topic)
    video_count = 0
    for ch in channels:
        state = ChannelState(config.channel_dir(topic, ch.name) / "state.json")
        video_count += state.get_processed_count()

    artifacts: list[str] = []
    topic_dir = config.topic_dir(topic)
    for label, path_obj in [
        ("topic synthesis", find_artifact(topic_dir, "topic_synthesis", identity=topic)),
        ("brief", find_artifact(topic_dir, "brief", identity=topic)),
        ("report", find_artifact(topic_dir, "report", identity=topic)),
        ("paper synthesis", find_artifact(topic_dir, "paper_synthesis", identity=topic)),
        ("corpus synthesis", find_artifact(topic_dir, "corpus_synthesis", identity=topic)),
    ]:
        if path_obj.exists():
            artifacts.append(label)

    profile = _load_topic_profile(config, topic)
    paper_count = _count_paper_corpus(config, [topic])
    site_count, page_count = _count_site_corpus(config, [topic])
    lines = [f"[bold]{topic}[/bold]"]
    if profile and _profile_str(profile, "goal"):
        lines.append(f"[dim]Goal:[/dim] {_profile_str(profile, 'goal')}")
    lines.append(
        f"[dim]Corpus:[/dim] {len(channels)} channel(s), {video_count} processed video(s), {paper_count} paper(s), {site_count} site(s) / {page_count} page(s)"
    )
    if profile:
        lines.append(
            f"[dim]Plan:[/dim] videos={_profile_int(profile, 'videos', 0)} papers={_profile_int(profile, 'papers', 0)} days={_profile_int(profile, 'days', 0)} shorts={'on' if _profile_bool(profile, 'shorts', False) else 'off'}"
        )
    if artifacts:
        lines.append(f"[dim]Artifacts:[/dim] {', '.join(artifacts)}")
    lines.append(
        f"[dim]Next:[/dim] distill topic update {topic}  |  distill topic brief {topic}  |  distill topic report {topic}"
    )
    console.print(Panel("\n".join(lines), title="Topic Summary", border_style="cyan"))


@topic_app.command("create")
def topic_create(
    goal: str = typer.Argument(help="Natural-language topic goal or research prompt"),
    topic: str = typer.Option("", "--topic", "-t", help="Explicit topic slug/name"),
    videos: int = typer.Option(10, "--videos", help="How many videos to ingest"),
    papers: int = typer.Option(10, "--papers", help="How many papers to ingest"),
    days: int = typer.Option(30, "--days", "-d", help="Video recency window in days"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
    preview: bool = typer.Option(
        False, "--preview", help="Show the plan without ingesting the topic corpus"
    ),
    brief: bool = typer.Option(
        False, "--brief", help="Generate a concise topic brief after ingestion"
    ),
    report_after: bool = typer.Option(
        False, "--report", help="Generate a full topic report after ingestion"
    ),
    test: bool = typer.Option(False, "--test", help="Cheaper/faster report mode"),
) -> None:
    """Create a topic corpus from a single goal using the configured source mix."""
    _run_topic_workflow(
        goal=goal,
        topic=topic,
        videos=videos,
        papers=papers,
        days=days,
        shorts=shorts,
        preview=preview,
        brief=brief,
        report_after=report_after,
        test=test,
    )


@topic_app.command("preview")
def topic_preview(
    goal: str = typer.Argument(help="Natural-language topic goal or research prompt"),
    topic: str = typer.Option("", "--topic", "-t", help="Optional topic slug/name"),
    videos: int = typer.Option(10, "--videos", help="How many videos to plan for"),
    papers: int = typer.Option(10, "--papers", help="How many papers to plan for"),
    days: int = typer.Option(30, "--days", "-d", help="Video recency window in days"),
    shorts: bool = typer.Option(
        False, "--shorts/--no-shorts", help="Include short-form videos under 3 minutes"
    ),
) -> None:
    """Preview the topic plan without ingesting anything."""
    _run_topic_workflow(
        goal=goal,
        topic=topic,
        videos=videos,
        papers=papers,
        days=days,
        shorts=shorts,
        preview=True,
        brief=False,
        report_after=False,
        test=False,
    )


@topic_app.command("update")
def topic_update(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    goal: str | None = typer.Option(None, "--goal", help="Override the stored goal"),
    videos: int | None = typer.Option(None, "--videos", help="Override stored video count"),
    papers: int | None = typer.Option(None, "--papers", help="Override stored paper count"),
    days: int | None = typer.Option(None, "--days", "-d", help="Override stored day window"),
    shorts: bool | None = typer.Option(
        None, "--shorts/--no-shorts", help="Override whether Shorts are included"
    ),
    preview: bool = typer.Option(False, "--preview", help="Preview the refreshed plan only"),
    brief: bool = typer.Option(False, "--brief", help="Generate a brief after update"),
    report_after: bool = typer.Option(False, "--report", help="Generate a report after update"),
    test: bool = typer.Option(False, "--test", help="Cheaper/faster report mode"),
) -> None:
    """Refresh a topic using its saved topic profile, with optional overrides."""
    _preflight()
    config = get_config()
    profile = _load_topic_profile(config, topic)
    if profile is None:
        console.print(
            f'[red]No topic profile found for {topic}[/red]\n[dim]Create one first with `distill topic create "..." --topic {topic}`[/dim]'
        )
        raise typer.Exit(code=ExitCode.NOT_FOUND)

    resolved_goal = goal or _profile_str(profile, "goal").strip()
    resolved_videos = _profile_int(profile, "videos", 0) if videos is None else videos
    resolved_papers = _profile_int(profile, "papers", 0) if papers is None else papers
    resolved_days = _profile_int(profile, "days", 30) if days is None else days
    resolved_shorts = _profile_bool(profile, "shorts", False) if shorts is None else shorts

    _run_topic_workflow(
        goal=resolved_goal,
        topic=topic,
        videos=resolved_videos,
        papers=resolved_papers,
        days=resolved_days,
        shorts=resolved_shorts,
        preview=preview,
        brief=brief,
        report_after=report_after,
        test=test,
    )


@topic_app.command("brief")
def topic_brief(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    report_after: bool = typer.Option(False, "--report", help="Also generate a full report"),
    test: bool = typer.Option(False, "--test", help="Cheaper/faster report mode"),
) -> None:
    """Generate a concise markdown brief from an existing topic corpus."""
    config = get_config()
    if not _topic_exists(config, topic):
        console.print(f"[red]Topic not found: {topic}[/red]")
        raise typer.Exit(code=ExitCode.NOT_FOUND)
    _generate_budgeted_topic_brief(topic, config)
    if report_after:
        from distill.commands.reports import report

        _invoke_command(report, topic=topic, test=test)


@topic_app.command("report")
def topic_report(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    focus: str | None = typer.Option(None, "--focus", "-f", help="Custom research focus"),
    test: bool = typer.Option(False, "--test", "-t", help="Test mode (cheaper, faster)"),
    legacy: bool = typer.Option(
        False, "--legacy", help="Use single-shot Deep Research (no section writing)"
    ),
    research_only: bool = typer.Option(
        False, "--research-only", help="Run Phase 1 only (raw research, no section writing)"
    ),
    sections_filter: str | None = typer.Option(
        None, "--sections", "-s", help="Comma-separated section IDs to write"
    ),
    no_qa: bool = typer.Option(False, "--no-qa", help="Skip QA review phase"),
) -> None:
    """Generate a full research report for an existing topic."""
    from distill.commands.reports import report

    report(
        topic=topic,
        channel=None,
        all_topics=False,
        focus=focus,
        test=test,
        legacy=legacy,
        research_only=research_only,
        sections_filter=sections_filter,
        no_qa=no_qa,
    )


@topic_app.command("show")
def topic_show(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    what: str = typer.Option(
        "summary",
        "--what",
        "-w",
        help="What to show: summary, synthesis, report",
    ),
) -> None:
    """Show the current state or key outputs for a topic."""
    from distill.commands.view import findings, synthesis

    if what == "summary":
        _render_topic_summary(topic)
        return
    if what == "synthesis":
        synthesis(topic=topic, channel=None)
        return
    if what == "report":
        findings(topic=topic, channel=None)
        return
    console.print("[red]Unknown --what. Use: summary, synthesis, report[/red]")
    raise typer.Exit(code=ExitCode.USAGE_ERROR)


@topic_app.command("export")
def topic_export(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    what: str = typer.Option(
        "report",
        "--what",
        "-w",
        help="What to export: report, synthesis, bundle, citations",
    ),
    bundle_format: str = typer.Option(
        "bundle", "--format", help="Bundle or citation format: bundle, deepr, okf, bibtex, ris"
    ),
) -> None:
    """Export topic artifacts in the same formats as the lower-level export command."""
    from distill.commands.reports import export

    export(topic=topic, what=what, channel=None, bundle_format=bundle_format)


@topic_app.command("watch")
def topic_watch(
    topic: str = typer.Argument(help="Existing topic name", autocompletion=_complete_topics),
    cadence: str = typer.Option("daily", "--cadence", help="Run cadence: daily or weekly"),
    days: int | None = typer.Option(None, "--days", "-d", help="Override lookback window"),
    limit: int | None = typer.Option(None, "--videos", help="Override video pick count"),
    name: str = typer.Option("", "--name", help="Explicit watch name"),
    report_after: bool = typer.Option(
        False, "--report", help="Also generate a full topic report when this watch runs"
    ),
    max_run_cost: float = typer.Option(
        0.0, "--max-run-cost", help="Pause this watch if projected run cost exceeds this amount"
    ),
    monthly_budget: float = typer.Option(
        0.0,
        "--monthly-budget",
        help="Pause this watch if projected 30-day spend exceeds this amount",
    ),
    now: bool = typer.Option(False, "--now", help="Run the watch immediately after creating it"),
    preview: bool = typer.Option(
        False, "--preview", help="Preview the selected best-pick videos instead of processing"
    ),
) -> None:
    """Create a recurring topic watch using the saved topic profile."""
    config = get_config()
    profile = _load_topic_profile(config, topic)
    if profile is None:
        console.print(
            f'[red]No topic profile found for {topic}[/red]\n[dim]Create one first with `distill topic create "..." --topic {topic}`[/dim]'
        )
        raise typer.Exit(code=ExitCode.NOT_FOUND)

    from distill.commands.discover import monitor

    monitor(
        query=_profile_str(profile, "goal").strip(),
        topic=topic,
        name=name,
        cadence=cadence,
        days=_profile_int(profile, "days", 30) if days is None else days,
        limit=_profile_int(profile, "videos", 10) if limit is None else limit,
        sort="date",
        per_channel_cap=3,
        ranking="balanced",
        report=report_after,
        max_run_cost=max_run_cost,
        monthly_budget=monthly_budget,
        now=now,
        preview=preview,
    )


def _collect_topic_bundle_files(config: DistillConfig, topic: str) -> list[Path]:
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return []
    files: list[Path] = []
    for path_obj in topic_dir.rglob("*"):
        if not path_obj.is_file():
            continue
        if path_obj.suffix.lower() not in {".md", ".json", ".txt"}:
            continue
        files.append(path_obj)
    files.sort()
    return files


def _topic_bundle_manifest(
    config: DistillConfig, topic: str, export_format: str, files: list[Path]
) -> dict[str, object]:
    lib = Library(config)
    channels = lib.get_channels(topic)
    site_count, page_count = _count_site_corpus(config, [topic])
    paper_count = _count_paper_corpus(config, [topic])
    report_count, brief_count, synthesis_count = _count_topic_outputs(config, [topic])
    video_count = 0
    for ch in channels:
        videos_dir = config.channel_dir(topic, ch.name) / "videos"
        if not videos_dir.exists():
            continue
        for video_dir in videos_dir.iterdir():
            if video_dir.is_dir() and artifact_exists(video_dir, "insights"):
                video_count += 1
    return {
        "topic": topic,
        "format": export_format,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_types": {
            "youtube": bool(channels),
            "website": bool(site_count),
            "papers": bool(paper_count),
        },
        "counts": {
            "channels": len(channels),
            "videos": video_count,
            "sites": site_count,
            "pages": page_count,
            "papers": paper_count,
            "topic_syntheses": synthesis_count,
            "briefs": brief_count,
            "reports": report_count,
            "files": len(files),
        },
        "files": [
            {
                "path": str(path_obj.relative_to(config.topic_dir(topic)).as_posix()),
                "bytes": path_obj.stat().st_size,
                "kind": path_obj.suffix.lower().removeprefix("."),
            }
            for path_obj in files
        ],
    }


def _export_topic_bundle(config: DistillConfig, topic: str, export_format: str) -> Path:
    if export_format not in {"deepr", "bundle"}:
        raise typer.BadParameter("--format must be 'deepr' or 'bundle'")
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        raise typer.Exit(code=ExitCode.NOT_FOUND)
    files = _collect_topic_bundle_files(config, topic)
    if not files:
        raise typer.Exit(code=ExitCode.NOT_FOUND)

    zip_path = _output_path(config, f"corpus-{topic_dir.name}-{export_format}.zip")
    manifest = _topic_bundle_manifest(config, topic, export_format, files)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for path_obj in files:
            arcname = Path(topic_dir.name) / path_obj.relative_to(topic_dir)
            zf.write(path_obj, arcname=str(arcname.as_posix()))
    return zip_path
