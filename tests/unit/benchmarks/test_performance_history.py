"""Comparable-run and variance-policy tests for performance history."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from benchmarks import performance_history
from benchmarks.performance_history import MetricValue, RunEvidence, build_performance_history


def _run(index: int, operating_system: str, architecture: str) -> RunEvidence:
    metrics: dict[str, MetricValue] = {
        "corpus/100/search_hit": {
            "p50_wall_ns": 10_000_000 + index * 100_000,
            "p95_wall_ns": 12_000_000 + index * 100_000,
            "max_peak_rss_bytes": 50_000_000 + index * 1_000,
        },
        "replay/paper_analyze": {
            "p50_wall_ns": 100_000_000 + index * 1_000_000,
            "p95_wall_ns": 120_000_000 + index * 1_000_000,
            "max_peak_rss_bytes": 70_000_000 + index * 1_000,
        },
    }
    return RunEvidence(
        bundle_dir=Path(f"{operating_system}-{index}"),
        bundle_manifest_sha256=f"{index:064x}",
        workflow_run_id=str(1000 + index),
        workflow_run_attempt="1",
        commit_sha=f"{index:040x}",
        project_version="0.19.68",
        created_at=f"2026-08-{index + 1:02d}T00:00:00Z",
        operating_system=operating_system,
        architecture=architecture,
        runner_name=f"runner-{index}",
        semantic_signature="a" * 64,
        source_fingerprints=("b" * 64, "c" * 64),
        metrics=metrics,
    )


def _paired_runs(count: int = 5) -> list[RunEvidence]:
    return [
        run
        for index in range(count)
        for run in (
            _run(index, "Linux", "X64"),
            _run(index, "macOS", "ARM64"),
        )
    ]


def test_history_requires_five_paired_semantically_comparable_runs() -> None:
    payload = performance_history._history_payload(_paired_runs(), 5)
    assert payload["workflow_run_count"] == 5
    policy = cast("dict[str, object]", payload["regression_policy"])
    assert policy["status"] == "active-advisory"
    assert policy["blocking_timing_gate"] is False

    with pytest.raises(ValueError, match="5 required"):
        performance_history._history_payload(_paired_runs(4), 5)


def test_history_rejects_unpaired_or_semantically_different_runs() -> None:
    unpaired = _paired_runs()
    unpaired.pop()
    with pytest.raises(ValueError, match="Linux and macOS"):
        performance_history._history_payload(unpaired, 5)

    mismatched = _paired_runs()
    last = mismatched[-1]
    mismatched[-1] = replace(last, semantic_signature="d" * 64)
    with pytest.raises(ValueError, match="semantic compatibility"):
        performance_history._history_payload(mismatched, 5)


def test_operation_policy_uses_observed_mad_and_stays_advisory() -> None:
    values: list[MetricValue] = [
        {
            "p50_wall_ns": value,
            "p95_wall_ns": value + 1_000_000,
            "max_peak_rss_bytes": 10_000_000,
        }
        for value in (10_000_000, 10_100_000, 10_200_000, 10_300_000, 10_400_000)
    ]
    result = performance_history._operation_stats(values)
    policy = cast("dict[str, object]", result["advisory_regression"])
    assert policy["relative_threshold"] == 0.20
    assert policy["absolute_floor_ns"] == 1_000_000
    assert policy["blocking"] is False


def test_build_history_hashes_outputs_and_inputs(tmp_path: Path, monkeypatch) -> None:
    runs = _paired_runs()
    paths = [tmp_path / f"bundle-{index}" for index in range(len(runs))]
    by_path = {path.resolve(): run for path, run in zip(paths, runs, strict=True)}
    monkeypatch.setattr(
        performance_history,
        "_load_bundle",
        lambda path: by_path[path.resolve()],
    )
    manifest_path, history_path, summary_path = build_performance_history(
        paths,
        tmp_path / "output",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == performance_history.HISTORY_BUNDLE_SCHEMA_VERSION
    assert manifest["verification"]["minimum_comparable_runs_per_host"] == 5
    assert history["workflow_run_count"] == 5
    assert summary_path.read_text(encoding="utf-8").startswith("# Comparable performance history")
