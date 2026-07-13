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
import subprocess
import sys
import sysconfig
import threading
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from benchmarks.corpus_scale.generator import GeneratedCorpus, corpus_tree_digest
from distill.library.insights import discover_insights
from distill.library.links import check_links
from distill.pipeline.dashboard_data import dashboard_snapshot
from distill.pipeline.dedup import collect_near_duplicates
from distill.pipeline.search import search_corpus

RESULT_SCHEMA_VERSION = "corpus-scale-result.v2"
WORKER_RESULT_SCHEMA_VERSION = "corpus-scale-worker-result.v1"
DEFAULT_TIMEOUT_SECONDS = 60.0
MIN_P95_SAMPLES = 20
OPERATION_NAMES = (
    "discover_insights",
    "search_hit",
    "search_miss",
    "check_links",
    "near_duplicates",
    "dashboard_snapshot",
)

type _Operation = Callable[[], tuple[object, int]]


class BenchmarkSample(TypedDict):
    wall_ns: int
    cpu_ns: int
    baseline_rss_bytes: int
    peak_rss_bytes: int
    result_count: int
    result_digest: str
    worker_pid: int


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
    source_integrity: IntegrityResult


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
    result: dict[str, object] = {
        "sample_count": len(samples),
        "min_wall_ns": min(wall),
        "p50_wall_ns": _nearest_rank(wall, 0.50),
        "max_wall_ns": max(wall),
        "p50_cpu_ns": _nearest_rank(cpu, 0.50),
        "max_peak_rss_bytes": max(peak),
        "max_rss_delta_bytes": max(
            maximum - start for maximum, start in zip(peak, baseline, strict=True)
        ),
    }
    if len(samples) >= MIN_P95_SAMPLES:
        result["p95_wall_ns"] = _nearest_rank(wall, 0.95)
    return result


def measure_operation(operation: _Operation) -> tuple[BenchmarkSample, object]:
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
        "worker_pid": os.getpid(),
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


def operation_by_name(corpus: GeneratedCorpus, name: str) -> _Operation:
    """Return one allowlisted benchmark operation for the private worker."""
    if name not in OPERATION_NAMES:
        allowed = ", ".join(OPERATION_NAMES)
        raise ValueError(f"unknown benchmark operation {name!r}; choose from: {allowed}")
    return dict(_operations(corpus))[name]


def _installed_distill_version() -> str:
    try:
        return version("distillr")
    except PackageNotFoundError:
        return "development"


