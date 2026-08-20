# pyright: strict
"""Fresh-process workflow replay runner."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypedDict, cast

from benchmarks.workflow_replay.fixtures import fixture_digest
from benchmarks.workflow_replay.measure import (
    MIN_P95_SAMPLES,
    PeakRssSampler,
    environment,
    json_digest,
    nearest_rank,
    source_fingerprint,
)
from benchmarks.workflow_replay.operations import OPERATION_NAMES
from benchmarks.workflow_replay.workspace import ReplayWorkspace

RESULT_SCHEMA_VERSION = "workflow-replay-result.v1"
WORKER_RESULT_SCHEMA_VERSION = "workflow-replay-worker-result.v1"
DEFAULT_TIMEOUT_SECONDS = 30.0
SOURCE_ROOT = Path(__file__).resolve().parents[2]


class ReplaySample(TypedDict):
    wall_ns: int
    cpu_ns: int
    provider_wait_ns: int
    distill_owned_ns: int
    baseline_rss_bytes: int
    peak_rss_bytes: int
    result_count: int
    result_digest: str
    worker_pid: int


class ReplayOperationResult(TypedDict):
    name: str
    status: str
    samples: list[ReplaySample]
    summary: dict[str, object]
    error: dict[str, str] | None


class WorkerError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


def measure_operation(operation: Any) -> tuple[ReplaySample, object]:
    sampler = PeakRssSampler()
    sampler.start()
    try:
        wall_start = time.perf_counter_ns()
        cpu_start = time.process_time_ns()
        value, result_count, provider_wait_ns = operation()
        cpu_ns = time.process_time_ns() - cpu_start
        wall_ns = time.perf_counter_ns() - wall_start
    finally:
        peak_rss = sampler.stop()
    provider_wait_ns = max(0, int(provider_wait_ns))
    distill_owned_ns = max(0, wall_ns - provider_wait_ns)
    sample: ReplaySample = {
        "wall_ns": wall_ns,
        "cpu_ns": cpu_ns,
        "provider_wait_ns": provider_wait_ns,
        "distill_owned_ns": distill_owned_ns,
        "baseline_rss_bytes": sampler.baseline,
        "peak_rss_bytes": peak_rss,
        "result_count": int(result_count),
        "result_digest": json_digest(value),
        "worker_pid": os.getpid(),
    }
    return sample, value


def _summary(samples: list[ReplaySample]) -> dict[str, object]:
    wall = [sample["wall_ns"] for sample in samples]
    owned = [sample["distill_owned_ns"] for sample in samples]
    wait = [sample["provider_wait_ns"] for sample in samples]
    cpu = [sample["cpu_ns"] for sample in samples]
    peak = [sample["peak_rss_bytes"] for sample in samples]
    result: dict[str, object] = {
        "sample_count": len(samples),
        "min_wall_ns": min(wall),
        "p50_wall_ns": nearest_rank(wall, 0.50),
        "max_wall_ns": max(wall),
        "p50_distill_owned_ns": nearest_rank(owned, 0.50),
        "p50_provider_wait_ns": nearest_rank(wait, 0.50),
        "p50_cpu_ns": nearest_rank(cpu, 0.50),
        "max_peak_rss_bytes": max(peak),
    }
    if len(samples) >= MIN_P95_SAMPLES:
        result["p95_wall_ns"] = nearest_rank(wall, 0.95)
        result["p95_distill_owned_ns"] = nearest_rank(owned, 0.95)
    return result


def _worker_environment() -> dict[str, str]:
    environment_vars = os.environ.copy()
    for key in tuple(environment_vars):
        if key.startswith(("COV_CORE_", "COVERAGE_")) or key == "PYTEST_CURRENT_TEST":
            environment_vars.pop(key)
        if key in {
            "XAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
        }:
            environment_vars.pop(key)
    environment_vars["PYTHONDONTWRITEBYTECODE"] = "1"
    environment_vars["PYTHONHASHSEED"] = "0"
    environment_vars["XAI_API_KEY"] = "distill-replay-inert"
    environment_vars["DISTILL_COST_MODE"] = "auto"
    return environment_vars


def _parse_worker_sample(stdout: str, operation_name: str) -> ReplaySample:
    try:
        loaded: object = json.loads(stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        raise WorkerError("WorkerProtocolError", "worker stdout was not JSON") from exc
    if not isinstance(loaded, dict):
        raise WorkerError("WorkerProtocolError", "worker result is not an object")
    raw = cast("Mapping[str, object]", loaded)
    if raw.get("schema_version") != WORKER_RESULT_SCHEMA_VERSION:
        raise WorkerError("WorkerProtocolError", "worker result has the wrong schema")
    if raw.get("operation") != operation_name:
        raise WorkerError("WorkerProtocolError", "worker result operation mismatch")
    if raw.get("status") != "ok":
        error = raw.get("error")
        message = "worker reported failure"
        if isinstance(error, dict):
            reported = cast("Mapping[str, object]", error).get("message")
            if isinstance(reported, str) and reported:
                message = reported
        raise WorkerError("WorkerCrash", message)
    sample_value = raw.get("sample")
    if not isinstance(sample_value, dict):
        raise WorkerError("WorkerProtocolError", "worker result has no sample")
    sample = cast("Mapping[str, object]", sample_value)
    required = (
        "wall_ns",
        "cpu_ns",
        "provider_wait_ns",
        "distill_owned_ns",
        "baseline_rss_bytes",
        "peak_rss_bytes",
        "result_count",
        "result_digest",
        "worker_pid",
    )
    if any(key not in sample for key in required):
        raise WorkerError("WorkerProtocolError", "worker sample is missing fields")
    return cast(ReplaySample, dict(sample))


def _run_worker_sample(
    workspace: ReplayWorkspace,
    operation_name: str,
    *,
    timeout_seconds: float,
    wait_ns: int,
) -> ReplaySample:
    command = [
        sys.executable,
        "-m",
        "benchmarks.workflow_replay.worker",
        "--workspace",
        str(workspace.root),
        f"--worker-token={workspace.worker_token}",
        "--operation",
        operation_name,
        "--wait-ns",
        str(wait_ns),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=SOURCE_ROOT,
            env=_worker_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerError(
            "WorkerTimeout",
            f"{operation_name} exceeded the {timeout_seconds:g}s sample timeout",
        ) from exc
    except OSError as exc:
        raise WorkerError(
            "WorkerLaunchError",
            f"{operation_name} worker could not start: {type(exc).__name__}",
        ) from exc
    if completed.returncode != 0:
        try:
            _parse_worker_sample(completed.stdout, operation_name)
        except WorkerError as exc:
            if exc.error_type != "WorkerProtocolError":
                raise
        detail = " ".join((completed.stderr or completed.stdout or "").split())[:500]
        raise WorkerError(
            "WorkerCrash",
            f"{operation_name} worker exited with code {completed.returncode}: {detail}",
        )
    return _parse_worker_sample(completed.stdout, operation_name)


def _selected(operations: Sequence[str] | None) -> tuple[str, ...]:
    if not operations:
        return OPERATION_NAMES
    unknown = [name for name in operations if name not in OPERATION_NAMES]
    if unknown:
        raise ValueError(f"unknown workflow replay operations: {', '.join(unknown)}")
    return tuple(dict.fromkeys(operations))


def run_workflow_replay(
    workspace: ReplayWorkspace,
    *,
    iterations: int = 5,
    warmups: int = 1,
    operations: Sequence[str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    wait_ns: int = 0,
) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if warmups < 0:
        raise ValueError("warmups cannot be negative")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive finite number")
    if wait_ns < 0:
        raise ValueError("wait_ns cannot be negative")

    selected = _selected(operations)
    env = environment(SOURCE_ROOT)
    source_before = str(env["source_fingerprint_sha256"])
    fixtures = fixture_digest()
    rows: list[ReplayOperationResult] = []
    for name in selected:
        samples: list[ReplaySample] = []
        error: dict[str, str] | None = None
        status = "ok"
        try:
            for index in range(warmups + iterations):
                sample = _run_worker_sample(
                    workspace,
                    name,
                    timeout_seconds=timeout_seconds,
                    wait_ns=wait_ns,
                )
                if index >= warmups:
                    samples.append(sample)
        except WorkerError as exc:
            status = "error"
            error = {"type": exc.error_type, "message": str(exc)}
        summary: dict[str, object] = {"sample_count": len(samples)}
        if samples:
            summary = _summary(samples)
        rows.append(
            {
                "name": name,
                "status": status,
                "samples": samples,
                "summary": summary,
                "error": error,
            }
        )

    source_after, _ = source_fingerprint(SOURCE_ROOT)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "suite": "workflow-replay",
        "environment": env,
        "fixtures": {"digest_sha256": fixtures, "topic": "replay-topic"},
        "execution": {
            "filesystem_cache_state": "fresh-temp-library",
            "iterations": iterations,
            "network": "fail-closed",
            "p95_minimum_samples": MIN_P95_SAMPLES,
            "parent_instrumentation": "stripped-from-worker",
            "process_state": "fresh-child-per-sample",
            "provider": "deterministic-stub",
            "quantile_method": "nearest-rank",
            "sample_timeout_seconds": timeout_seconds,
            "simulated_provider_wait_ns": wait_ns,
            "warmups": warmups,
        },
        "operations": rows,
        "source_integrity": {
            "after_digest": source_after,
            "before_digest": source_before,
            "unchanged": source_before == source_after,
        },
    }
