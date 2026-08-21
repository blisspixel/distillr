# pyright: strict
"""Validate and package canonical cross-platform performance receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from benchmarks.corpus_scale.generator import DEFAULT_SEED
from benchmarks.corpus_scale.runner import OPERATION_NAMES as CORPUS_OPERATIONS
from benchmarks.corpus_scale.runner import RESULT_SCHEMA_VERSION as CORPUS_SCHEMA_VERSION
from benchmarks.workflow_replay.operations import OPERATION_NAMES as REPLAY_OPERATIONS
from benchmarks.workflow_replay.runner import RESULT_SCHEMA_VERSION as REPLAY_SCHEMA_VERSION
from distill.parsing import strict_json_loads

BUNDLE_SCHEMA_VERSION = "performance-evidence-bundle.v1"
CANONICAL_SCALES = (100, 500, 1_000, 10_000)
CANONICAL_ITERATIONS = 20
CANONICAL_WARMUPS = 1
_MAX_RECEIPT_BYTES = 32 * 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_RUNNER_OS_TO_PLATFORM = {"Linux": "Linux", "macOS": "Darwin", "Windows": "Windows"}
_RUNNER_ARCH_TO_MACHINES = {
    "ARM64": {"aarch64", "arm64"},
    "X64": {"amd64", "x86_64"},
}


@dataclass(frozen=True, slots=True)
class RunIdentity:
    """Public workflow identity recorded beside one evidence bundle."""

    repository: str
    commit_sha: str
    workflow_run_id: str
    workflow_run_attempt: str
    runner_os: str
    runner_arch: str
    runner_name: str


def _object(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast("Mapping[str, object]", value)


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return cast("list[object]", value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be non-empty text")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _hex_digest(value: object, label: str) -> str:
    text = _text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _load_receipt(path: Path) -> Mapping[str, object]:
    try:
        with path.open("rb") as stream:
            content = stream.read(_MAX_RECEIPT_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"cannot read receipt: {path.name}") from exc
    if len(content) > _MAX_RECEIPT_BYTES:
        raise ValueError(f"receipt exceeds {_MAX_RECEIPT_BYTES:,} bytes: {path.name}")
    try:
        return _object(strict_json_loads(content), path.name)
    except (RecursionError, UnicodeError, ValueError) as exc:
        raise ValueError(f"receipt is not strict JSON: {path.name}") from exc


def _execution(payload: Mapping[str, object], label: str) -> Mapping[str, object]:
    execution = _object(payload.get("execution"), f"{label}.execution")
    if execution.get("iterations") != CANONICAL_ITERATIONS:
        raise ValueError(f"{label} must contain {CANONICAL_ITERATIONS} iterations")
    if execution.get("warmups") != CANONICAL_WARMUPS:
        raise ValueError(f"{label} must contain {CANONICAL_WARMUPS} warmup")
    if execution.get("p95_minimum_samples") != CANONICAL_ITERATIONS:
        raise ValueError(f"{label} must require {CANONICAL_ITERATIONS} samples for p95")
    return execution


def _environment(
    payload: Mapping[str, object],
    label: str,
    *,
    expected_os: str,
    expected_arch: str,
) -> Mapping[str, object]:
    environment = _object(payload.get("environment"), f"{label}.environment")
    operating_system = _text(
        environment.get("operating_system"), f"{label}.environment.operating_system"
    )
    platform_os = _RUNNER_OS_TO_PLATFORM.get(expected_os)
    if platform_os is None:
        raise ValueError(f"unsupported runner operating system: {expected_os!r}")
    if operating_system != platform_os:
        raise ValueError(
            f"{label} operating system {operating_system!r} does not match runner {expected_os!r}"
        )
    machine = _text(environment.get("architecture"), f"{label}.environment.architecture")
    expected_machines = _RUNNER_ARCH_TO_MACHINES.get(expected_arch)
    if expected_machines is None:
        raise ValueError(f"unsupported runner architecture: {expected_arch!r}")
    if machine.casefold() not in expected_machines:
        raise ValueError(
            f"{label} architecture {machine!r} does not match runner {expected_arch!r}"
        )
    project_version = _text(
        environment.get("project_version"), f"{label}.environment.project_version"
    )
    installed_version = _text(
        environment.get("installed_distill_version"),
        f"{label}.environment.installed_distill_version",
    )
    if (
        environment.get("installed_distill_version_matches_project") is not True
        or installed_version != project_version
    ):
        raise ValueError(f"{label} did not measure the checked-out project version")
    if environment.get("source_fingerprint_kind") != "normalized-source-tree-sha256":
        raise ValueError(f"{label} has an unsupported source fingerprint")
    _hex_digest(
        environment.get("source_fingerprint_sha256"),
        f"{label}.environment.source_fingerprint_sha256",
    )
    _integer(
        environment.get("source_file_count"), f"{label}.environment.source_file_count", minimum=1
    )
    return environment


def _validate_integrity(payload: Mapping[str, object], key: str, label: str) -> None:
    integrity = _object(payload.get(key), f"{label}.{key}")
    before = _hex_digest(integrity.get("before_digest"), f"{label}.{key}.before_digest")
    after = _hex_digest(integrity.get("after_digest"), f"{label}.{key}.after_digest")
    if integrity.get("unchanged") is not True or before != after:
        raise ValueError(f"{label}.{key} must prove unchanged input")


def _validate_samples(
    samples: Sequence[object], operation_label: str
) -> tuple[list[int], list[int]]:
    digests: set[str] = set()
    wall_times: list[int] = []
    peak_memory: list[int] = []
    for index, sample in enumerate(samples):
        sample_label = f"{operation_label}.samples[{index}]"
        sample_row = _object(sample, sample_label)
        _integer(sample_row.get("worker_pid"), f"{sample_label}.worker_pid", minimum=1)
        wall_times.append(_integer(sample_row.get("wall_ns"), f"{sample_label}.wall_ns"))
        _integer(sample_row.get("cpu_ns"), f"{sample_label}.cpu_ns")
        peak_memory.append(
            _integer(sample_row.get("peak_rss_bytes"), f"{sample_label}.peak_rss_bytes")
        )
        _integer(sample_row.get("result_count"), f"{sample_label}.result_count")
        digests.add(_hex_digest(sample_row.get("result_digest"), f"{sample_label}.result_digest"))
    if len(digests) != 1:
        raise ValueError(f"{operation_label} result digest changed between samples")
    return wall_times, peak_memory


def _nearest_rank(values: Sequence[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _validate_operation_rows(
    payload: Mapping[str, object],
    *,
    expected_names: Sequence[str],
    label: str,
    require_integrity: bool,
) -> list[Mapping[str, object]]:
    operations = [
        _object(row, f"{label}.operations[{index}]")
        for index, row in enumerate(_array(payload.get("operations"), f"{label}.operations"))
    ]
    names = [_text(row.get("name"), f"{label}.operations.name") for row in operations]
    if names != list(expected_names):
        raise ValueError(f"{label} operations do not match the canonical order")

    for row in operations:
        name = _text(row.get("name"), f"{label}.operations.name")
        operation_label = f"{label}.{name}"
        if row.get("status") != "ok" or row.get("error") not in (None, {}):
            raise ValueError(f"{operation_label} did not complete successfully")
        samples = _array(row.get("samples"), f"{operation_label}.samples")
        if len(samples) != CANONICAL_ITERATIONS:
            raise ValueError(f"{operation_label} must contain {CANONICAL_ITERATIONS} samples")
        wall_times, peak_memory = _validate_samples(samples, operation_label)
        summary = _object(row.get("summary"), f"{operation_label}.summary")
        if summary.get("sample_count") != CANONICAL_ITERATIONS:
            raise ValueError(f"{operation_label} summary has the wrong sample count")
        expected_summary = {
            "p50_wall_ns": _nearest_rank(wall_times, 0.50),
            "p95_wall_ns": _nearest_rank(wall_times, 0.95),
            "max_peak_rss_bytes": max(peak_memory),
        }
        for key, expected in expected_summary.items():
            if summary.get(key) != expected:
                raise ValueError(f"{operation_label} summary {key} does not match raw samples")
        if require_integrity:
            _validate_integrity(row, "integrity", operation_label)
    return operations


def _validate_corpus_receipt(
    path: Path,
    *,
    scale: int,
    expected_os: str,
    expected_arch: str,
) -> Mapping[str, object]:
    label = path.name
    payload = _load_receipt(path)
    if (
        payload.get("schema_version") != CORPUS_SCHEMA_VERSION
        or payload.get("suite") != "corpus-scale"
    ):
        raise ValueError(f"{label} is not a {CORPUS_SCHEMA_VERSION} receipt")
    environment = _environment(
        payload,
        label,
        expected_os=expected_os,
        expected_arch=expected_arch,
    )
    execution = _execution(payload, label)
    if execution.get("filesystem_cache_state") != "warm-generated":
        raise ValueError(f"{label} must identify its warmed filesystem state")
    corpus = _object(payload.get("corpus"), f"{label}.corpus")
    if corpus.get("scale") != scale or corpus.get("seed") != DEFAULT_SEED:
        raise ValueError(f"{label} does not match canonical scale {scale} and seed {DEFAULT_SEED}")
    _validate_integrity(payload, "integrity", label)
    _validate_integrity(payload, "source_integrity", label)
    operations = _validate_operation_rows(
        payload,
        expected_names=CORPUS_OPERATIONS,
        label=label,
        require_integrity=True,
    )
    return {
        "suite": "corpus-scale",
        "scale": scale,
        "project_version": environment["project_version"],
        "source_fingerprint_sha256": environment["source_fingerprint_sha256"],
        "operations": operations,
    }


def _validate_replay_waits(operations: Sequence[Mapping[str, object]], label: str) -> None:
    for operation in operations:
        name = _text(operation.get("name"), f"{label}.operations.name")
        operation_label = f"{label}.{name}"
        samples = _array(operation.get("samples"), f"{operation_label}.samples")
        for index, sample in enumerate(samples):
            sample_label = f"{operation_label}.samples[{index}]"
            row = _object(sample, sample_label)
            wall_ns = _integer(row.get("wall_ns"), f"{sample_label}.wall_ns")
            wait_ns = _integer(row.get("provider_wait_ns"), f"{sample_label}.provider_wait_ns")
            owned_ns = _integer(row.get("distill_owned_ns"), f"{sample_label}.distill_owned_ns")
            if wait_ns != 0 or owned_ns != wall_ns:
                raise ValueError(f"{sample_label} contains nonzero simulated provider wait")
        summary = _object(operation.get("summary"), f"{operation_label}.summary")
        if (
            summary.get("p50_provider_wait_ns") != 0
            or summary.get("p50_distill_owned_ns") != summary.get("p50_wall_ns")
            or summary.get("p95_distill_owned_ns") != summary.get("p95_wall_ns")
        ):
            raise ValueError(f"{operation_label} summary does not prove zero provider wait")


def _validate_replay_receipt(
    path: Path,
    *,
    expected_os: str,
    expected_arch: str,
) -> Mapping[str, object]:
    label = path.name
    payload = _load_receipt(path)
    if (
        payload.get("schema_version") != REPLAY_SCHEMA_VERSION
        or payload.get("suite") != "workflow-replay"
    ):
        raise ValueError(f"{label} is not a {REPLAY_SCHEMA_VERSION} receipt")
    environment = _environment(
        payload,
        label,
        expected_os=expected_os,
        expected_arch=expected_arch,
    )
    execution = _execution(payload, label)
    if (
        execution.get("network") != "fail-closed"
        or execution.get("provider") != "deterministic-stub"
        or execution.get("simulated_provider_wait_ns") != 0
    ):
        raise ValueError(f"{label} is not the canonical offline replay")
    _validate_integrity(payload, "source_integrity", label)
    operations = _validate_operation_rows(
        payload,
        expected_names=REPLAY_OPERATIONS,
        label=label,
        require_integrity=False,
    )
    _validate_replay_waits(operations, label)
    return {
        "suite": "workflow-replay",
        "project_version": environment["project_version"],
        "source_fingerprint_sha256": environment["source_fingerprint_sha256"],
        "operations": operations,
    }


def _receipt_hash(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.name,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _format_duration(nanoseconds: int) -> str:
    milliseconds = nanoseconds / 1_000_000
    if milliseconds < 1_000:
        return f"{milliseconds:.1f} ms"
    return f"{milliseconds / 1_000:.2f} s"


def _format_memory(byte_count: int) -> str:
    return f"{byte_count / (1024 * 1024):.1f} MiB"


def _summary_table(title: str, operations: Sequence[Mapping[str, object]]) -> list[str]:
    lines = [
        f"## {title}",
        "",
        "| Operation | p50 wall | p95 wall | Peak RSS |",
        "|---|---:|---:|---:|",
    ]
    for operation in operations:
        summary = _object(operation.get("summary"), "operation.summary")
        lines.append(
            "| "
            + _text(operation.get("name"), "operation.name")
            + " | "
            + _format_duration(_integer(summary.get("p50_wall_ns"), "summary.p50_wall_ns"))
            + " | "
            + _format_duration(_integer(summary.get("p95_wall_ns"), "summary.p95_wall_ns"))
            + " | "
            + _format_memory(
                _integer(summary.get("max_peak_rss_bytes"), "summary.max_peak_rss_bytes")
            )
            + " |"
        )
    lines.append("")
    return lines


def _render_summary(
    identity: RunIdentity,
    project_version: str,
    corpus_rows: Sequence[Mapping[str, object]],
    replay_row: Mapping[str, object],
) -> str:
    lines = [
        "# Cross-platform performance evidence",
        "",
        f"- Repository: `{identity.repository}`",
        f"- Commit: `{identity.commit_sha}`",
        f"- Project version: `{project_version}`",
        f"- Runner: `{identity.runner_os}` / `{identity.runner_arch}` / `{identity.runner_name}`",
        f"- Workflow run: `{identity.workflow_run_id}` attempt `{identity.workflow_run_attempt}`",
        f"- Samples: {CANONICAL_ITERATIONS} measured plus {CANONICAL_WARMUPS} warmup",
        "- Network and live model use: none",
        "",
        "Timing is advisory. Receipt integrity, source integrity, operation completion,",
        "sample count, and stable result digests are validated before this summary is written.",
        "",
    ]
    for corpus in corpus_rows:
        scale = _integer(corpus.get("scale"), "corpus.scale", minimum=1)
        operations = cast("Sequence[Mapping[str, object]]", corpus["operations"])
        lines.extend(_summary_table(f"Corpus scale {scale:,}", operations))
    replay_operations = cast("Sequence[Mapping[str, object]]", replay_row["operations"])
    lines.extend(_summary_table("Frozen workflow replay", replay_operations))
    return "\n".join(lines).rstrip() + "\n"


def _validate_identity(identity: RunIdentity) -> None:
    _text(identity.repository, "repository")
    if _COMMIT_RE.fullmatch(identity.commit_sha) is None:
        raise ValueError("commit_sha must be a lowercase Git object id")
    for label, value in (
        ("workflow_run_id", identity.workflow_run_id),
        ("workflow_run_attempt", identity.workflow_run_attempt),
        ("runner_os", identity.runner_os),
        ("runner_arch", identity.runner_arch),
        ("runner_name", identity.runner_name),
    ):
        _text(value, label)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def build_evidence_bundle(
    receipt_dir: Path,
    output_dir: Path,
    identity: RunIdentity,
) -> tuple[Path, Path]:
    """Validate canonical receipts, then write a summary and provenance manifest."""

    _validate_identity(identity)
    corpus_paths = {scale: receipt_dir / f"corpus-scale-{scale}.json" for scale in CANONICAL_SCALES}
    replay_path = receipt_dir / "workflow-replay.json"
    corpus_rows = [
        _validate_corpus_receipt(
            path,
            scale=scale,
            expected_os=identity.runner_os,
            expected_arch=identity.runner_arch,
        )
        for scale, path in corpus_paths.items()
    ]
    replay_row = _validate_replay_receipt(
        replay_path,
        expected_os=identity.runner_os,
        expected_arch=identity.runner_arch,
    )
    versions = {
        _text(row.get("project_version"), "project_version") for row in [*corpus_rows, replay_row]
    }
    if len(versions) != 1:
        raise ValueError("canonical receipts do not share one project version")
    project_version = versions.pop()
    corpus_fingerprints = {
        _text(row.get("source_fingerprint_sha256"), "source_fingerprint_sha256")
        for row in corpus_rows
    }
    if len(corpus_fingerprints) != 1:
        raise ValueError("corpus-scale receipts do not share one source fingerprint")

    summary = _render_summary(identity, project_version, corpus_rows, replay_row)
    summary_path = output_dir / "SUMMARY.md"
    manifest_path = output_dir / "MANIFEST.json"
    receipt_paths = [*corpus_paths.values(), replay_path]
    manifest = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "repository": identity.repository,
        "commit_sha": identity.commit_sha,
        "workflow_run_id": identity.workflow_run_id,
        "workflow_run_attempt": identity.workflow_run_attempt,
        "runner": {
            "operating_system": identity.runner_os,
            "architecture": identity.runner_arch,
            "name": identity.runner_name,
        },
        "project_version": project_version,
        "profile": {
            "scales": list(CANONICAL_SCALES),
            "seed": DEFAULT_SEED,
            "iterations": CANONICAL_ITERATIONS,
            "warmups": CANONICAL_WARMUPS,
            "network": "fail-closed",
            "provider": "deterministic-stub",
            "timing_policy": "advisory",
        },
        "receipts": [_receipt_hash(path) for path in receipt_paths],
        "summary": {
            "path": summary_path.name,
            "bytes": len(summary.encode("utf-8")),
            "sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
        },
        "verification": {
            "all_operations_completed": True,
            "all_result_digests_stable": True,
            "corpus_integrity_unchanged": True,
            "source_integrity_unchanged": True,
        },
    }
    _atomic_write(summary_path, summary)
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return manifest_path, summary_path


def load_canonical_receipt(path: Path) -> Mapping[str, object]:
    """Load one size-limited strict-JSON canonical receipt."""

    return _load_receipt(path)


def validate_corpus_receipt(
    path: Path,
    *,
    scale: int,
    expected_os: str,
    expected_arch: str,
) -> Mapping[str, object]:
    """Validate one canonical corpus-scale receipt for a declared runner."""

    return _validate_corpus_receipt(
        path,
        scale=scale,
        expected_os=expected_os,
        expected_arch=expected_arch,
    )


def validate_replay_receipt(
    path: Path,
    *,
    expected_os: str,
    expected_arch: str,
) -> Mapping[str, object]:
    """Validate one canonical workflow-replay receipt for a declared runner."""

    return _validate_replay_receipt(
        path,
        expected_os=expected_os,
        expected_arch=expected_arch,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and package one canonical cross-platform performance run."
    )
    parser.add_argument("--receipt-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--workflow-run-attempt", required=True)
    parser.add_argument("--runner-os", required=True)
    parser.add_argument("--runner-arch", required=True)
    parser.add_argument("--runner-name", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    identity = RunIdentity(
        repository=args.repository,
        commit_sha=args.commit_sha,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        runner_os=args.runner_os,
        runner_arch=args.runner_arch,
        runner_name=args.runner_name,
    )
    try:
        manifest, summary = build_evidence_bundle(args.receipt_dir, args.output_dir, identity)
    except ValueError as exc:
        raise SystemExit(f"performance evidence validation failed: {exc}") from exc
    sys.stdout.write(f"Validated {manifest} and {summary}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "CANONICAL_ITERATIONS",
    "CANONICAL_SCALES",
    "CANONICAL_WARMUPS",
    "RunIdentity",
    "build_evidence_bundle",
    "load_canonical_receipt",
    "main",
    "validate_corpus_receipt",
    "validate_replay_receipt",
]
