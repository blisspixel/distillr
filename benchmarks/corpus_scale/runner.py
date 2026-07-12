# pyright: strict
"""Read-only measurements over a generated corpus."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import json
import math
import os
import platform
import sys
import sysconfig
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import NotRequired, TypedDict

from benchmarks.corpus_scale.generator import GeneratedCorpus, corpus_tree_digest
from distill.library.insights import discover_insights
from distill.library.links import check_links
from distill.pipeline.dashboard_data import dashboard_snapshot
from distill.pipeline.dedup import collect_near_duplicates
from distill.pipeline.search import search_corpus

RESULT_SCHEMA_VERSION = "corpus-scale-result.v1"

type _Operation = Callable[[], tuple[object, int]]


class BenchmarkSample(TypedDict):
    wall_ns: int
    cpu_ns: int
    baseline_rss_bytes: int
    peak_rss_bytes: int
    result_count: int
    result_digest: str


class IntegrityResult(TypedDict):
    before_digest: str
    after_digest: str
    unchanged: bool


class BenchmarkOperation(TypedDict):
    name: str
    status: str
    samples: list[BenchmarkSample]
    summary: dict[str, object]
    integrity: IntegrityResult
    error: NotRequired[dict[str, str]]


class BenchmarkResult(TypedDict):
    schema_version: str
    suite: str
    generated_at: str
    environment: dict[str, object]
    corpus: dict[str, object]
    execution: dict[str, object]
    operations: list[BenchmarkOperation]
    integrity: IntegrityResult


def _json_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _windows_rss_bytes() -> int:
    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD),
            ("page_fault_count", ctypes.wintypes.DWORD),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
    process = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
    return int(counters.working_set_size) if ok else 0


def _current_rss_bytes() -> int:
    if sys.platform == "win32":
        return _windows_rss_bytes()
    statm = Path("/proc/self/statm")
    if statm.exists():
        try:
            resident_pages = int(statm.read_text(encoding="ascii").split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            pass
    try:
        import resource

        maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return maximum if sys.platform == "darwin" else maximum * 1024
    except (ImportError, OSError, ValueError):
        return 0


class _PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.001) -> None:
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._samples = [_current_rss_bytes()]
        self._thread = threading.Thread(target=self._sample, daemon=True)

    @property
    def baseline(self) -> int:
        return self._samples[0]

    def _sample(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._samples.append(_current_rss_bytes())

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> int:
        self._stop.set()
        self._thread.join()
        self._samples.append(_current_rss_bytes())
        return max(self._samples)


def _nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _summary(samples: list[BenchmarkSample]) -> dict[str, object]:
    wall = [sample["wall_ns"] for sample in samples]
    cpu = [sample["cpu_ns"] for sample in samples]
    peak = [sample["peak_rss_bytes"] for sample in samples]
    baseline = [sample["baseline_rss_bytes"] for sample in samples]
    return {
        "min_wall_ns": min(wall),
        "p50_wall_ns": _nearest_rank(wall, 0.50),
        "p95_wall_ns": _nearest_rank(wall, 0.95),
        "max_wall_ns": max(wall),
        "p50_cpu_ns": _nearest_rank(cpu, 0.50),
        "max_peak_rss_bytes": max(peak),
        "max_rss_delta_bytes": max(
            maximum - start for maximum, start in zip(peak, baseline, strict=True)
        ),
    }


def _measure(operation: _Operation) -> tuple[BenchmarkSample, object]:
    sampler = _PeakRssSampler()
    sampler.start()
    try:
        wall_start = time.perf_counter_ns()
        cpu_start = time.process_time_ns()
        value, result_count = operation()
        cpu_ns = time.process_time_ns() - cpu_start
        wall_ns = time.perf_counter_ns() - wall_start
    finally:
        peak_rss = sampler.stop()
    sample: BenchmarkSample = {
        "wall_ns": wall_ns,
        "cpu_ns": cpu_ns,
        "baseline_rss_bytes": sampler.baseline,
        "peak_rss_bytes": peak_rss,
        "result_count": result_count,
        "result_digest": _json_digest(value),
    }
    return sample, value


def _operations(corpus: GeneratedCorpus) -> list[tuple[str, _Operation]]:
    root = corpus.library_root
    topic_dir = corpus.topic_dir

    def insights() -> tuple[object, int]:
        rows = sorted((ref.artifact_path, ref.source_id) for ref in discover_insights(topic_dir))
        return rows, len(rows)

    def search_hit() -> tuple[object, int]:
        rows = sorted(
            (
                result.path.replace("\\", "/"),
                round(result.score, 12),
                result.artifact_type,
            )
            for result in search_corpus(corpus.config, corpus.topic, "commonneedle", limit=25)
        )
        return rows, len(rows)

    def search_miss() -> tuple[object, int]:
        rows = search_corpus(corpus.config, corpus.topic, "definitelyabsenttoken", limit=25)
        normalized = sorted(result.path.replace("\\", "/") for result in rows)
        return normalized, len(normalized)

    def links() -> tuple[object, int]:
        result = check_links(root)
        rows = sorted(
            (
                broken.source_file.relative_to(root).as_posix(),
                broken.line_number,
                broken.target_slug,
            )
            for broken in result.broken_links
        )
        value = {
            "broken": rows,
            "files_scanned": result.files_scanned,
            "total_links": result.total_links,
        }
        return value, len(rows)

    def duplicates() -> tuple[object, int]:
        rows = sorted(
            (tuple(sorted(group.paths)), group.similarity)
            for group in collect_near_duplicates(topic_dir)
        )
        return rows, len(rows)

    def dashboard() -> tuple[object, int]:
        snapshot = dashboard_snapshot(corpus.config)
        value = {
            "brief_count": snapshot["brief_count"],
            "corpus_health_warnings": len(snapshot["corpus_health_warnings"]),
            "full_videos": snapshot["full_videos"],
            "page_count": snapshot["page_count"],
            "paper_count": snapshot["paper_count"],
            "report_count": snapshot["report_count"],
            "scan_videos": snapshot["scan_videos"],
            "site_count": snapshot["site_count"],
            "synthesis_count": snapshot["synthesis_count"],
            "topics": sorted(snapshot["topics"]),
            "total_channels": snapshot["total_channels"],
            "total_videos": snapshot["total_videos"],
        }
        return value, len(snapshot["topics"])

    return [
        ("discover_insights", insights),
        ("search_hit", search_hit),
        ("search_miss", search_miss),
        ("check_links", links),
        ("near_duplicates", duplicates),
        ("dashboard_snapshot", dashboard),
    ]


def _distill_version() -> str:
    try:
        return version("distillr")
    except PackageNotFoundError:
        return "development"


def _environment() -> dict[str, object]:
    return {
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "distill_version": _distill_version(),
        "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "operating_system": platform.system(),
        "platform_release": platform.release(),
        "processor": platform.processor(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }


def run_corpus_scale(
    corpus: GeneratedCorpus,
    *,
    iterations: int = 5,
    warmups: int = 1,
) -> BenchmarkResult:
    """Run repository-only read operations and return a JSON-serializable result."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")

    suite_before = corpus_tree_digest(corpus.library_root)
    operation_rows: list[BenchmarkOperation] = []
    for name, operation in _operations(corpus):
        operation_before = corpus_tree_digest(corpus.library_root)
        status = "ok"
        error: dict[str, str] | None = None
        samples: list[BenchmarkSample] = []
        try:
            for _ in range(warmups):
                operation()
            for _ in range(iterations):
                sample, _ = _measure(operation)
                samples.append(sample)
        except Exception as exc:  # benchmark errors belong in the result artifact
            status = "error"
            error = {"type": type(exc).__name__, "message": str(exc)}
        operation_after = corpus_tree_digest(corpus.library_root)
        unchanged = operation_before == operation_after
        if not unchanged and status == "ok":
            status = "integrity_error"
        row: BenchmarkOperation = {
            "name": name,
            "status": status,
            "samples": samples,
            "summary": _summary(samples) if samples else {},
            "integrity": {
                "before_digest": operation_before,
                "after_digest": operation_after,
                "unchanged": unchanged,
            },
        }
        if error is not None:
            row["error"] = error
        operation_rows.append(row)

    suite_after = corpus_tree_digest(corpus.library_root)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "suite": "corpus-scale",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": _environment(),
        "corpus": corpus.manifest.to_dict(),
        "execution": {
            "iterations": iterations,
            "warmups": warmups,
            "process_state": "warm-process",
            "filesystem_cache_state": "uncontrolled",
            "quantile_method": "nearest-rank",
        },
        "operations": operation_rows,
        "integrity": {
            "before_digest": suite_before,
            "after_digest": suite_after,
            "unchanged": suite_before == suite_after,
        },
    }
