"""Canonical cross-platform performance evidence bundle contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from benchmarks.corpus_scale.generator import DEFAULT_SEED
from benchmarks.corpus_scale.runner import OPERATION_NAMES as CORPUS_OPERATIONS
from benchmarks.corpus_scale.runner import RESULT_SCHEMA_VERSION as CORPUS_SCHEMA_VERSION
from benchmarks.evidence_bundle import (
    BUNDLE_SCHEMA_VERSION,
    CANONICAL_ITERATIONS,
    CANONICAL_SCALES,
    RunIdentity,
    build_evidence_bundle,
)
from benchmarks.workflow_replay.operations import OPERATION_NAMES as REPLAY_OPERATIONS
from benchmarks.workflow_replay.runner import RESULT_SCHEMA_VERSION as REPLAY_SCHEMA_VERSION


def _environment(
    *,
    operating_system: str = "Linux",
    architecture: str = "x86_64",
) -> dict[str, object]:
    return {
        "operating_system": operating_system,
        "architecture": architecture,
        "project_version": "0.19.64",
        "installed_distill_version": "0.19.64",
        "installed_distill_version_matches_project": True,
        "source_fingerprint_kind": "normalized-source-tree-sha256",
        "source_fingerprint_sha256": "1" * 64,
        "source_file_count": 100,
    }


def _integrity() -> dict[str, object]:
    return {
        "before_digest": "2" * 64,
        "after_digest": "2" * 64,
        "unchanged": True,
    }


def _samples() -> list[dict[str, object]]:
    return [
        {
            "worker_pid": index + 1,
            "wall_ns": 1_000_000 + index,
            "cpu_ns": 900_000 + index,
            "baseline_rss_bytes": 40_000_000,
            "peak_rss_bytes": 50_000_000,
            "result_count": 1,
            "result_digest": "3" * 64,
        }
        for index in range(CANONICAL_ITERATIONS)
    ]


def _operation(name: str, *, with_integrity: bool) -> dict[str, object]:
    row: dict[str, object] = {
        "name": name,
        "status": "ok",
        "samples": _samples(),
        "summary": {
            "sample_count": CANONICAL_ITERATIONS,
            "p50_wall_ns": 1_000_009,
            "p95_wall_ns": 1_000_018,
            "max_peak_rss_bytes": 50_000_000,
        },
        "error": None,
    }
    if with_integrity:
        row["integrity"] = _integrity()
    else:
        samples = cast("list[dict[str, object]]", row["samples"])
        for sample in samples:
            sample["provider_wait_ns"] = 0
            sample["distill_owned_ns"] = sample["wall_ns"]
        summary = cast("dict[str, object]", row["summary"])
        summary["p50_provider_wait_ns"] = 0
        summary["p50_distill_owned_ns"] = summary["p50_wall_ns"]
        summary["p95_distill_owned_ns"] = summary["p95_wall_ns"]
    return row


def _execution() -> dict[str, object]:
    return {
        "iterations": CANONICAL_ITERATIONS,
        "warmups": 1,
        "p95_minimum_samples": CANONICAL_ITERATIONS,
    }


def _write_receipts(
    root: Path,
    *,
    operating_system: str = "Linux",
    architecture: str = "x86_64",
) -> None:
    for scale in CANONICAL_SCALES:
        payload = {
            "schema_version": CORPUS_SCHEMA_VERSION,
            "suite": "corpus-scale",
            "environment": _environment(
                operating_system=operating_system,
                architecture=architecture,
            ),
            "execution": {**_execution(), "filesystem_cache_state": "warm-generated"},
            "corpus": {"scale": scale, "seed": DEFAULT_SEED},
            "operations": [_operation(name, with_integrity=True) for name in CORPUS_OPERATIONS],
            "integrity": _integrity(),
            "source_integrity": _integrity(),
        }
        (root / f"corpus-scale-{scale}.json").write_text(json.dumps(payload), encoding="utf-8")
    replay = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "suite": "workflow-replay",
        "environment": _environment(
            operating_system=operating_system,
            architecture=architecture,
        ),
        "execution": {
            **_execution(),
            "network": "fail-closed",
            "provider": "deterministic-stub",
            "simulated_provider_wait_ns": 0,
        },
        "operations": [_operation(name, with_integrity=False) for name in REPLAY_OPERATIONS],
        "source_integrity": _integrity(),
    }
    (root / "workflow-replay.json").write_text(json.dumps(replay), encoding="utf-8")


def _identity() -> RunIdentity:
    return RunIdentity(
        repository="blisspixel/distillr",
        commit_sha="a" * 40,
        workflow_run_id="123",
        workflow_run_attempt="1",
        runner_os="Linux",
        runner_arch="X64",
        runner_name="GitHub Actions 1",
    )


def test_build_evidence_bundle_validates_and_hashes_canonical_receipts(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipts(receipts)

    manifest_path, summary_path = build_evidence_bundle(receipts, receipts, _identity())

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == BUNDLE_SCHEMA_VERSION
    assert manifest["commit_sha"] == "a" * 40
    assert manifest["profile"] == {
        "iterations": 20,
        "network": "fail-closed",
        "provider": "deterministic-stub",
        "scales": [100, 500, 1000, 10000],
        "seed": DEFAULT_SEED,
        "timing_policy": "advisory",
        "warmups": 1,
    }
    assert len(manifest["receipts"]) == 5
    assert manifest["summary"] == {
        "bytes": len(summary_path.read_bytes()),
        "path": "SUMMARY.md",
        "sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
    }
    first = manifest["receipts"][0]
    receipt_path = receipts / first["path"]
    assert first["bytes"] == receipt_path.stat().st_size
    assert first["sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    summary = summary_path.read_text(encoding="utf-8")
    assert "## Corpus scale 10,000" in summary
    assert "## Frozen workflow replay" in summary
    assert "Timing is advisory" in summary


def test_build_evidence_bundle_refuses_result_drift_before_writes(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    output = tmp_path / "output"
    receipts.mkdir()
    _write_receipts(receipts)
    path = receipts / "corpus-scale-100.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["operations"][0]["samples"][1]["result_digest"] = "4" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="result digest changed between samples"):
        build_evidence_bundle(receipts, output, _identity())

    assert not output.exists()


def test_build_evidence_bundle_refuses_runner_os_mismatch(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipts(receipts)
    identity = RunIdentity(
        repository="blisspixel/distillr",
        commit_sha="a" * 40,
        workflow_run_id="123",
        workflow_run_attempt="1",
        runner_os="macOS",
        runner_arch="ARM64",
        runner_name="GitHub Actions 2",
    )

    with pytest.raises(ValueError, match="does not match runner"):
        build_evidence_bundle(receipts, receipts, identity)

    assert not (receipts / "MANIFEST.json").exists()
    assert not (receipts / "SUMMARY.md").exists()


def test_build_evidence_bundle_accepts_github_macos_name(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipts(receipts, operating_system="Darwin", architecture="arm64")
    identity = RunIdentity(
        repository="blisspixel/distillr",
        commit_sha="a" * 40,
        workflow_run_id="123",
        workflow_run_attempt="1",
        runner_os="macOS",
        runner_arch="ARM64",
        runner_name="GitHub Actions 2",
    )

    manifest_path, summary_path = build_evidence_bundle(receipts, receipts, identity)

    assert manifest_path.is_file()
    assert summary_path.is_file()


def test_build_evidence_bundle_refuses_summary_drift(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipts(receipts)
    path = receipts / "workflow-replay.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["operations"][0]["summary"]["p95_wall_ns"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="summary p95_wall_ns does not match raw samples"):
        build_evidence_bundle(receipts, receipts, _identity())


def test_build_evidence_bundle_refuses_replay_provider_wait(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipts(receipts)
    path = receipts / "workflow-replay.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["operations"][0]["samples"][0]["provider_wait_ns"] = 1
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="contains nonzero simulated provider wait"):
        build_evidence_bundle(receipts, receipts, _identity())


def test_build_evidence_bundle_refuses_runner_architecture_mismatch(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_receipts(receipts)
    identity = RunIdentity(
        repository="blisspixel/distillr",
        commit_sha="a" * 40,
        workflow_run_id="123",
        workflow_run_attempt="1",
        runner_os="Linux",
        runner_arch="ARM64",
        runner_name="GitHub Actions 3",
    )

    with pytest.raises(ValueError, match=r"architecture .* does not match runner"):
        build_evidence_bundle(receipts, receipts, identity)
