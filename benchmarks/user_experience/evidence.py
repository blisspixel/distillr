# pyright: strict
"""Fail-closed validation and bundling for user-experience receipts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from benchmarks.corpus_scale.generator import DEFAULT_SEED
from benchmarks.user_experience.runner import (
    DEFAULT_ITERATIONS,
    DEFAULT_WARMUPS,
    EXPORT_SCALE,
    OPERATION_NAMES,
    RESULT_SCHEMA_VERSION,
)
from distill.parsing import strict_json_loads

BUNDLE_SCHEMA_VERSION = "user-experience-evidence-bundle.v1"
_MAX_RECEIPT_BYTES = 64 * 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_RUNNER_OS_TO_PLATFORM = {"Linux": "Linux", "macOS": "Darwin", "Windows": "Windows"}
_RUNNER_ARCH_TO_MACHINES = {
    "ARM64": {"aarch64", "arm64"},
    "X64": {"amd64", "x86_64"},
}


@dataclass(frozen=True, slots=True)
class RunIdentity:
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


def _digest(value: object, label: str) -> str:
    text = _text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _load(path: Path) -> Mapping[str, object]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read receipt: {path.name}") from exc
    if len(payload) > _MAX_RECEIPT_BYTES:
        raise ValueError(f"receipt exceeds {_MAX_RECEIPT_BYTES:,} bytes")
    try:
        return _object(strict_json_loads(payload), path.name)
    except (RecursionError, UnicodeError, ValueError) as exc:
        raise ValueError(f"receipt is not strict JSON: {path.name}") from exc


def _nearest_rank(values: Sequence[int], percentile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _sample(value: object, label: str) -> Mapping[str, object]:
    row = _object(value, label)
    _integer(row.get("wall_ns"), f"{label}.wall_ns")
    _integer(row.get("cpu_ns"), f"{label}.cpu_ns")
    _integer(row.get("peak_rss_bytes"), f"{label}.peak_rss_bytes")
    if row.get("returncode") != 0:
        raise ValueError(f"{label} did not exit successfully")
    _integer(row.get("result_count"), f"{label}.result_count")
    _digest(row.get("result_digest"), f"{label}.result_digest")
    return row


def _validate_environment(payload: Mapping[str, object], identity: RunIdentity) -> tuple[str, str]:
    environment = _object(payload.get("environment"), "environment")
    expected_platform = _RUNNER_OS_TO_PLATFORM.get(identity.runner_os)
    if expected_platform is None or environment.get("operating_system") != expected_platform:
        raise ValueError("receipt operating system does not match the workflow runner")
    expected_machines = _RUNNER_ARCH_TO_MACHINES.get(identity.runner_arch)
    machine = _text(environment.get("architecture"), "environment.architecture").casefold()
    if expected_machines is None or machine not in expected_machines:
        raise ValueError("receipt architecture does not match the workflow runner")
    project_version = _text(environment.get("project_version"), "environment.project_version")
    installed_version = _text(
        environment.get("installed_distill_version"),
        "environment.installed_distill_version",
    )
    if (
        environment.get("installed_distill_version_matches_project") is not True
        or installed_version != project_version
    ):
        raise ValueError("receipt did not measure the checked-out project")
    if environment.get("source_fingerprint_kind") != "normalized-source-tree-sha256":
        raise ValueError("unsupported source fingerprint kind")
    fingerprint = _digest(
        environment.get("source_fingerprint_sha256"),
        "environment.source_fingerprint_sha256",
    )
    _integer(environment.get("source_file_count"), "environment.source_file_count", minimum=1)
    return project_version, fingerprint


def _validate_artifacts(payload: Mapping[str, object]) -> Mapping[str, object]:
    artifacts = _object(payload.get("artifacts"), "artifacts")
    for name, suffix in (("wheel", ".whl"), ("sdist", ".tar.gz")):
        artifact = _object(artifacts.get(name), f"artifacts.{name}")
        if not _text(artifact.get("filename"), f"artifacts.{name}.filename").endswith(suffix):
            raise ValueError(f"artifacts.{name} has the wrong filename")
        _integer(artifact.get("bytes"), f"artifacts.{name}.bytes", minimum=1)
        _digest(artifact.get("sha256"), f"artifacts.{name}.sha256")
    return artifacts


def _validate_install(payload: Mapping[str, object], project_version: str) -> Mapping[str, object]:
    install = _object(payload.get("install"), "install")
    if (
        install.get("status") != "ok"
        or install.get("source") != "local-wheel"
        or install.get("dependency_index") != "https://pypi.org/simple"
        or install.get("cache_state") != "disabled"
        or install.get("network") != "pypi-dependency-resolution"
        or install.get("installed_version_matches_project") is not True
        or install.get("installed_version") != project_version
    ):
        raise ValueError("install receipt does not prove a clean full install")
    create = _sample(install.get("venv_create"), "install.venv_create")
    package = _sample(install.get("package_install"), "install.package_install")
    expected_total = _integer(create.get("wall_ns"), "create.wall_ns") + _integer(
        package.get("wall_ns"), "package.wall_ns"
    )
    if install.get("total_wall_ns") != expected_total:
        raise ValueError("install total_wall_ns does not match component samples")
    _integer(
        install.get("installed_environment_bytes"),
        "install.installed_environment_bytes",
        minimum=1,
    )
    _integer(
        install.get("installed_distribution_count"),
        "install.installed_distribution_count",
        minimum=1,
    )
    inventory = [
        _object(value, f"install.installed_distributions[{index}]")
        for index, value in enumerate(
            _array(install.get("installed_distributions"), "install.installed_distributions")
        )
    ]
    normalized = [
        {
            "name": _text(row.get("name"), "installed distribution name"),
            "version": _text(row.get("version"), "installed distribution version"),
        }
        for row in inventory
    ]
    if install.get("installed_distribution_count") != len(normalized):
        raise ValueError("installed distribution count does not match its inventory")
    expected_inventory_digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        _digest(
            install.get("installed_distribution_inventory_sha256"),
            "install.installed_distribution_inventory_sha256",
        )
        != expected_inventory_digest
    ):
        raise ValueError("installed distribution inventory digest does not match")
    return install


def _validate_operations(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    execution = _object(payload.get("execution"), "execution")
    if (
        execution.get("iterations") != DEFAULT_ITERATIONS
        or execution.get("warmups") != DEFAULT_WARMUPS
        or execution.get("p95_minimum_samples") != 20
        or execution.get("process_state") != "fresh-child-per-sample"
        or execution.get("first_start_policy") != "first-successful-invocation-before-measured-loop"
        or execution.get("filesystem_cache_state") != "uncontrolled-host-state"
        or execution.get("timing_policy") != "advisory"
        or execution.get("credentials") != "stripped"
        or execution.get("rss_sample_interval_ms") != 10
        or execution.get("child_refresh_interval_ms") != 100
    ):
        raise ValueError("receipt is not the canonical execution profile")
    rows = [
        _object(row, f"operations[{index}]")
        for index, row in enumerate(_array(payload.get("operations"), "operations"))
    ]
    names = [_text(row.get("name"), "operation.name") for row in rows]
    if names != list(OPERATION_NAMES):
        raise ValueError("operations do not match the canonical order")
    for row in rows:
        name = _text(row.get("name"), "operation.name")
        if (
            row.get("status") != "ok"
            or row.get("network") != "fail-closed"
            or row.get("result_digests_stable") is not True
        ):
            raise ValueError(f"{name} did not complete in the offline profile")
        samples = [
            _sample(sample, f"{name}.samples[{index}]")
            for index, sample in enumerate(_array(row.get("samples"), f"{name}.samples"))
        ]
        if len(samples) != DEFAULT_ITERATIONS:
            raise ValueError(f"{name} does not have {DEFAULT_ITERATIONS} samples")
        warmups = [
            _sample(sample, f"{name}.warmup_samples[{index}]")
            for index, sample in enumerate(
                _array(row.get("warmup_samples"), f"{name}.warmup_samples")
            )
        ]
        if len(warmups) != DEFAULT_WARMUPS or row.get("first_start_sample") != warmups[0]:
            raise ValueError(f"{name} does not preserve its canonical first-start sample")
        digests = {
            _digest(sample.get("result_digest"), f"{name}.result_digest")
            for sample in [*warmups, *samples]
        }
        if len(digests) != 1:
            raise ValueError(f"{name} result digest changed between samples")
        summary = _object(row.get("summary"), f"{name}.summary")
        wall = [_integer(sample.get("wall_ns"), f"{name}.wall_ns") for sample in samples]
        peak = [
            _integer(sample.get("peak_rss_bytes"), f"{name}.peak_rss_bytes") for sample in samples
        ]
        expected = {
            "sample_count": DEFAULT_ITERATIONS,
            "min_wall_ns": min(wall),
            "p50_wall_ns": _nearest_rank(wall, 0.50),
            "p95_wall_ns": _nearest_rank(wall, 0.95),
            "max_wall_ns": max(wall),
            "max_peak_rss_bytes": max(peak),
        }
        for key, expected_value in expected.items():
            if summary.get(key) != expected_value:
                raise ValueError(f"{name} summary {key} does not match raw samples")
    return rows


def _validate_integrity(payload: Mapping[str, object]) -> None:
    source = _object(payload.get("source_integrity"), "source_integrity")
    source_before = _digest(source.get("before_digest"), "source_integrity.before_digest")
    source_after = _digest(source.get("after_digest"), "source_integrity.after_digest")
    if source.get("unchanged") is not True or source_before != source_after:
        raise ValueError("source integrity changed during measurement")
    corpus = _object(payload.get("export_corpus"), "export_corpus")
    if corpus.get("scale") != EXPORT_SCALE or corpus.get("seed") != DEFAULT_SEED:
        raise ValueError("export corpus does not match the canonical fixture")
    corpus_before = _digest(corpus.get("before_digest"), "export_corpus.before_digest")
    corpus_after = _digest(corpus.get("after_digest"), "export_corpus.after_digest")
    if corpus.get("unchanged") is not True or corpus_before != corpus_after:
        raise ValueError("export operations changed the authoritative corpus")
    uninstall = _object(payload.get("uninstall"), "uninstall")
    if uninstall.get("status") != "ok" or uninstall.get("dependencies_retained") is not True:
        raise ValueError("uninstall receipt is incomplete")
    _sample(uninstall.get("sample"), "uninstall.sample")


def _format_duration(nanoseconds: int) -> str:
    milliseconds = nanoseconds / 1_000_000
    return f"{milliseconds:.1f} ms" if milliseconds < 1_000 else f"{milliseconds / 1_000:.2f} s"


def _format_bytes(byte_count: int) -> str:
    return f"{byte_count / (1024 * 1024):.2f} MiB"


def _render_summary(
    identity: RunIdentity,
    project_version: str,
    artifacts: Mapping[str, object],
    install: Mapping[str, object],
    operations: Sequence[Mapping[str, object]],
) -> str:
    lines = [
        "# Cross-platform user-experience evidence",
        "",
        f"- Repository: `{identity.repository}`",
        f"- Commit: `{identity.commit_sha}`",
        f"- Project version: `{project_version}`",
        f"- Runner: `{identity.runner_os}` / `{identity.runner_arch}` / `{identity.runner_name}`",
        f"- Workflow run: `{identity.workflow_run_id}` attempt `{identity.workflow_run_attempt}`",
        "- Clean install: local wheel, PyPI dependencies, cache disabled",
        f"- Fresh-process and export samples: {DEFAULT_ITERATIONS} measured plus {DEFAULT_WARMUPS} warmup",
        "- Timings: advisory",
        "",
        "## Installation and artifacts",
        "",
        "| Measurement | Value |",
        "|---|---:|",
        f"| Clean install | {_format_duration(_integer(install.get('total_wall_ns'), 'install.total_wall_ns'))} |",
        f"| Installed environment | {_format_bytes(_integer(install.get('installed_environment_bytes'), 'install.bytes'))} |",
        f"| Installed distributions | {_integer(install.get('installed_distribution_count'), 'install.distribution_count')} |",
    ]
    for name in ("wheel", "sdist"):
        artifact = _object(artifacts.get(name), f"artifacts.{name}")
        lines.append(
            f"| {name.title()} | {_format_bytes(_integer(artifact.get('bytes'), f'artifacts.{name}.bytes'))} |"
        )
    lines.extend(
        [
            "",
            "## Fresh-process and export operations",
            "",
            "| Operation | First start | p50 wall | p95 wall | Peak RSS |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in operations:
        summary = _object(row.get("summary"), "operation.summary")
        first_start = _sample(row.get("first_start_sample"), "operation.first_start_sample")
        lines.append(
            "| "
            + _text(row.get("name"), "operation.name")
            + " | "
            + _format_duration(_integer(first_start.get("wall_ns"), "first_start.wall_ns"))
            + " | "
            + _format_duration(_integer(summary.get("p50_wall_ns"), "summary.p50_wall_ns"))
            + " | "
            + _format_duration(_integer(summary.get("p95_wall_ns"), "summary.p95_wall_ns"))
            + " | "
            + _format_bytes(
                _integer(summary.get("max_peak_rss_bytes"), "summary.max_peak_rss_bytes")
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _identity(identity: RunIdentity) -> None:
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


def build_evidence_bundle(
    receipt_path: Path,
    output_dir: Path,
    identity: RunIdentity,
) -> tuple[Path, Path]:
    """Validate one canonical receipt and bind it to workflow provenance."""

    _identity(identity)
    payload = _load(receipt_path)
    if (
        payload.get("schema_version") != RESULT_SCHEMA_VERSION
        or payload.get("suite") != "user-experience"
    ):
        raise ValueError(f"receipt is not a {RESULT_SCHEMA_VERSION} result")
    project_version, fingerprint = _validate_environment(payload, identity)
    artifacts = _validate_artifacts(payload)
    install = _validate_install(payload, project_version)
    operations = _validate_operations(payload)
    _validate_integrity(payload)

    summary = _render_summary(identity, project_version, artifacts, install, operations)
    summary_path = output_dir / "SUMMARY.md"
    manifest_path = output_dir / "MANIFEST.json"
    receipt_bytes = receipt_path.read_bytes()
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
            "iterations": DEFAULT_ITERATIONS,
            "warmups": DEFAULT_WARMUPS,
            "first_start_policy": "first-successful-invocation-before-measured-loop",
            "filesystem_cache_state": "uncontrolled-host-state",
            "export_scale": EXPORT_SCALE,
            "seed": DEFAULT_SEED,
            "install_network": "pypi-dependency-resolution",
            "operation_network": "fail-closed",
            "timing_policy": "advisory",
        },
        "source_fingerprint_sha256": fingerprint,
        "install": {
            "installed_environment_bytes": install["installed_environment_bytes"],
            "installed_distribution_count": install["installed_distribution_count"],
            "installed_distribution_inventory_sha256": install[
                "installed_distribution_inventory_sha256"
            ],
        },
        "receipts": [
            {
                "path": receipt_path.name,
                "bytes": len(receipt_bytes),
                "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            }
        ],
        "summary": {
            "path": summary_path.name,
            "bytes": len(summary.encode("utf-8")),
            "sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
        },
        "verification": {
            "clean_install_completed": True,
            "installed_version_matches_project": True,
            "all_operations_completed": True,
            "all_result_digests_stable": True,
            "authoritative_corpus_unchanged": True,
            "source_integrity_unchanged": True,
            "uninstall_completed": True,
        },
    }
    _atomic_write(summary_path, summary)
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return manifest_path, summary_path


__all__ = ["BUNDLE_SCHEMA_VERSION", "RunIdentity", "build_evidence_bundle"]
