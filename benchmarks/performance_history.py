# pyright: strict
"""Aggregate validated comparable performance bundles into variance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from benchmarks import evidence_bundle
from benchmarks.evidence_bundle import (
    BUNDLE_SCHEMA_VERSION,
    CANONICAL_ITERATIONS,
    CANONICAL_SCALES,
    CANONICAL_WARMUPS,
)

HISTORY_SCHEMA_VERSION = "performance-history.v1"
HISTORY_BUNDLE_SCHEMA_VERSION = "performance-history-bundle.v1"
DEFAULT_MINIMUM_RUNS = 5
REQUIRED_HOSTS = ("Linux", "macOS")
_MAX_JSON_BYTES = 32 * 1024 * 1024


class MetricValue(TypedDict):
    p50_wall_ns: int
    p95_wall_ns: int
    max_peak_rss_bytes: int


@dataclass(frozen=True, slots=True)
class RunEvidence:
    bundle_dir: Path
    bundle_manifest_sha256: str
    workflow_run_id: str
    workflow_run_attempt: str
    commit_sha: str
    project_version: str
    created_at: str
    operating_system: str
    architecture: str
    runner_name: str
    semantic_signature: str
    source_fingerprints: tuple[str, ...]
    metrics: Mapping[str, MetricValue]


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    raw = cast("dict[object, object]", value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{label} must use string keys")
    return {cast("str", key): item for key, item in raw.items()}


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return cast("list[object]", value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be non-empty text")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _strict_json(path: Path) -> tuple[dict[str, object], bytes]:
    payload = path.read_bytes()
    if not payload or len(payload) > _MAX_JSON_BYTES:
        raise ValueError(f"invalid JSON evidence size: {path}")
    raw: object = json.loads(
        payload, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))
    )
    return _object(raw, path.name), payload


def _hash_file(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()


def _verify_bundle_files(bundle_dir: Path, manifest: Mapping[str, object]) -> None:
    expected = {f"corpus-scale-{scale}.json" for scale in CANONICAL_SCALES} | {
        "workflow-replay.json"
    }
    rows = _array(manifest.get("receipts"), "bundle receipts")
    if len(rows) != len(expected):
        raise ValueError("bundle receipt count does not match the canonical profile")
    found: set[str] = set()
    for value in rows:
        row = _object(value, "bundle receipt")
        name = _text(row.get("path"), "bundle receipt path")
        if Path(name).name != name or name not in expected or name in found:
            raise ValueError("bundle receipt path is unsafe or unexpected")
        size, digest = _hash_file(bundle_dir / name)
        if row.get("bytes") != size or row.get("sha256") != digest:
            raise ValueError(f"bundle receipt hash mismatch: {name}")
        found.add(name)
    summary = _object(manifest.get("summary"), "bundle summary")
    summary_name = _text(summary.get("path"), "bundle summary path")
    if summary_name != "SUMMARY.md":
        raise ValueError("bundle summary path is not canonical")
    size, digest = _hash_file(bundle_dir / summary_name)
    if summary.get("bytes") != size or summary.get("sha256") != digest:
        raise ValueError("bundle summary hash mismatch")


def _metric(operation: Mapping[str, object], label: str) -> MetricValue:
    summary = _object(operation.get("summary"), f"{label}.summary")
    return {
        "p50_wall_ns": _integer(summary.get("p50_wall_ns"), f"{label}.p50"),
        "p95_wall_ns": _integer(summary.get("p95_wall_ns"), f"{label}.p95"),
        "max_peak_rss_bytes": _integer(summary.get("max_peak_rss_bytes"), f"{label}.peak_rss"),
    }


def _operation_identity(operation: Mapping[str, object], label: str) -> dict[str, object]:
    samples = _array(operation.get("samples"), f"{label}.samples")
    if not samples:
        raise ValueError(f"{label} has no samples")
    first = _object(samples[0], f"{label}.samples[0]")
    return {
        "name": _text(operation.get("name"), f"{label}.name"),
        "result_count": _integer(first.get("result_count"), f"{label}.result_count"),
        "result_digest": _text(first.get("result_digest"), f"{label}.result_digest"),
    }


def _semantic_signature(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _load_bundle(bundle_dir: Path) -> RunEvidence:
    resolved = bundle_dir.resolve()
    manifest, manifest_raw = _strict_json(resolved / "MANIFEST.json")
    if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError(f"bundle schema must be {BUNDLE_SCHEMA_VERSION}")
    profile = _object(manifest.get("profile"), "bundle profile")
    if profile != {
        "scales": list(CANONICAL_SCALES),
        "seed": 20260711,
        "iterations": CANONICAL_ITERATIONS,
        "warmups": CANONICAL_WARMUPS,
        "network": "fail-closed",
        "provider": "deterministic-stub",
        "timing_policy": "advisory",
    }:
        raise ValueError("bundle profile is not canonical")
    verification = _object(manifest.get("verification"), "bundle verification")
    if any(verification.get(key) is not True for key in verification):
        raise ValueError("bundle verification is incomplete")
    runner = _object(manifest.get("runner"), "bundle runner")
    operating_system = _text(runner.get("operating_system"), "runner operating system")
    architecture = _text(runner.get("architecture"), "runner architecture")
    runner_name = _text(runner.get("name"), "runner name")
    _verify_bundle_files(resolved, manifest)

    metrics: dict[str, MetricValue] = {}
    semantic_corpus: list[dict[str, object]] = []
    source_fingerprints: set[str] = set()
    versions: set[str] = set()
    for scale in CANONICAL_SCALES:
        path = resolved / f"corpus-scale-{scale}.json"
        validated = evidence_bundle.validate_corpus_receipt(
            path,
            scale=scale,
            expected_os=operating_system,
            expected_arch=architecture,
        )
        payload = evidence_bundle.load_canonical_receipt(path)
        corpus = _object(payload.get("corpus"), f"corpus-scale-{scale}.corpus")
        operations = [
            _object(value, f"corpus-scale-{scale}.operation")
            for value in _array(payload.get("operations"), "corpus operations")
        ]
        identities: list[dict[str, object]] = []
        for operation in operations:
            name = _text(operation.get("name"), "corpus operation name")
            label = f"corpus/{scale}/{name}"
            metrics[label] = _metric(operation, label)
            identities.append(_operation_identity(operation, label))
        semantic_corpus.append(
            {
                "scale": scale,
                "corpus_schema": corpus.get("schema_version"),
                "corpus_digest": corpus.get("digest_sha256"),
                "source_counts": corpus.get("source_counts"),
                "operations": identities,
            }
        )
        versions.add(_text(validated.get("project_version"), "corpus project version"))
        source_fingerprints.add(
            _text(validated.get("source_fingerprint_sha256"), "corpus source fingerprint")
        )

    replay_path = resolved / "workflow-replay.json"
    validated_replay = evidence_bundle.validate_replay_receipt(
        replay_path,
        expected_os=operating_system,
        expected_arch=architecture,
    )
    replay = evidence_bundle.load_canonical_receipt(replay_path)
    fixture = _object(replay.get("fixtures"), "replay fixtures")
    replay_operations = [
        _object(value, "replay operation")
        for value in _array(replay.get("operations"), "replay operations")
    ]
    semantic_replay: list[dict[str, object]] = []
    for operation in replay_operations:
        name = _text(operation.get("name"), "replay operation name")
        label = f"replay/{name}"
        metrics[label] = _metric(operation, label)
        semantic_replay.append(_operation_identity(operation, label))
    versions.add(_text(validated_replay.get("project_version"), "replay project version"))
    source_fingerprints.add(
        _text(
            validated_replay.get("source_fingerprint_sha256"),
            "replay source fingerprint",
        )
    )
    if len(versions) != 1:
        raise ValueError("bundle receipts do not share one project version")
    signature = _semantic_signature(
        {
            "profile": profile,
            "corpus": semantic_corpus,
            "replay_fixture": fixture,
            "replay_operations": semantic_replay,
        }
    )
    return RunEvidence(
        bundle_dir=resolved,
        bundle_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        workflow_run_id=_text(manifest.get("workflow_run_id"), "workflow run id"),
        workflow_run_attempt=_text(manifest.get("workflow_run_attempt"), "workflow run attempt"),
        commit_sha=_text(manifest.get("commit_sha"), "commit sha"),
        project_version=versions.pop(),
        created_at=_text(manifest.get("created_at"), "created at"),
        operating_system=operating_system,
        architecture=architecture,
        runner_name=runner_name,
        semantic_signature=signature,
        source_fingerprints=tuple(sorted(source_fingerprints)),
        metrics=metrics,
    )


def _median_int(values: Sequence[int]) -> int:
    return int(statistics.median(values))


def _operation_stats(values: Sequence[MetricValue]) -> dict[str, object]:
    if not values:
        raise ValueError("operation history is empty")
    p50 = [item["p50_wall_ns"] for item in values]
    p95 = [item["p95_wall_ns"] for item in values]
    peak = [item["max_peak_rss_bytes"] for item in values]
    median_p50 = _median_int(p50)
    deviations = [abs(item - median_p50) for item in p50]
    mad = _median_int(deviations)
    mean = statistics.fmean(p50)
    coefficient = statistics.pstdev(p50) / mean if len(p50) > 1 and mean else 0.0
    relative_range = (max(p50) - min(p50)) / median_p50 if median_p50 else 0.0
    noise_class = "low" if coefficient <= 0.10 else "moderate" if coefficient <= 0.25 else "high"
    absolute_floor = max(1_000_000, math.ceil(3 * mad))
    return {
        "run_count": len(values),
        "p50_wall_ns": {
            "min": min(p50),
            "median": median_p50,
            "max": max(p50),
            "median_absolute_deviation": mad,
            "coefficient_of_variation": round(coefficient, 6),
            "relative_range": round(relative_range, 6),
            "noise_class": noise_class,
        },
        "p95_wall_ns": {"min": min(p95), "median": _median_int(p95), "max": max(p95)},
        "peak_rss_bytes": {"min": min(peak), "median": _median_int(peak), "max": max(peak)},
        "advisory_regression": {
            "relative_threshold": 0.20,
            "absolute_floor_ns": absolute_floor,
            "candidate_peak_rss_ceiling_bytes": math.ceil(max(peak) * 1.25 / (4 * 1024 * 1024))
            * (4 * 1024 * 1024),
            "blocking": False,
        },
    }


def _run_sort_key(run: RunEvidence) -> tuple[int, str, str]:
    try:
        run_id = int(run.workflow_run_id)
    except ValueError:
        run_id = 0
    return run_id, run.workflow_run_attempt, run.created_at


def _history_payload(  # noqa: C901 - validates cross-run pairing and comparability
    runs: Sequence[RunEvidence], minimum_runs: int
) -> dict[str, object]:
    if minimum_runs < DEFAULT_MINIMUM_RUNS:
        raise ValueError(f"minimum_runs cannot be less than {DEFAULT_MINIMUM_RUNS}")
    unique = {
        (run.workflow_run_id, run.workflow_run_attempt, run.operating_system): run for run in runs
    }
    if len(unique) != len(runs):
        raise ValueError("performance history contains duplicate host receipts")
    workflow_hosts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for run in runs:
        workflow_hosts[(run.workflow_run_id, run.workflow_run_attempt)].add(run.operating_system)
    expected_hosts = set(REQUIRED_HOSTS)
    if any(hosts != expected_hosts for hosts in workflow_hosts.values()):
        raise ValueError("every comparable workflow run must contain Linux and macOS receipts")
    signatures = {run.semantic_signature for run in runs}
    if len(signatures) != 1:
        raise ValueError("performance receipts do not share one semantic compatibility signature")
    grouped: dict[tuple[str, str], list[RunEvidence]] = defaultdict(list)
    for run in runs:
        grouped[(run.operating_system, run.architecture)].append(run)
    if {key[0] for key in grouped} != expected_hosts:
        raise ValueError("performance history lacks a required host")

    hosts: list[dict[str, object]] = []
    for (operating_system, architecture), host_runs in sorted(grouped.items()):
        host_runs.sort(key=_run_sort_key)
        if len(host_runs) < minimum_runs:
            raise ValueError(
                f"{operating_system}/{architecture} has {len(host_runs)} runs; {minimum_runs} required"
            )
        metric_names = set(host_runs[0].metrics)
        if any(set(run.metrics) != metric_names for run in host_runs):
            raise ValueError("comparable host receipts have different operation sets")
        metrics = {
            name: _operation_stats([run.metrics[name] for run in host_runs])
            for name in sorted(metric_names)
        }
        hosts.append(
            {
                "operating_system": operating_system,
                "architecture": architecture,
                "run_count": len(host_runs),
                "workflow_runs": [
                    {
                        "workflow_run_id": run.workflow_run_id,
                        "workflow_run_attempt": run.workflow_run_attempt,
                        "commit_sha": run.commit_sha,
                        "project_version": run.project_version,
                        "created_at": run.created_at,
                        "runner_name": run.runner_name,
                        "bundle_manifest_sha256": run.bundle_manifest_sha256,
                        "source_fingerprints": list(run.source_fingerprints),
                    }
                    for run in host_runs
                ],
                "metrics": metrics,
            }
        )
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "semantic_compatibility_signature": next(iter(signatures)),
        "minimum_comparable_runs_per_host": minimum_runs,
        "workflow_run_count": len(workflow_hosts),
        "hosts": hosts,
        "regression_policy": {
            "status": "active-advisory",
            "baseline": "rolling median of at least five comparable run-level p50 values",
            "trigger": "two consecutive comparable runs exceed both the 20 percent relative threshold and the operation absolute noise floor",
            "absolute_noise_floor": "max(1 ms, three times the historical median absolute deviation)",
            "resource_policy": "candidate peak RSS ceiling is 125 percent of the observed maximum rounded to 4 MiB",
            "blocking_timing_gate": False,
            "blocking_resource_gate": False,
            "blocking_correctness_gates": True,
            "reason": "hosted-runner timing remains advisory even after variance characterization",
        },
    }


def _format_ns(value: int) -> str:
    milliseconds = value / 1_000_000
    return f"{milliseconds:.1f} ms" if milliseconds < 1_000 else f"{milliseconds / 1_000:.2f} s"


def _render_summary(payload: Mapping[str, object]) -> str:
    lines = [
        "# Comparable performance history",
        "",
        f"- Workflow runs: `{payload['workflow_run_count']}`",
        f"- Minimum runs per host: `{payload['minimum_comparable_runs_per_host']}`",
        f"- Semantic compatibility: `{payload['semantic_compatibility_signature']}`",
        "- Timing policy: `active-advisory`",
        "- Blocking timing gate: `false`",
        "",
        "The history uses run-level medians, not pooled samples. A timing regression requires two consecutive comparable runs that exceed both 20 percent and the measured absolute noise floor. Correctness and integrity remain blocking.",
        "",
    ]
    for host_value in _array(payload.get("hosts"), "history hosts"):
        host = _object(host_value, "history host")
        lines.extend(
            [
                f"## {host['operating_system']} / {host['architecture']}",
                "",
                f"Comparable runs: `{host['run_count']}`",
                "",
                "| Operation | Median p50 | p50 range | CV | Noise | Advisory absolute floor |",
                "| --- | ---: | ---: | ---: | --- | ---: |",
            ]
        )
        metrics = _object(host.get("metrics"), "host metrics")
        for name, metric_value in metrics.items():
            metric = _object(metric_value, "operation history")
            p50 = _object(metric.get("p50_wall_ns"), "p50 history")
            advisory = _object(metric.get("advisory_regression"), "advisory policy")
            lines.append(
                f"| {name} | {_format_ns(_integer(p50['median'], 'median'))} "
                f"| {_format_ns(_integer(p50['min'], 'minimum'))} to {_format_ns(_integer(p50['max'], 'maximum'))} "
                f"| {float(cast('int | float', p50['coefficient_of_variation'])):.3f} "
                f"| {p50['noise_class']} | {_format_ns(_integer(advisory['absolute_floor_ns'], 'floor'))} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_performance_history(
    bundle_dirs: Sequence[Path],
    output_dir: Path,
    *,
    minimum_runs: int = DEFAULT_MINIMUM_RUNS,
) -> tuple[Path, Path, Path]:
    """Validate comparable bundles, characterize variance, and publish policy."""

    runs = [_load_bundle(path) for path in bundle_dirs]
    history = _history_payload(runs, minimum_runs)
    history_text = json.dumps(history, indent=2, sort_keys=True) + "\n"
    summary = _render_summary(history)
    history_path = output_dir / "HISTORY.json"
    summary_path = output_dir / "SUMMARY.md"
    manifest_path = output_dir / "MANIFEST.json"
    inputs = [
        {
            "workflow_run_id": run.workflow_run_id,
            "workflow_run_attempt": run.workflow_run_attempt,
            "operating_system": run.operating_system,
            "architecture": run.architecture,
            "bundle_manifest_sha256": run.bundle_manifest_sha256,
        }
        for run in sorted(runs, key=lambda item: (*_run_sort_key(item), item.operating_system))
    ]
    manifest = {
        "schema_version": HISTORY_BUNDLE_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": inputs,
        "history": {
            "path": history_path.name,
            "bytes": len(history_text.encode()),
            "sha256": hashlib.sha256(history_text.encode()).hexdigest(),
        },
        "summary": {
            "path": summary_path.name,
            "bytes": len(summary.encode()),
            "sha256": hashlib.sha256(summary.encode()).hexdigest(),
        },
        "verification": {
            "minimum_comparable_runs_per_host": minimum_runs,
            "required_hosts_complete": True,
            "paired_workflow_runs_complete": True,
            "semantic_compatibility_complete": True,
            "raw_receipt_hashes_complete": True,
            "advisory_policy_derived": True,
            "blocking_timing_gate": False,
        },
    }
    _atomic_write(history_path, history_text)
    _atomic_write(summary_path, summary)
    _atomic_write(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest_path, history_path, summary_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate comparable performance evidence")
    parser.add_argument("--bundle-dir", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-runs", type=int, default=DEFAULT_MINIMUM_RUNS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = build_performance_history(
            args.bundle_dir,
            args.output_dir,
            minimum_runs=args.minimum_runs,
        )
    except (OSError, RecursionError, UnicodeError, ValueError) as exc:
        sys.stderr.write(f"performance history failed: {exc}\n")
        return 1
    sys.stdout.write("\n".join(str(path) for path in paths) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_MINIMUM_RUNS",
    "HISTORY_BUNDLE_SCHEMA_VERSION",
    "HISTORY_SCHEMA_VERSION",
    "REQUIRED_HOSTS",
    "MetricValue",
    "RunEvidence",
    "build_performance_history",
    "main",
]