def _project_version(source_root: Path | None = None) -> str:
    """Read the measured source version instead of inferring it from the environment."""
    root = (source_root or Path(__file__).resolve().parents[2]).resolve()
    path = root / "pyproject.toml"
    try:
        raw = cast("dict[str, object]", tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read benchmark project version from {path}") from exc
    project = raw.get("project")
    if not isinstance(project, Mapping):
        raise ValueError(f"benchmark pyproject has no project table: {path}")
    project_mapping = cast("Mapping[str, object]", project)
    project_version = project_mapping.get("version")
    if not isinstance(project_version, str) or not project_version:
        raise ValueError(f"benchmark pyproject has no project version: {path}")
    return project_version


def source_fingerprint(source_root: Path | None = None) -> tuple[str, int]:
    """Hash normalized source bytes so dirty development builds stay identifiable."""
    root = (source_root or Path(__file__).resolve().parents[2]).resolve()
    candidates: set[Path] = set()
    for directory in (root / "distill", root / "benchmarks" / "corpus_scale"):
        if directory.is_dir():
            candidates.update(path for path in directory.rglob("*.py") if path.is_file())
    for name in ("pyproject.toml", "uv.lock"):
        path = root / name
        if path.is_file():
            candidates.add(path)
    if not candidates:
        raise ValueError(f"no benchmark source files found under {root}")

    digest = hashlib.sha256()
    for path in sorted(candidates, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest(), len(candidates)


def _environment() -> dict[str, object]:
    fingerprint, source_files = source_fingerprint()
    project_version = _project_version()
    installed_version = _installed_distill_version()
    return {
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "installed_distill_version": installed_version,
        "installed_distill_version_matches_project": installed_version == project_version,
        "operating_system": platform.system(),
        "platform_release": platform.release(),
        "processor": platform.processor(),
        "project_version": project_version,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "source_fingerprint_kind": "normalized-source-tree-sha256",
        "source_fingerprint_sha256": fingerprint,
        "source_file_count": source_files,
    }


class BenchmarkWorkerError(RuntimeError):
    """One isolated sample failed before it produced valid evidence."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def _required_worker_int(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise BenchmarkWorkerError("WorkerProtocolError", f"worker returned invalid {key}")
    return item


def _parse_worker_payload(stdout: str) -> Mapping[str, object]:
    try:
        raw = json.loads(stdout)
    except ValueError as exc:
        raise BenchmarkWorkerError(
            "WorkerProtocolError",
            "worker did not return one valid JSON result",
        ) from exc
    if not isinstance(raw, Mapping):
        raise BenchmarkWorkerError("WorkerProtocolError", "worker result is not an object")
    return cast("Mapping[str, object]", raw)


def _raise_reported_worker_error(raw: Mapping[str, object]) -> None:
    error_value = raw.get("error")
    error_type = "WorkerOperationError"
    message = "worker operation failed"
    if isinstance(error_value, Mapping):
        error_mapping = cast("Mapping[str, object]", error_value)
        candidate_type = error_mapping.get("type")
        candidate_message = error_mapping.get("message")
        if isinstance(candidate_type, str) and candidate_type:
            error_type = candidate_type
        if isinstance(candidate_message, str) and candidate_message:
            message = candidate_message
    raise BenchmarkWorkerError(error_type, message)


def _sample_from_mapping(sample_value: Mapping[str, object]) -> BenchmarkSample:
    result_digest = sample_value.get("result_digest")
    if (
        not isinstance(result_digest, str)
        or len(result_digest) != 64
        or any(char not in "0123456789abcdef" for char in result_digest)
    ):
        raise BenchmarkWorkerError("WorkerProtocolError", "worker returned invalid result_digest")
    worker_pid = _required_worker_int(sample_value, "worker_pid")
    if worker_pid < 1:
        raise BenchmarkWorkerError("WorkerProtocolError", "worker returned invalid worker_pid")
    return BenchmarkSample(
        wall_ns=_required_worker_int(sample_value, "wall_ns"),
        cpu_ns=_required_worker_int(sample_value, "cpu_ns"),
        baseline_rss_bytes=_required_worker_int(sample_value, "baseline_rss_bytes"),
        peak_rss_bytes=_required_worker_int(sample_value, "peak_rss_bytes"),
        result_count=_required_worker_int(sample_value, "result_count"),
        result_digest=result_digest,
        worker_pid=worker_pid,
    )


def _parse_worker_sample(stdout: str, operation_name: str) -> BenchmarkSample:
    raw = _parse_worker_payload(stdout)
    if raw.get("schema_version") != WORKER_RESULT_SCHEMA_VERSION:
        raise BenchmarkWorkerError("WorkerProtocolError", "worker result schema is unsupported")
    if raw.get("operation") != operation_name:
        raise BenchmarkWorkerError("WorkerProtocolError", "worker returned the wrong operation")
    if raw.get("status") != "ok":
        _raise_reported_worker_error(raw)
    sample_value = raw.get("sample")
    if not isinstance(sample_value, Mapping):
        raise BenchmarkWorkerError("WorkerProtocolError", "worker result has no sample")
    return _sample_from_mapping(cast("Mapping[str, object]", sample_value))


def _worker_environment() -> dict[str, str]:
    """Return a deterministic worker environment without parent instrumentation."""
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(("COV_CORE_", "COVERAGE_")) or key == "PYTEST_CURRENT_TEST":
            environment.pop(key)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONHASHSEED"] = "0"
    return environment


def _worker_crash_message(operation_name: str, completed: subprocess.CompletedProcess[str]) -> str:
    message = f"{operation_name} worker exited with code {completed.returncode}"
    stderr = completed.stderr.strip()
    if not stderr:
        return message
    compact_stderr = " ".join(stderr.split())
    return f"{message}: {compact_stderr[:500]}"


def _run_worker_sample(
    corpus: GeneratedCorpus,
    operation_name: str,
    *,
    timeout_seconds: float,
) -> BenchmarkSample:
    source_root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "-m",
        "benchmarks.corpus_scale.worker",
        "--workspace",
        str(corpus.workspace),
        f"--worker-token={corpus.worker_token}",
        "--operation",
        operation_name,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=source_root,
            env=_worker_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BenchmarkWorkerError(
            "WorkerTimeout",
            f"{operation_name} exceeded the {timeout_seconds:g}s sample timeout",
        ) from exc
    except OSError as exc:
        raise BenchmarkWorkerError(
            "WorkerLaunchError",
            f"{operation_name} worker could not start: {type(exc).__name__}",
        ) from exc
    if completed.returncode != 0:
        try:
            _parse_worker_sample(completed.stdout, operation_name)
        except BenchmarkWorkerError as exc:
            if exc.error_type != "WorkerProtocolError":
                raise
        raise BenchmarkWorkerError(
            "WorkerCrash",
            _worker_crash_message(operation_name, completed),
        )
    return _parse_worker_sample(completed.stdout, operation_name)


def _selected_operations(
    operations: Sequence[str] | None,
    *,
    timeout_seconds: float,
) -> list[str]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive finite number")
    selected = (
        list(operations) if operations is not None else [str(name) for name in OPERATION_NAMES]
    )
    if not selected:
        raise ValueError("at least one benchmark operation is required")
    if len(selected) != len(set(selected)):
        raise ValueError("benchmark operations cannot be repeated")
    unknown = [name for name in selected if name not in OPERATION_NAMES]
    if unknown:
        raise ValueError(f"unknown benchmark operation: {unknown[0]}")
    return selected


def _collect_isolated_samples(
    corpus: GeneratedCorpus,
    operation_name: str,
    *,
    iterations: int,
    warmups: int,
    timeout_seconds: float,
) -> list[BenchmarkSample]:
    samples: list[BenchmarkSample] = []
    observed_digests: set[str] = set()
    for index in range(warmups + iterations):
        sample = _run_worker_sample(
            corpus,
            operation_name,
            timeout_seconds=timeout_seconds,
        )
        observed_digests.add(sample["result_digest"])
        if index >= warmups:
            samples.append(sample)
    if len(observed_digests) != 1:
        raise BenchmarkWorkerError(
            "ResultDigestMismatch",
            f"{operation_name} returned different results across isolated samples",
        )
    return samples


def _run_benchmark_operation(
    corpus: GeneratedCorpus,
    operation_name: str,
    *,
    iterations: int,
    warmups: int,
    timeout_seconds: float,
) -> BenchmarkOperation:
    before = corpus_tree_digest(corpus.library_root)
    status = "ok"
    error: dict[str, str] | None = None
    samples: list[BenchmarkSample] = []
    try:
        samples = _collect_isolated_samples(
            corpus,
            operation_name,
            iterations=iterations,
            warmups=warmups,
            timeout_seconds=timeout_seconds,
        )
    except BenchmarkWorkerError as exc:
        status = "error"
        error = {"type": exc.error_type, "message": str(exc)}
    after = corpus_tree_digest(corpus.library_root)
    unchanged = before == after
    if not unchanged and status == "ok":
        status = "integrity_error"
    row: BenchmarkOperation = {
        "name": operation_name,
        "status": status,
        "samples": samples,
        "summary": _summary(samples) if status == "ok" and samples else {},
        "integrity": {
            "before_digest": before,
            "after_digest": after,
            "unchanged": unchanged,
        },
    }
    if error is not None:
        row["error"] = error
    return row


def run_corpus_scale(
    corpus: GeneratedCorpus,
    *,
    iterations: int = 5,
    warmups: int = 1,
    operations: Sequence[str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> BenchmarkResult:
    """Run repository-only read operations and return a JSON-serializable result."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")
    selected = _selected_operations(operations, timeout_seconds=timeout_seconds)

    environment = _environment()
    source_before = str(environment["source_fingerprint_sha256"])
    suite_before = corpus_tree_digest(corpus.library_root)
    operation_rows = [
        _run_benchmark_operation(
            corpus,
            name,
            iterations=iterations,
            warmups=warmups,
            timeout_seconds=timeout_seconds,
        )
        for name in selected
    ]

    suite_after = corpus_tree_digest(corpus.library_root)
    source_after, _ = source_fingerprint()
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "suite": "corpus-scale",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "corpus": corpus.manifest.to_dict(),
        "execution": {
            "iterations": iterations,
            "warmups": warmups,
            "process_state": "fresh-child-per-sample",
            "parent_instrumentation": "stripped-from-worker",
            "filesystem_cache_state": "warm-generated",
            "integrity_reads_before_each_operation": True,
            "sample_timeout_seconds": timeout_seconds,
            "quantile_method": "nearest-rank",
            "p95_minimum_samples": MIN_P95_SAMPLES,
        },
        "operations": operation_rows,
        "integrity": {
            "before_digest": suite_before,
            "after_digest": suite_after,
            "unchanged": suite_before == suite_after,
        },
        "source_integrity": {
            "before_digest": source_before,
            "after_digest": source_after,
            "unchanged": source_before == source_after,
        },
    }
