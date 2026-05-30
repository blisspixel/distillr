from __future__ import annotations

import json
import time
import traceback
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from distill.llm.cost import deep_research_query_cost
from distill.pipeline.costs import ACCORDION_GROK_ESTIMATE, report_deep_research_estimate

__all__ = [
    "ETATracker",
    "RunIssue",
    "RunSummary",
    "VideoResult",
    "display_estimate",
    "display_summary",
    "log_preview_cost",
]


@dataclass(frozen=True)
class VideoResult:
    """Result from processing a single video."""

    video_id: str
    title: str
    success: bool
    is_short: bool = False
    error: str | None = None
    transcript_bytes: int = 0
    duration: int = 0


@dataclass(frozen=True)
class RunIssue:
    """Structured non-video issue surfaced during a run."""

    stage: str
    message: str
    context: str = ""
    severity: str = "error"
    exception_type: str = ""
    traceback_text: str = ""
    details: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "stage": self.stage,
            "message": self.message,
            "context": self.context,
            "severity": self.severity,
        }
        if self.exception_type:
            payload["exception_type"] = self.exception_type
        if self.traceback_text:
            payload["traceback"] = self.traceback_text
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass
class RunSummary:
    """Accumulated results from a processing run."""

    results: list[VideoResult] = field(default_factory=list)
    issues: list[RunIssue] = field(default_factory=list)
    output_files: list[Path] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    command: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def add_result(self, result: VideoResult) -> None:
        self.results.append(result)

    def add_output(self, path: Path) -> None:
        if not path.exists():
            return
        resolved = path.resolve()
        if resolved not in self.output_files:
            self.output_files.append(resolved)

    def set_metadata(self, **kwargs: str) -> None:
        for key, value in kwargs.items():
            if value:
                self.metadata[str(key)] = str(value)

    def add_issue(
        self,
        stage: str,
        message: str,
        context: str = "",
        *,
        severity: str = "error",
        details: dict[str, Any] | None = None,
        exception_type: str = "",
        traceback_text: str = "",
    ) -> None:
        normalized_details = _normalize_details(details)
        issue = RunIssue(
            stage=stage,
            message=message,
            context=context,
            severity=severity,
            exception_type=exception_type,
            traceback_text=traceback_text,
            details=normalized_details,
        )
        if issue not in self.issues:
            self.issues.append(issue)

    def add_exception(
        self,
        stage: str,
        exc: BaseException,
        context: str = "",
        *,
        severity: str = "error",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.add_issue(
            stage,
            str(exc) or exc.__class__.__name__,
            context=context,
            severity=severity,
            details=details,
            exception_type=exc.__class__.__name__,
            traceback_text="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ).strip(),
        )

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def shorts_count(self) -> int:
        return sum(1 for r in self.results if r.is_short and r.success)

    @property
    def full_count(self) -> int:
        return sum(1 for r in self.results if not r.is_short and r.success)

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time


@dataclass
class ETATracker:
    """Tracks per-video processing time for ETA estimates."""

    total: int
    completed: int = 0
    _times: list[float] = field(default_factory=list)

    def start(self) -> float:
        return time.time()

    def tick(self, start_time: float) -> None:
        self._times.append(time.time() - start_time)
        self.completed += 1

    @property
    def avg_seconds(self) -> float:
        if not self._times:
            return 0
        return sum(self._times) / len(self._times)

    @property
    def eta_str(self) -> str:
        if not self._times or self.completed >= self.total:
            return ""
        remaining = (self.total - self.completed) * self.avg_seconds
        if remaining < 60:
            return f"~{int(remaining)}s left"
        mins = int(remaining // 60)
        return f"~{mins}m left"

    def progress_str(self, current_step: str = "") -> str:
        parts = [f"{self.completed + 1}/{self.total}"]
        eta = self.eta_str
        if eta:
            parts.append(eta)
        step = f"  {current_step}" if current_step else ""
        return f"[dim][{', '.join(parts)}][/dim]{step}"


_ACCENT = "rgb(100,149,237)"


def display_estimate(
    full_videos: int = 0,
    shorts: int = 0,
    console: Console | None = None,
    include_report: bool = False,
    synthesis_calls: int = 0,
    scan_videos: int = 0,
) -> None:
    con = console or Console()

    grok_cost = full_videos * 0.006 + shorts * 0.0004 + scan_videos * 0.001
    synthesis_cost = synthesis_calls * 0.003
    gemini_cost = deep_research_query_cost() if include_report else 0.0
    accordion_grok = ACCORDION_GROK_ESTIMATE if include_report else 0.0
    total = grok_cost + synthesis_cost + gemini_cost + accordion_grok

    parts = []
    if full_videos:
        parts.append(f"{full_videos} video{'s' if full_videos != 1 else ''}")
    if scan_videos:
        parts.append(f"{scan_videos} video{'s' if scan_videos != 1 else ''} (scan)")
    if shorts:
        parts.append(f"{shorts} Short{'s' if shorts != 1 else ''}")
    if synthesis_calls and not full_videos and not shorts and not scan_videos:
        parts.append(f"{synthesis_calls} synthesis call{'s' if synthesis_calls != 1 else ''}")
    desc_str = " + ".join(parts) if parts else "0 videos"

    con.print()
    con.print(f"  [{_ACCENT}]{desc_str}[/{_ACCENT}]  ·  [dim]~${total:.2f} estimated[/dim]")
    if include_report:
        con.print(
            f"  [dim]includes Deep Research (~${report_deep_research_estimate(include_section_writing=False):.2f}) "
            "+ report generation[/dim]"
        )
    con.print()


def display_summary(  # noqa: C901 — legacy, will refactor
    summary: RunSummary,
    cost_tracker=None,
    console: Console | None = None,
    log_dir: Path | None = None,
    preview: bool = False,
) -> None:
    con = console or Console()

    is_empty = not summary.results and not summary.output_files and not summary.issues
    # Preview runs intentionally produce no outputs/results, but they still pay
    # for query expansion + rerank and need their cost logged separately.
    if is_empty and not preview:
        return

    if cost_tracker and log_dir:
        try:
            from distill.pipeline.costs import save_run_log

            save_run_log(
                log_dir=log_dir,
                command=summary.command,
                tracker=cost_tracker,
                full_videos=summary.full_count,
                shorts=summary.shorts_count,
                elapsed_seconds=summary.elapsed,
                metadata=summary.metadata,
                preview=preview,
            )
        except Exception:
            pass

    # Preview runs skip the visual summary block — the preview already showed
    # the ranked table; only the cost log needed to be written.
    if is_empty and preview:
        return

    if log_dir:
        with suppress(Exception):
            _save_run_artifacts(summary, log_dir)

    con.print()
    con.print(f"  [dim]{'-' * 50}[/dim]")
    con.print()

    if summary.results:
        parts = []
        if summary.full_count:
            parts.append(
                f"[{_ACCENT}]{summary.full_count}[/{_ACCENT}] video{'s' if summary.full_count != 1 else ''}"
            )
        if summary.shorts_count:
            parts.append(
                f"[{_ACCENT}]{summary.shorts_count}[/{_ACCENT}] Short{'s' if summary.shorts_count != 1 else ''}"
            )
        if summary.failed:
            parts.append(f"[red]{summary.failed} failed[/red]")
        if summary.issue_count:
            parts.append(
                f"[yellow]{summary.issue_count} issue{'s' if summary.issue_count != 1 else ''}[/yellow]"
            )
        con.print(f"  {' + '.join(parts)} processed")
    elif summary.issue_count:
        con.print(
            f"  [yellow]{summary.issue_count} issue{'s' if summary.issue_count != 1 else ''}[/yellow]"
        )

    elapsed = summary.elapsed
    time_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s" if elapsed > 60 else f"{elapsed:.1f}s"

    cost_str = ""
    if cost_tracker:
        cost_str = f"  ·  ~{cost_tracker.format_cost()}"
        tokens = (
            f"{cost_tracker.total_input_tokens:,} in / {cost_tracker.total_output_tokens:,} out"
        )
        cost_str += f" [dim]({tokens})[/dim]"

    con.print(f"  [dim]{time_str}[/dim]{cost_str}")

    if summary.output_files:
        con.print()
        for path in summary.output_files:
            uri = f"file:///{path.as_posix()}"
            con.print(
                f"  [{_ACCENT}][link={uri}]{path.name}[/link][/{_ACCENT}]  [dim]{_file_size(path)}[/dim]"
            )

    failed = [r for r in summary.results if not r.success]
    if failed:
        con.print()
        con.print(f"  [red]{len(failed)} failed[/red]")
        for r in failed:
            con.print(f"    [dim]x[/dim] {r.title[:60]}  [dim]{r.error or 'Unknown error'}[/dim]")

    if summary.issues:
        con.print()
        con.print(
            f"  [yellow]{len(summary.issues)} run issue{'s' if len(summary.issues) != 1 else ''}[/yellow]"
        )
        for issue in summary.issues:
            context = f" ({issue.context})" if issue.context else ""
            detail_suffix = ""
            if issue.exception_type:
                detail_suffix = f" [{issue.exception_type}]"
            con.print(
                f"    [dim]![/dim] {issue.stage}{context}{detail_suffix}  [dim]{issue.message}[/dim]"
            )

    con.print()


def _normalize_details(details: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    if not details:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in details.items()))


def _save_run_artifacts(summary: RunSummary, log_dir: Path) -> None:  # noqa: C901 — legacy, will refactor
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).isoformat()
    payload = {
        "timestamp": timestamp,
        "command": summary.command,
        "elapsed_seconds": round(summary.elapsed, 1),
        "results": {
            "passed": summary.passed,
            "failed": summary.failed,
            "full_videos": summary.full_count,
            "shorts": summary.shorts_count,
        },
        "issues": [issue.to_dict() for issue in summary.issues],
        "failed_videos": [asdict(r) for r in summary.results if not r.success],
        "outputs": [str(path) for path in summary.output_files],
        "metadata": summary.metadata,
    }

    run_log = log_dir / "run_log.jsonl"
    with run_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")

    latest_json = log_dir / "latest_run.json"
    latest_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    latest = log_dir / "latest_run_errors.md"
    lines = [
        "# Distill Run Log",
        "",
        f"- Timestamp: `{timestamp}`",
        f"- Command: `{summary.command or 'unknown'}`",
        f"- Elapsed: `{round(summary.elapsed, 1)}s`",
        f"- Passed videos: `{summary.passed}`",
        f"- Failed videos: `{summary.failed}`",
        f"- Run issues: `{summary.issue_count}`",
        f"- Latest JSON: `{latest_json}`",
        "",
    ]

    if summary.issues:
        lines.extend(["## Run Issues", ""])
        for issue in summary.issues:
            context = f" ({issue.context})" if issue.context else ""
            headline = f"- `{issue.stage}{context}`: {issue.message}"
            if issue.exception_type:
                headline += f" [{issue.exception_type}]"
            lines.append(headline)
            if issue.details:
                for key, value in issue.details:
                    lines.append(f"  - `{key}`: {value}")
            if issue.traceback_text:
                lines.extend(["", "```text", issue.traceback_text, "```"])
        lines.append("")

    if summary.failed:
        lines.extend(["## Failed Videos", ""])
        for result in summary.results:
            if not result.success:
                lines.append(f"- `{result.title}`: {result.error or 'Unknown error'}")
        lines.append("")

    if summary.output_files:
        lines.extend(["## Outputs", ""])
        for path in summary.output_files:
            lines.append(f"- `{path}`")
        lines.append("")

    latest.write_text("\n".join(lines), encoding="utf-8")


def _file_size(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def log_preview_cost(
    tracker,
    log_dir: Path | None,
    command: str,
    *,
    metadata: dict[str, str] | None = None,
    elapsed_seconds: float = 0.0,
) -> None:
    """Log preview-only cost to ``cost_log.jsonl`` with a ``_preview`` suffix.

    Preview paths (``--preview``) intentionally produce no outputs but still pay
    for query expansion and rerank. This helper records that spend so iterative
    preview cycles are visible in ``distill costs`` separately from ingest runs.
    No-op if the tracker has no entries or ``log_dir`` is None.
    """
    if tracker is None or log_dir is None:
        return
    has_spend = bool(getattr(tracker, "entries", [])) or getattr(tracker, "gemini_queries", 0)
    if not has_spend:
        return
    try:
        from distill.pipeline.costs import save_run_log

        save_run_log(
            log_dir=log_dir,
            command=command,
            tracker=tracker,
            metadata=metadata or {},
            elapsed_seconds=elapsed_seconds,
            preview=True,
        )
    except Exception:
        pass
