"""Correctness and integrity tests for user-experience evidence."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

import pytest

from benchmarks.user_experience import evidence, runner
from benchmarks.user_experience.evidence import RunIdentity, build_evidence_bundle


def _sample(index: int = 0, *, digest: str = "a" * 64) -> runner.CommandSample:
    return {
        "wall_ns": 100 + index,
        "cpu_ns": 50 + index,
        "peak_rss_bytes": 1_000 + index,
        "returncode": 0,
        "result_count": 1,
        "result_digest": digest,
    }


def _canonical_receipt() -> dict[str, object]:
    samples = [_sample(index) for index in range(runner.DEFAULT_ITERATIONS)]
    operations = [
        {
            "name": name,
            "status": "ok",
            "warmup_samples": [_sample()],
            "first_start_sample": _sample(),
            "samples": samples,
            "summary": runner._summary(samples),
            "network": "fail-closed",
            "result_digests_stable": True,
        }
        for name in runner.OPERATION_NAMES
    ]
    return {
        "schema_version": runner.RESULT_SCHEMA_VERSION,
        "suite": "user-experience",
        "generated_at": "2026-08-21T00:00:00Z",
        "environment": {
            "architecture": "x86_64",
            "cpu_count": 4,
            "free_threaded": False,
            "generated_at": "2026-08-21T00:00:00Z",
            "installed_distill_version": "1.2.3",
            "installed_distill_version_matches_project": True,
            "operating_system": "Linux",
            "platform_release": "test",
            "processor": "test",
            "project_version": "1.2.3",
            "python_implementation": "CPython",
            "python_version": "3.12.0",
            "source_file_count": 10,
            "source_fingerprint_kind": "normalized-source-tree-sha256",
            "source_fingerprint_sha256": "b" * 64,
        },
        "artifacts": {
            "wheel": {"filename": "distillr-1.2.3.whl", "bytes": 10, "sha256": "c" * 64},
            "sdist": {
                "filename": "distillr-1.2.3.tar.gz",
                "bytes": 20,
                "sha256": "d" * 64,
            },
        },
        "execution": {
            "iterations": runner.DEFAULT_ITERATIONS,
            "warmups": runner.DEFAULT_WARMUPS,
            "p95_minimum_samples": 20,
            "process_state": "fresh-child-per-sample",
            "first_start_policy": "first-successful-invocation-before-measured-loop",
            "filesystem_cache_state": "uncontrolled-host-state",
            "timing_policy": "advisory",
            "credentials": "stripped",
            "rss_sample_interval_ms": 10,
            "child_refresh_interval_ms": 100,
        },
        "install": {
            "status": "ok",
            "source": "local-wheel",
            "dependency_index": "https://pypi.org/simple",
            "cache_state": "disabled",
            "network": "pypi-dependency-resolution",
            "venv_create": _sample(),
            "package_install": _sample(1),
            "total_wall_ns": 201,
            "installed_environment_bytes": 30,
            "installed_distribution_count": 2,
            "installed_distributions": [
                {"name": "distillr", "version": "1.2.3"},
                {"name": "example", "version": "4.5.6"},
            ],
            "installed_distribution_inventory_sha256": runner._json_digest(
                [
                    {"name": "distillr", "version": "1.2.3"},
                    {"name": "example", "version": "4.5.6"},
                ]
            ),
            "installed_version": "1.2.3",
            "installed_version_matches_project": True,
        },
        "operations": operations,
        "export_corpus": {
            "scale": runner.EXPORT_SCALE,
            "seed": 20260711,
            "topic": "benchmark-scale",
            "source_counts": {"paper": 200, "site": 300, "video": 400, "x": 100},
            "before_digest": "e" * 64,
            "after_digest": "e" * 64,
            "unchanged": True,
        },
        "uninstall": {
            "status": "ok",
            "sample": _sample(2),
            "dependencies_retained": True,
        },
        "source_integrity": {
            "before_digest": "b" * 64,
            "after_digest": "b" * 64,
            "unchanged": True,
        },
    }


def _identity() -> RunIdentity:
    return RunIdentity(
        repository="owner/repository",
        commit_sha="f" * 40,
        workflow_run_id="123",
        workflow_run_attempt="1",
        runner_os="Linux",
        runner_arch="X64",
        runner_name="GitHub Actions 1",
    )


def test_summary_only_emits_p95_for_twenty_samples() -> None:
    summary_19 = runner._summary([_sample(index) for index in range(19)])
    summary_20 = runner._summary([_sample(index) for index in range(20)])
    assert "p95_wall_ns" not in summary_19
    assert summary_20["p95_wall_ns"] == 118


def test_measure_command_drains_large_output_without_deadlock(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "print('x' * 200_000)"]
    result = runner.measure_command(
        command,
        cwd=tmp_path,
        env=os.environ,
        timeout_seconds=10,
        result=lambda stdout, stderr: ((len(stdout), len(stderr)), 1),
    )
    assert result["sample"]["returncode"] == 0
    assert len(result["stdout"]) > 200_000
    assert result["stderr"] == b""


def test_measure_command_times_out_and_kills_child(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(2)"]
    with pytest.raises(TimeoutError, match="timed out"):
        runner.measure_command(
            command,
            cwd=tmp_path,
            env=os.environ,
            timeout_seconds=0.05,
            result=lambda stdout, stderr: ((stdout, stderr), 0),
        )


def test_sanitized_environment_removes_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "secret")
    monkeypatch.setenv("CUSTOM_AUTH_TOKEN", "secret")
    monkeypatch.setenv("COV_CORE_SOURCE", "distill")
    environment = runner._sanitized_environment(tmp_path / "library", tmp_path)
    assert "XAI_API_KEY" not in environment
    assert "CUSTOM_AUTH_TOKEN" not in environment
    assert "COV_CORE_SOURCE" not in environment
    assert environment["DISTILL_COST_MODE"] == "no-metered"
    assert environment["DISTILL_NO_UPDATE_CHECK"] == "1"


def test_source_fingerprint_includes_benchmark_changes(tmp_path: Path) -> None:
    (tmp_path / "distill").mkdir()
    benchmark = tmp_path / "benchmarks" / "user_experience"
    benchmark.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='1'\n")
    (tmp_path / "uv.lock").write_text("lock")
    source = benchmark / "runner.py"
    source.write_text("first\n")
    first, count = runner.source_fingerprint(tmp_path)
    source.write_text("second\n")
    second, second_count = runner.source_fingerprint(tmp_path)
    assert first != second
    assert count == second_count == 3


def test_result_exit_code_tracks_correctness_not_timing() -> None:
    receipt = _canonical_receipt()
    assert runner.result_exit_code(receipt) == 0
    operations = receipt["operations"]
    assert isinstance(operations, list)
    operations[0]["summary"]["p95_wall_ns"] = 10**20
    assert runner.result_exit_code(receipt) == 0
    operations[0]["status"] = "error"
    assert runner.result_exit_code(receipt) == 1


def test_build_evidence_bundle_validates_and_hashes_receipt(tmp_path: Path) -> None:
    receipt_path = tmp_path / "user-experience.json"
    receipt_path.write_text(json.dumps(_canonical_receipt()), encoding="utf-8")
    manifest_path, summary_path = build_evidence_bundle(receipt_path, tmp_path, _identity())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == evidence.BUNDLE_SCHEMA_VERSION
    assert manifest["verification"] == {
        "all_operations_completed": True,
        "all_result_digests_stable": True,
        "authoritative_corpus_unchanged": True,
        "clean_install_completed": True,
        "installed_version_matches_project": True,
        "source_integrity_unchanged": True,
        "uninstall_completed": True,
    }
    assert manifest["receipts"][0]["path"] == receipt_path.name
    assert summary_path.read_text(encoding="utf-8").startswith(
        "# Cross-platform user-experience evidence"
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda payload: payload["install"].update({"cache_state": "warm"}), "clean full"),
        (
            lambda payload: payload["install"]["installed_distributions"][0].update(
                {"version": "9.9.9"}
            ),
            "inventory digest",
        ),
        (
            lambda payload: payload["operations"][0]["samples"][0].update(
                {"result_digest": "0" * 64}
            ),
            "changed between samples",
        ),
        (
            lambda payload: payload["export_corpus"].update({"after_digest": "0" * 64}),
            "authoritative corpus",
        ),
        (
            lambda payload: payload["environment"].update({"operating_system": "Windows"}),
            "operating system",
        ),
    ],
)
def test_build_evidence_bundle_fails_closed(
    tmp_path: Path,
    mutation,
    match: str,
) -> None:
    payload = _canonical_receipt()
    mutation(payload)
    receipt_path = tmp_path / "user-experience.json"
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        build_evidence_bundle(receipt_path, tmp_path, _identity())


def test_platform_mapping_covers_supported_workflow_hosts() -> None:
    assert evidence._RUNNER_OS_TO_PLATFORM == {
        "Linux": "Linux",
        "macOS": "Darwin",
        "Windows": "Windows",
    }
    assert platform.system() in evidence._RUNNER_OS_TO_PLATFORM.values()
