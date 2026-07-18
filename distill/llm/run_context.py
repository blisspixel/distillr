# pyright: strict
"""Local run correlation and lightweight phase telemetry.

The active run is held in a context variable so synchronous code and asyncio
tasks can correlate provider, cost, and phase rows without adding plumbing to
every call. Telemetry is append-only, local, content-free, and fail-soft.
"""

from __future__ import annotations

import ctypes
import json
import logging
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from distill.jsonl import append_jsonl_line

logger = logging.getLogger(__name__)

WaitClass = Literal[
    "acquisition",
    "provider",
    "queue",
    "subprocess",
    "filesystem",
    "deterministic_cpu",
    "write",
    "mixed",
]


@dataclass(slots=True)
class RunContext:
    """Correlation state for one top-level CLI command or MCP tool call."""

    run_id: str
    invocation_type: str
    command: str
    ops_dir: Path | None
    started_monotonic: float = field(default_factory=time.monotonic)
    outcome: str = ""
    profile_receipt_written: bool = False


@dataclass(frozen=True, slots=True)
class PhaseTelemetryRecord:
    """Content-free timing and resource row for one measured run phase."""

    run_id: str
    invocation_type: str
    command: str
    phase: str
    elapsed_seconds: float
    cpu_seconds: float
    outcome: str
    wait_class: WaitClass
    peak_rss_bytes: int | None = None
    artifact_count: int = 0
    byte_count: int = 0
    error_type: str = ""
    timestamp: str = ""
    schema_version: int = 1


_current_run: ContextVar[RunContext | None] = ContextVar("distill_current_run", default=None)


def current_run() -> RunContext | None:
    """Return the active run context, if this call is inside an invocation."""
    return _current_run.get()


def current_run_id() -> str:
    """Return the active correlation ID, or an empty string outside a run."""
    context = current_run()
    return context.run_id if context is not None else ""


def current_run_elapsed_seconds() -> float:
    """Return wall time since the active invocation began."""
    context = current_run()
    if context is None:
        return 0.0
    return max(0.0, time.monotonic() - context.started_monotonic)


def update_current_run(*, command: str = "", ops_dir: str | Path | None = None) -> None:
    """Add details discovered after the CLI root callback loads configuration."""
    context = current_run()
    if context is None:
        return
    if command:
        context.command = command
    if ops_dir is not None:
        context.ops_dir = Path(ops_dir)


def mark_current_run_outcome(outcome: str) -> None:
    """Set a structured terminal outcome for a gate that returns or exits cleanly."""
    context = current_run()
    if context is not None:
        context.outcome = outcome


def mark_profile_receipt_written() -> None:
    """Record that this command durably appended its profile cost receipt."""

    context = current_run()
    if context is not None:
        context.profile_receipt_written = True


def _start_run(
    *,
    invocation_type: str,
    command: str,
    ops_dir: str | Path | None,
    run_id: str,
) -> tuple[RunContext, Token[RunContext | None]]:
    context = RunContext(
        run_id=run_id or str(uuid.uuid4()),
        invocation_type=invocation_type,
        command=command,
        ops_dir=Path(ops_dir) if ops_dir is not None else None,
    )
    return context, _current_run.set(context)


@contextmanager
def run_scope(
    *,
    invocation_type: str,
    command: str,
    ops_dir: str | Path | None = None,
    run_id: str = "",
):
    """Create one correlated invocation and record its top-level phase."""
    context, token = _start_run(
        invocation_type=invocation_type,
        command=command,
        ops_dir=ops_dir,
        run_id=run_id,
    )
    try:
        with phase_scope("command", wait_class="mixed"):
            yield context
    finally:
        _current_run.reset(token)


@contextmanager
def phase_scope(
    phase: str,
    *,
    wait_class: WaitClass,
    artifact_count: int = 0,
    byte_count: int = 0,
):
    """Measure a phase inside the active run and append one local JSONL row."""
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    outcome = "success"
    error_type = ""
    try:
        yield
    except BaseException as exc:
        if isinstance(exc, SystemExit) and exc.code in (None, 0):
            outcome = "success"
            error_type = ""
        elif isinstance(exc, KeyboardInterrupt):
            outcome = "cancelled"
            error_type = type(exc).__name__
        else:
            outcome = "error"
            error_type = type(exc).__name__
        raise
    finally:
        context = current_run()
        if context is not None and context.ops_dir is not None:
            if context.outcome:
                outcome = context.outcome
            write_phase_record(
                context.ops_dir,
                PhaseTelemetryRecord(
                    run_id=context.run_id,
                    invocation_type=context.invocation_type,
                    command=context.command,
                    phase=phase,
                    elapsed_seconds=round(max(0.0, time.perf_counter() - started_wall), 6),
                    cpu_seconds=round(max(0.0, time.process_time() - started_cpu), 6),
                    outcome=outcome,
                    wait_class=wait_class,
                    peak_rss_bytes=_peak_rss_bytes(),
                    artifact_count=max(0, artifact_count),
                    byte_count=max(0, byte_count),
                    error_type=error_type,
                ),
            )


def record_completed_phase(
    *,
    phase: str,
    elapsed_seconds: float,
    cpu_seconds: float,
    outcome: str,
    wait_class: WaitClass,
    artifact_count: int = 0,
    byte_count: int = 0,
    error_type: str = "",
) -> None:
    """Record a phase timed by an existing workflow summary."""
    context = current_run()
    if context is None or context.ops_dir is None:
        return
    write_phase_record(
        context.ops_dir,
        PhaseTelemetryRecord(
            run_id=context.run_id,
            invocation_type=context.invocation_type,
            command=context.command,
            phase=phase,
            elapsed_seconds=round(max(0.0, elapsed_seconds), 6),
            cpu_seconds=round(max(0.0, cpu_seconds), 6),
            outcome=outcome,
            wait_class=wait_class,
            peak_rss_bytes=_peak_rss_bytes(),
            artifact_count=max(0, artifact_count),
            byte_count=max(0, byte_count),
            error_type=error_type,
        ),
    )


def write_phase_record(ops_dir: str | Path, record: PhaseTelemetryRecord) -> None:
    """Append one phase row without allowing telemetry failure to break a run."""
    try:
        path = Path(ops_dir)
        path.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        if not payload["timestamp"]:
            payload["timestamp"] = datetime.now(UTC).isoformat()
        append_jsonl_line(
            path / "phase_telemetry.jsonl",
            json.dumps(payload, separators=(",", ":"), allow_nan=False),
        )
    except Exception:
        logger.debug("Failed to write phase telemetry", exc_info=True)


def _peak_rss_bytes() -> int | None:
    """Return the process high-water resident set using only the standard library."""
    try:
        if sys.platform == "win32":
            return _windows_peak_rss_bytes()
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except Exception:
        logger.debug("Failed to read process peak RSS", exc_info=True)
        return None


def _windows_peak_rss_bytes() -> int:
    """Read PeakWorkingSetSize from the current Windows process."""

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    process = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    )
    if not ok:
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.PeakWorkingSetSize)


__all__ = [
    "PhaseTelemetryRecord",
    "RunContext",
    "WaitClass",
    "current_run",
    "current_run_elapsed_seconds",
    "current_run_id",
    "mark_current_run_outcome",
    "mark_profile_receipt_written",
    "phase_scope",
    "record_completed_phase",
    "run_scope",
    "update_current_run",
    "write_phase_record",
]
