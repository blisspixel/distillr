"""Correctness tests for frozen workflow replay."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from benchmarks.workflow_replay import (
    OPERATION_NAMES,
    RESULT_SCHEMA_VERSION,
    run_workflow_replay,
    temporary_workspace,
)
from benchmarks.workflow_replay import runner as runner_module
from benchmarks.workflow_replay.fixtures import fixture_digest
from benchmarks.workflow_replay.netguard import install_network_guard
from benchmarks.workflow_replay.runner import ReplaySample
from benchmarks.workflow_replay.workspace import load_workspace


def _sample(index: int) -> ReplaySample:
    return {
        "wall_ns": 100 + index,
        "cpu_ns": 50 + index,
        "provider_wait_ns": 10,
        "distill_owned_ns": 90 + index,
        "baseline_rss_bytes": 100,
        "peak_rss_bytes": 110 + index,
        "result_count": 1,
        "result_digest": "a" * 64,
        "worker_pid": 1000 + index,
    }


def test_fixture_digest_is_stable() -> None:
    assert fixture_digest() == fixture_digest()
    assert len(fixture_digest()) == 64


def test_replay_suite_is_json_serializable_and_offline() -> None:
    with temporary_workspace() as workspace:
        result = run_workflow_replay(workspace, iterations=1, warmups=0)

    assert result["schema_version"] == RESULT_SCHEMA_VERSION
    assert result["source_integrity"]["unchanged"] is True
    assert result["execution"]["network"] == "fail-closed"
    assert result["execution"]["provider"] == "deterministic-stub"
    assert result["execution"]["simulated_provider_wait_ns"] == 0
    assert "p95_wall_ns" not in result["operations"][0]["summary"]
    assert json.loads(json.dumps(result))["suite"] == "workflow-replay"

    operations = {row["name"]: row for row in result["operations"]}
    assert set(operations) == set(OPERATION_NAMES)
    for operation in operations.values():
        assert operation["status"] == "ok", operation.get("error")
        assert len(operation["samples"]) == 1
        sample = operation["samples"][0]
        assert sample["provider_wait_ns"] == 0
        assert sample["distill_owned_ns"] >= 0
        assert sample["wall_ns"] >= sample["distill_owned_ns"]


def test_result_digests_are_stable_across_workspaces() -> None:
    digests: list[dict[str, str]] = []
    for _ in range(2):
        with temporary_workspace() as workspace:
            result = run_workflow_replay(
                workspace,
                iterations=1,
                warmups=0,
                operations=["paper_analyze", "verify_numeric"],
            )
            rows = {row["name"]: row for row in result["operations"]}
            assert rows["paper_analyze"]["status"] == "ok", rows["paper_analyze"].get("error")
            assert rows["verify_numeric"]["status"] == "ok", rows["verify_numeric"].get("error")
            digests.append(
                {
                    name: rows[name]["samples"][0]["result_digest"]
                    for name in ("paper_analyze", "verify_numeric")
                }
            )
    assert digests[0] == digests[1]


def test_verify_numeric_is_clean_against_frozen_receipts() -> None:
    with temporary_workspace() as workspace:
        result = run_workflow_replay(
            workspace,
            iterations=1,
            warmups=0,
            operations=["verify_numeric"],
        )
    operation = result["operations"][0]
    assert operation["status"] == "ok", operation.get("error")
    assert operation["samples"][0]["result_count"] >= 1


def test_paper_and_video_use_distinct_worker_pids() -> None:
    with temporary_workspace() as workspace:
        result = run_workflow_replay(
            workspace,
            iterations=2,
            warmups=0,
            operations=["site_analyze"],
        )
    operation = result["operations"][0]
    assert operation["status"] == "ok", operation.get("error")
    samples = operation["samples"]
    assert len({sample["worker_pid"] for sample in samples}) == 2
    assert len({sample["result_digest"] for sample in samples}) == 1


def test_simulated_wait_is_attributed_to_provider() -> None:
    wait_ns = 8_000_000
    with temporary_workspace() as workspace:
        result = run_workflow_replay(
            workspace,
            iterations=1,
            warmups=0,
            operations=["paper_analyze"],
            wait_ns=wait_ns,
        )
    operation = result["operations"][0]
    assert operation["status"] == "ok", operation.get("error")
    sample = operation["samples"][0]
    assert sample["provider_wait_ns"] >= wait_ns
    assert sample["distill_owned_ns"] <= sample["wall_ns"]
    assert result["execution"]["simulated_provider_wait_ns"] == wait_ns


def test_worker_environment_strips_keys_and_coverage(monkeypatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "real-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "real-secret")
    monkeypatch.setenv("COV_CORE_SOURCE", "distill")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_worker")
    environment = runner_module._worker_environment()
    assert environment["XAI_API_KEY"] == "distill-replay-inert"
    assert "GEMINI_API_KEY" not in environment
    assert "PYTEST_CURRENT_TEST" not in environment
    assert not any(key.startswith("COV_CORE_") for key in environment)


def test_p95_is_suppressed_until_twenty_samples() -> None:
    summary_19 = runner_module._summary([_sample(index) for index in range(19)])
    summary_20 = runner_module._summary([_sample(index) for index in range(20)])
    assert "p95_wall_ns" not in summary_19
    assert "p95_distill_owned_ns" not in summary_19
    assert "p95_wall_ns" in summary_20
    assert "p95_distill_owned_ns" in summary_20


def test_unknown_operation_is_rejected() -> None:
    with temporary_workspace() as workspace, pytest.raises(ValueError, match="unknown"):
        run_workflow_replay(workspace, operations=["not_a_real_op"])


def test_mismatched_worker_token_is_rejected(tmp_path) -> None:
    with temporary_workspace() as workspace:
        marker = workspace.root / "workflow-replay-workspace.json"
        (tmp_path / "workflow-replay-workspace.json").write_text(
            marker.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (tmp_path / "library").mkdir()
        with pytest.raises(ValueError, match="token"):
            load_workspace(tmp_path, "wrong-token")


def test_network_guard_refuses_public_connect() -> None:
    install_network_guard()
    with socket.socket() as client, pytest.raises(OSError, match="public network disabled"):
        client.connect(("example.com", 443))


def test_profile_preview_digest_is_stable_and_has_candidates() -> None:
    with temporary_workspace() as workspace:
        first = run_workflow_replay(
            workspace,
            iterations=1,
            warmups=0,
            operations=["profile_preview"],
        )
    with temporary_workspace() as workspace:
        second = run_workflow_replay(
            workspace,
            iterations=1,
            warmups=0,
            operations=["profile_preview"],
        )
    row = first["operations"][0]
    assert row["status"] == "ok", row.get("error")
    assert row["samples"][0]["result_count"] >= 4
    assert (
        row["samples"][0]["result_digest"] == second["operations"][0]["samples"][0]["result_digest"]
    )


def test_report_synthesize_stays_inside_the_temp_workspace() -> None:
    with temporary_workspace() as workspace:
        result = run_workflow_replay(
            workspace,
            iterations=1,
            warmups=0,
            operations=["report_synthesize"],
        )
    operation = result["operations"][0]
    assert operation["status"] == "ok", operation.get("error")
    assert not (Path.cwd() / "output" / "synthesis-replay.md").exists()
    assert operation["samples"][0]["result_count"] == 1
