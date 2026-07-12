"""Tests for read-only performance evidence correlation."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from distill.llm.run_context import run_scope
from distill.pipeline.performance_history import (
    PERFORMANCE_EVIDENCE_SCHEMA_VERSION,
    load_performance_evidence,
)
from distill.pipeline.summary import RunSummary, display_summary


def _write_rows(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [row if isinstance(row, str) else json.dumps(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _phase(
    run_id: str,
    phase: str,
    *,
    command: str = "learn",
    timestamp: str = "2026-07-12T12:00:00+00:00",
    outcome: str = "success",
    artifacts: int = 0,
    byte_count: int = 0,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "invocation_type": "cli",
        "timestamp": timestamp,
        "command": command,
        "phase": phase,
        "wait_class": "mixed",
        "outcome": outcome,
        "elapsed_seconds": 2.0,
        "cpu_seconds": 1.0,
        "peak_rss_bytes": 1_048_576,
        "artifact_count": artifacts,
        "byte_count": byte_count,
        "error_type": "",
    }


def _provider(run_id: str, elapsed: float = 0.25) -> dict[str, object]:
    return {
        "run_id": run_id,
        "timestamp": "2026-07-12T12:00:00+00:00",
        "model": "grok-4.3",
        "workload_tag": "analysis",
        "outcome": "success",
        "elapsed_seconds": elapsed,
    }


def _cost(run_id: str, actual_cost: float = 0.25) -> dict[str, object]:
    return {
        "run_id": run_id,
        "timestamp": "2026-07-12T12:00:00+00:00",
        "command": "learn",
        "actual_cost": actual_cost,
    }


def test_missing_logs_return_empty_versioned_evidence(tmp_path: Path) -> None:
    evidence = load_performance_evidence(tmp_path / ".distill")

    assert evidence == {
        "schema_version": PERFORMANCE_EVIDENCE_SCHEMA_VERSION,
        "runs": [],
        "latest_nested_phases": [],
        "coverage": {
            "correlated_runs_total": 0,
            "excluded_observer_runs": 0,
            "runs_shown": 0,
            "phase_rows_total": 0,
            "phase_rows_joined": 0,
            "provider_rows_total": 0,
            "provider_rows_joined": 0,
            "cost_rows_total": 0,
            "cost_rows_joined": 0,
            "legacy_unjoinable_phase_rows": 0,
            "legacy_unjoinable_provider_rows": 0,
            "legacy_unjoinable_cost_rows": 0,
            "unanchored_phase_rows": 0,
            "unanchored_provider_rows": 0,
            "unanchored_cost_rows": 0,
            "malformed_phase_rows": 0,
            "malformed_provider_rows": 0,
            "malformed_cost_rows": 0,
            "unreadable_logs": [],
        },
        "semantics": {
            "correlation": "exact_run_id_only_no_legacy_backfill",
            "provider_time": "cumulative_call_time_not_critical_path",
            "cpu": "process_cpu_time_includes_concurrent_work_and_excludes_child_processes",
            "memory": "process_high_water_mark_not_phase_attribution",
            "artifacts": "recorded_workflow_summary_only_unknown_without_workflow_phase",
            "completeness": "invalid_named_rows_nullify_affected_run_rollups",
        },
    }


def test_exact_joins_workflow_selection_observer_filter_and_coverage(tmp_path: Path) -> None:
    ops = tmp_path / ".distill"
    phases = [
        "not-json",
        [],
        {**_phase("invalid", "command"), "elapsed_seconds": "2"},
        _phase("", "command", command="legacy"),
        _phase("run-one", "workflow:learn", artifacts=1, byte_count=64),
        _phase("run-one", "workflow:learn", artifacts=2, byte_count=128),
        _phase("run-one", "command"),
        _phase("orphan", "workflow:learn"),
        _phase(
            "run-two",
            "workflow:different",
            command="audit",
            outcome="partial",
            artifacts=3,
            byte_count=256,
        ),
        _phase("run-two", "command", command="audit", timestamp="2026-07-12T12:05:00+00:00"),
        _phase("observer", "command", command="costs", timestamp="2026-07-12T12:06:00+00:00"),
    ]
    _write_rows(ops / "phase_telemetry.jsonl", phases)
    _write_rows(
        ops / "telemetry.jsonl",
        [
            _provider(""),
            _provider("run-one", 3),
            _provider("run-one", 4),
            _provider("run-two", 0),
            _provider("orphan", 8),
            {**_provider("run-two"), "elapsed_seconds": "bad"},
        ],
    )
    _write_rows(
        ops / "cost_log.jsonl",
        [
            _cost("", 1),
            _cost("run-one", 0.25),
            _cost("run-one", 0.05),
            _cost("run-two", 0),
            _cost("orphan", 4),
            {**_cost("run-two"), "actual_cost": "bad"},
        ],
    )

    evidence = load_performance_evidence(ops, limit=2)

    assert [run["run_id"] for run in evidence["runs"]] == ["run-two", "run-one"]
    newest, older = evidence["runs"]
    assert newest["command_envelope"] == {
        "invocation_type": "cli",
        "timestamp": "2026-07-12T12:05:00+00:00",
        "outcome": "success",
        "wall_seconds": 2.0,
        "process_cpu_seconds": 1.0,
        "process_peak_rss_bytes": 1_048_576,
    }
    assert newest["workflow"] == {
        "phase": "workflow:different",
        "outcome": "partial",
        "wall_seconds": 2.0,
        "process_cpu_seconds": 1.0,
        "artifact_count": 3,
        "byte_count": 256,
        "error_type": "",
    }
    assert newest["phases_complete"] is True
    assert newest["nested_phase_count"] == 1
    assert newest["provider_complete"] is False
    assert newest["provider_call_count"] is None
    assert newest["provider_call_seconds_cumulative"] is None
    assert newest["cost_complete"] is False
    assert newest["cost_row_count"] is None
    assert newest["actual_cost_usd"] is None
    assert older["phases_complete"] is True
    assert older["provider_complete"] is True
    assert older["cost_complete"] is True
    assert older["workflow"] is not None
    assert older["workflow"]["artifact_count"] == 2
    assert older["provider_call_seconds_cumulative"] == 7
    assert older["actual_cost_usd"] == 0.3
    assert [phase["phase"] for phase in evidence["latest_nested_phases"]] == ["workflow:different"]

    coverage = evidence["coverage"]
    assert coverage == {
        "correlated_runs_total": 3,
        "excluded_observer_runs": 1,
        "runs_shown": 2,
        "phase_rows_total": 8,
        "phase_rows_joined": 6,
        "provider_rows_total": 5,
        "provider_rows_joined": 3,
        "cost_rows_total": 5,
        "cost_rows_joined": 3,
        "legacy_unjoinable_phase_rows": 1,
        "legacy_unjoinable_provider_rows": 1,
        "legacy_unjoinable_cost_rows": 1,
        "unanchored_phase_rows": 1,
        "unanchored_provider_rows": 1,
        "unanchored_cost_rows": 1,
        "malformed_phase_rows": 3,
        "malformed_provider_rows": 1,
        "malformed_cost_rows": 1,
        "unreadable_logs": [],
    }


def test_real_emitter_keeps_command_envelope_separate_from_workflow(tmp_path: Path) -> None:
    ops = tmp_path / ".distill"
    artifact = tmp_path / "artifact.md"
    artifact.write_text("x", encoding="utf-8")
    with run_scope(invocation_type="cli", command="learn", ops_dir=ops):
        summary = RunSummary(command="learn")
        summary.add_output(artifact)
        summary.add_issue("analysis", "failed", severity="error")
        display_summary(summary, console=Console(file=StringIO()), log_dir=tmp_path)

    run = load_performance_evidence(ops)["runs"][0]

    assert run["command_envelope"]["outcome"] == "success"
    assert run["workflow"] is not None
    assert run["workflow"]["outcome"] == "partial"
    assert run["workflow"]["artifact_count"] == 1
    assert run["workflow"]["byte_count"] == 1
    assert run["phases_complete"] is True
    assert run["provider_complete"] is True
    assert run["provider_call_count"] == 0
    assert run["provider_call_seconds_cumulative"] == 0
    assert run["cost_complete"] is True
    assert run["cost_row_count"] == 0
    assert run["actual_cost_usd"] is None


def test_ambiguous_nonmatching_workflows_remain_unknown(tmp_path: Path) -> None:
    ops = tmp_path / ".distill"
    _write_rows(
        ops / "phase_telemetry.jsonl",
        [
            _phase("run", "workflow:first", command="audit"),
            _phase("run", "workflow:second", command="audit"),
            _phase("run", "command", command="audit"),
        ],
    )

    run = load_performance_evidence(ops)["runs"][0]

    assert run["workflow"] is None


def test_invalid_named_siblings_nullify_only_affected_run_rollups(tmp_path: Path) -> None:
    ops = tmp_path / ".distill"
    _write_rows(
        ops / "phase_telemetry.jsonl",
        [
            _phase("run", "workflow:learn", artifacts=2, byte_count=128),
            {**_phase("run", "learn.invalid"), "elapsed_seconds": "bad"},
            _phase("run", "command"),
        ],
    )
    _write_rows(
        ops / "telemetry.jsonl",
        [
            _provider("run", 0),
            {**_provider("run", 1), "model": ""},
        ],
    )
    _write_rows(
        ops / "cost_log.jsonl",
        [
            _cost("run", 0),
            {**_cost("run", 1), "actual_cost": "bad"},
        ],
    )

    evidence = load_performance_evidence(ops)
    run = evidence["runs"][0]

    assert run["phases_complete"] is False
    assert run["nested_phase_count"] is None
    assert run["workflow"] is not None
    assert run["workflow"]["artifact_count"] == 2
    assert run["provider_complete"] is False
    assert run["provider_call_count"] is None
    assert run["provider_call_seconds_cumulative"] is None
    assert run["cost_complete"] is False
    assert run["cost_row_count"] is None
    assert run["actual_cost_usd"] is None
    assert evidence["coverage"]["malformed_phase_rows"] == 1
    assert evidence["coverage"]["malformed_provider_rows"] == 1
    assert evidence["coverage"]["malformed_cost_rows"] == 1


def test_complete_empty_and_explicit_zero_evidence_remain_distinct(tmp_path: Path) -> None:
    ops = tmp_path / ".distill"
    _write_rows(
        ops / "phase_telemetry.jsonl",
        [
            _phase("empty", "command", timestamp="2026-07-12T12:01:00+00:00"),
            _phase("zero", "command", timestamp="2026-07-12T12:02:00+00:00"),
        ],
    )
    _write_rows(ops / "telemetry.jsonl", [_provider("zero", 0)])
    _write_rows(ops / "cost_log.jsonl", [_cost("zero", 0)])

    runs = {run["run_id"]: run for run in load_performance_evidence(ops)["runs"]}
    empty = runs["empty"]
    zero = runs["zero"]

    assert empty["phases_complete"] is True
    assert empty["nested_phase_count"] == 0
    assert empty["provider_complete"] is True
    assert empty["provider_call_count"] == 0
    assert empty["provider_call_seconds_cumulative"] == 0
    assert empty["cost_complete"] is True
    assert empty["cost_row_count"] == 0
    assert empty["actual_cost_usd"] is None
    assert zero["provider_call_count"] == 1
    assert zero["provider_call_seconds_cumulative"] == 0
    assert zero["cost_row_count"] == 1
    assert zero["actual_cost_usd"] == 0


def test_invalid_rows_without_nonempty_string_id_do_not_invalidate_run(tmp_path: Path) -> None:
    ops = tmp_path / ".distill"
    _write_rows(ops / "phase_telemetry.jsonl", [_phase("run", "command")])
    _write_rows(
        ops / "telemetry.jsonl",
        [
            {**_provider(""), "elapsed_seconds": "bad"},
            {**_provider("run"), "run_id": 4},
        ],
    )
    _write_rows(
        ops / "cost_log.jsonl",
        [
            {**_cost(""), "actual_cost": "bad"},
            {**_cost("run"), "run_id": 4},
        ],
    )

    run = load_performance_evidence(ops)["runs"][0]

    assert run["provider_complete"] is True
    assert run["provider_call_count"] == 0
    assert run["cost_complete"] is True
    assert run["cost_row_count"] == 0


@pytest.mark.parametrize(
    ("bad_key", "bad_value"),
    [
        ("schema_version", 2),
        ("run_id", 4),
        ("invocation_type", ""),
        ("timestamp", 4),
        ("command", ""),
        ("phase", ""),
        ("wait_class", ""),
        ("outcome", ""),
        ("elapsed_seconds", True),
        ("elapsed_seconds", "1"),
        ("elapsed_seconds", -1),
        ("elapsed_seconds", float("inf")),
        ("cpu_seconds", float("nan")),
        ("peak_rss_bytes", -1),
        ("peak_rss_bytes", 1.5),
        ("artifact_count", True),
        ("byte_count", -1),
        ("error_type", 4),
    ],
)
def test_phase_schema_invalid_values_are_malformed(
    tmp_path: Path, bad_key: str, bad_value: object
) -> None:
    ops = tmp_path / ".distill"
    _write_rows(ops / "phase_telemetry.jsonl", [{**_phase("run", "command"), bad_key: bad_value}])

    evidence = load_performance_evidence(ops)

    assert evidence["runs"] == []
    assert evidence["coverage"]["malformed_phase_rows"] == 1


@pytest.mark.parametrize(
    "row",
    [
        {**_provider("run"), "timestamp": ""},
        {**_provider("run"), "model": 4},
        {**_provider("run"), "workload_tag": ""},
        {**_provider("run"), "outcome": ""},
        {**_provider("run"), "run_id": 4},
        {**_provider("run"), "elapsed_seconds": -1},
    ],
)
def test_provider_schema_invalid_values_are_malformed(tmp_path: Path, row: object) -> None:
    ops = tmp_path / ".distill"
    _write_rows(ops / "telemetry.jsonl", [row])

    evidence = load_performance_evidence(ops)

    assert evidence["coverage"]["malformed_provider_rows"] == 1


@pytest.mark.parametrize(
    "row",
    [
        {**_cost("run"), "timestamp": ""},
        {**_cost("run"), "command": 4},
        {**_cost("run"), "run_id": 4},
        {**_cost("run"), "actual_cost": float("nan")},
    ],
)
def test_cost_schema_invalid_values_are_malformed(tmp_path: Path, row: object) -> None:
    ops = tmp_path / ".distill"
    _write_rows(ops / "cost_log.jsonl", [row])

    evidence = load_performance_evidence(ops)

    assert evidence["coverage"]["malformed_cost_rows"] == 1


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("phase_telemetry.jsonl", ["phase_telemetry.jsonl"]),
        ("telemetry.jsonl", ["telemetry.jsonl"]),
        ("cost_log.jsonl", ["cost_log.jsonl"]),
    ],
)
def test_unreadable_logs_are_named(tmp_path: Path, name: str, expected: list[str]) -> None:
    ops = tmp_path / ".distill"
    (ops / name).mkdir(parents=True)

    evidence = load_performance_evidence(ops)

    assert evidence["coverage"]["unreadable_logs"] == expected


def test_unreadable_join_logs_nullify_selected_run_rollups(tmp_path: Path) -> None:
    ops = tmp_path / ".distill"
    _write_rows(ops / "phase_telemetry.jsonl", [_phase("run", "command")])
    (ops / "telemetry.jsonl").mkdir()
    (ops / "cost_log.jsonl").mkdir()

    evidence = load_performance_evidence(ops)
    run = evidence["runs"][0]

    assert run["phases_complete"] is True
    assert run["provider_complete"] is False
    assert run["provider_call_count"] is None
    assert run["provider_call_seconds_cumulative"] is None
    assert run["cost_complete"] is False
    assert run["cost_row_count"] is None
    assert run["actual_cost_usd"] is None
    assert evidence["coverage"]["unreadable_logs"] == [
        "telemetry.jsonl",
        "cost_log.jsonl",
    ]


def test_duplicate_anchor_last_wins_and_limit_zero_selects_none(tmp_path: Path) -> None:
    ops = tmp_path / ".distill"
    _write_rows(
        ops / "phase_telemetry.jsonl",
        [
            _phase("run", "command", command="first"),
            {**_phase("run", "command", command="second"), "peak_rss_bytes": None},
        ],
    )

    evidence = load_performance_evidence(ops, limit=0)

    assert evidence["runs"] == []
    assert evidence["coverage"]["correlated_runs_total"] == 1
