# pyright: strict
"""Read-only correlation of local command, provider, and cost telemetry."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

PERFORMANCE_EVIDENCE_SCHEMA_VERSION = "performance-evidence.v1"
_OBSERVER_COMMANDS = frozenset({"costs"})


class PerformancePhase(TypedDict):
    """Validated content-free phase evidence for one correlated run."""

    run_id: str
    invocation_type: str
    timestamp: str
    command: str
    phase: str
    wait_class: str
    outcome: str
    wall_seconds: float
    process_cpu_seconds: float
    process_peak_rss_bytes: int | None
    artifact_count: int
    byte_count: int
    error_type: str


class PerformanceCommandEnvelope(TypedDict):
    """Top-level process envelope emitted by ``run_scope``."""

    invocation_type: str
    timestamp: str
    outcome: str
    wall_seconds: float
    process_cpu_seconds: float
    process_peak_rss_bytes: int | None


class PerformanceWorkflow(TypedDict):
    """Best unambiguous RunSummary workflow phase, when one exists."""

    phase: str
    outcome: str
    wall_seconds: float
    process_cpu_seconds: float
    artifact_count: int
    byte_count: int
    error_type: str


class PerformanceRun(TypedDict):
    """One command envelope plus exact-ID workflow, provider, and cost evidence."""

    run_id: str
    command: str
    command_envelope: PerformanceCommandEnvelope
    workflow: PerformanceWorkflow | None
    phases_complete: bool
    nested_phase_count: int | None
    provider_complete: bool
    provider_call_count: int | None
    provider_call_seconds_cumulative: float | None
    cost_complete: bool
    cost_row_count: int | None
    actual_cost_usd: float | None


class PerformanceCoverage(TypedDict):
    """Counts that make correlation gaps and invalid rows explicit."""

    correlated_runs_total: int
    excluded_observer_runs: int
    runs_shown: int
    phase_rows_total: int
    phase_rows_joined: int
    provider_rows_total: int
    provider_rows_joined: int
    cost_rows_total: int
    cost_rows_joined: int
    legacy_unjoinable_phase_rows: int
    legacy_unjoinable_provider_rows: int
    legacy_unjoinable_cost_rows: int
    unanchored_phase_rows: int
    unanchored_provider_rows: int
    unanchored_cost_rows: int
    malformed_phase_rows: int
    malformed_provider_rows: int
    malformed_cost_rows: int
    unreadable_logs: list[str]


class PerformanceSemantics(TypedDict):
    """Machine-readable cautions for downstream consumers."""

    correlation: str
    provider_time: str
    cpu: str
    memory: str
    artifacts: str
    completeness: str


class PerformanceEvidence(TypedDict):
    """Additive JSON payload used by the existing cost surfaces."""

    schema_version: str
    runs: list[PerformanceRun]
    latest_nested_phases: list[PerformancePhase]
    coverage: PerformanceCoverage
    semantics: PerformanceSemantics


class _ProviderRow(TypedDict):
    run_id: str
    elapsed_seconds: float


class _CostRow(TypedDict):
    run_id: str
    actual_cost: float


type _EvidenceRow = PerformancePhase | _ProviderRow | _CostRow


@dataclass(frozen=True, slots=True)
class _LoadedRows[T: _EvidenceRow]:
    rows: list[T]
    malformed: int
    unreadable: bool
    invalid_run_ids: set[str]


def _required_text(row: Mapping[str, object], key: str, *, allow_empty: bool = False) -> str:
    value = row.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"invalid {key}")
    return value


def _run_id(row: Mapping[str, object]) -> str:
    value = row.get("run_id", "")
    if not isinstance(value, str):
        raise ValueError("invalid run_id")
    return value


def _nonnegative_float(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"invalid {key}")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"invalid {key}")
    return parsed


def _nonnegative_int(value: object, key: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"invalid {key}")
    return value


def _optional_nonnegative_int(value: object, key: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, key)


def _parse_phase(row: Mapping[str, object]) -> PerformancePhase:
    if row.get("schema_version") != 1:
        raise ValueError("invalid schema_version")
    return {
        "run_id": _run_id(row),
        "invocation_type": _required_text(row, "invocation_type"),
        "timestamp": _required_text(row, "timestamp"),
        "command": _required_text(row, "command"),
        "phase": _required_text(row, "phase"),
        "wait_class": _required_text(row, "wait_class"),
        "outcome": _required_text(row, "outcome"),
        "wall_seconds": round(_nonnegative_float(row.get("elapsed_seconds"), "elapsed_seconds"), 6),
        "process_cpu_seconds": round(_nonnegative_float(row.get("cpu_seconds"), "cpu_seconds"), 6),
        "process_peak_rss_bytes": _optional_nonnegative_int(
            row.get("peak_rss_bytes"), "peak_rss_bytes"
        ),
        "artifact_count": _nonnegative_int(row.get("artifact_count"), "artifact_count"),
        "byte_count": _nonnegative_int(row.get("byte_count"), "byte_count"),
        "error_type": _required_text(row, "error_type", allow_empty=True),
    }


def _parse_provider(row: Mapping[str, object]) -> _ProviderRow:
    _required_text(row, "timestamp")
    _required_text(row, "model")
    _required_text(row, "workload_tag")
    _required_text(row, "outcome")
    return {
        "run_id": _run_id(row),
        "elapsed_seconds": round(
            _nonnegative_float(row.get("elapsed_seconds"), "elapsed_seconds"), 6
        ),
    }


def _parse_cost(row: Mapping[str, object]) -> _CostRow:
    _required_text(row, "timestamp")
    _required_text(row, "command")
    return {
        "run_id": _run_id(row),
        "actual_cost": round(_nonnegative_float(row.get("actual_cost"), "actual_cost"), 6),
    }


def _read_rows[T: _EvidenceRow](
    path: Path,
    parser: Callable[[Mapping[str, object]], T],
) -> _LoadedRows[T]:
    rows: list[T] = []
    malformed = 0
    invalid_run_ids: set[str] = set()
    try:
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                candidate_run_id: str | None = None
                try:
                    value: object = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError("row is not an object")
                    mapping = cast("Mapping[str, object]", value)
                    raw_run_id = mapping.get("run_id")
                    if isinstance(raw_run_id, str) and raw_run_id:
                        candidate_run_id = raw_run_id
                    rows.append(parser(mapping))
                except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
                    malformed += 1
                    if candidate_run_id is not None:
                        invalid_run_ids.add(candidate_run_id)
    except FileNotFoundError:
        return _LoadedRows(rows=[], malformed=0, unreadable=False, invalid_run_ids=set())
    except (OSError, UnicodeError):
        return _LoadedRows(rows=[], malformed=0, unreadable=True, invalid_run_ids=set())
    return _LoadedRows(
        rows=rows,
        malformed=malformed,
        unreadable=False,
        invalid_run_ids=invalid_run_ids,
    )


def _command_anchors(
    phase_rows: list[PerformancePhase],
) -> tuple[dict[str, PerformancePhase], dict[str, int]]:
    anchors: dict[str, PerformancePhase] = {}
    positions: dict[str, int] = {}
    for position, row in enumerate(phase_rows):
        run_id = row["run_id"]
        if row["phase"] == "command" and run_id:
            anchors[run_id] = row
            positions[run_id] = position
    return anchors, positions


def _group_anchored_rows[T: _EvidenceRow](
    rows: list[T],
    anchor_ids: set[str],
) -> dict[str, list[T]]:
    grouped: defaultdict[str, list[T]] = defaultdict(list)
    for row in rows:
        run_id = row["run_id"]
        if run_id in anchor_ids:
            grouped[run_id].append(row)
    return dict(grouped)


def _workflow_from_phase(phase: PerformancePhase) -> PerformanceWorkflow:
    return {
        "phase": phase["phase"],
        "outcome": phase["outcome"],
        "wall_seconds": phase["wall_seconds"],
        "process_cpu_seconds": phase["process_cpu_seconds"],
        "artifact_count": phase["artifact_count"],
        "byte_count": phase["byte_count"],
        "error_type": phase["error_type"],
    }


def _best_workflow(command: str, phases: Sequence[PerformancePhase]) -> PerformanceWorkflow | None:
    workflow_phases = [row for row in phases if row["phase"].startswith("workflow:")]
    exact = [row for row in workflow_phases if row["phase"] == f"workflow:{command}"]
    if exact:
        return _workflow_from_phase(exact[-1])
    if len(workflow_phases) == 1:
        return _workflow_from_phase(workflow_phases[0])
    return None


def _command_envelope(anchor: PerformancePhase) -> PerformanceCommandEnvelope:
    return {
        "invocation_type": anchor["invocation_type"],
        "timestamp": anchor["timestamp"],
        "outcome": anchor["outcome"],
        "wall_seconds": anchor["wall_seconds"],
        "process_cpu_seconds": anchor["process_cpu_seconds"],
        "process_peak_rss_bytes": anchor["process_peak_rss_bytes"],
    }


def _build_runs(
    selected_ids: list[str],
    anchors: Mapping[str, PerformancePhase],
    phases_by_run: Mapping[str, list[PerformancePhase]],
    providers_by_run: Mapping[str, list[_ProviderRow]],
    costs_by_run: Mapping[str, list[_CostRow]],
    phase_incomplete_ids: set[str],
    provider_incomplete_ids: set[str],
    cost_incomplete_ids: set[str],
) -> list[PerformanceRun]:
    runs: list[PerformanceRun] = []
    for run_id in selected_ids:
        anchor = anchors[run_id]
        phases = phases_by_run.get(run_id, [])
        providers = providers_by_run.get(run_id, [])
        costs = costs_by_run.get(run_id, [])
        phases_complete = run_id not in phase_incomplete_ids
        provider_complete = run_id not in provider_incomplete_ids
        cost_complete = run_id not in cost_incomplete_ids
        runs.append(
            {
                "run_id": run_id,
                "command": anchor["command"],
                "command_envelope": _command_envelope(anchor),
                "workflow": _best_workflow(anchor["command"], phases),
                "phases_complete": phases_complete,
                "nested_phase_count": (
                    sum(row["phase"] != "command" for row in phases) if phases_complete else None
                ),
                "provider_complete": provider_complete,
                "provider_call_count": len(providers) if provider_complete else None,
                "provider_call_seconds_cumulative": (
                    round(sum(row["elapsed_seconds"] for row in providers), 6)
                    if provider_complete
                    else None
                ),
                "cost_complete": cost_complete,
                "cost_row_count": len(costs) if cost_complete else None,
                "actual_cost_usd": (
                    round(sum(row["actual_cost"] for row in costs), 6)
                    if costs and cost_complete
                    else None
                ),
            }
        )
    return runs


def _legacy_count(rows: Sequence[_EvidenceRow]) -> int:
    return sum(not row["run_id"] for row in rows)


def _unanchored_count(rows: Sequence[_EvidenceRow], anchor_ids: set[str]) -> int:
    return sum(bool(row["run_id"]) and row["run_id"] not in anchor_ids for row in rows)


def _unreadable_log_names(
    phase_loaded: _LoadedRows[PerformancePhase],
    provider_loaded: _LoadedRows[_ProviderRow],
    cost_loaded: _LoadedRows[_CostRow],
    cost_log_name: str,
) -> list[str]:
    names: list[str] = []
    if phase_loaded.unreadable:
        names.append("phase_telemetry.jsonl")
    if provider_loaded.unreadable:
        names.append("telemetry.jsonl")
    if cost_loaded.unreadable:
        names.append(cost_log_name)
    return names


def _coverage(
    *,
    anchors: Mapping[str, PerformancePhase],
    runs: list[PerformanceRun],
    phase_loaded: _LoadedRows[PerformancePhase],
    provider_loaded: _LoadedRows[_ProviderRow],
    cost_loaded: _LoadedRows[_CostRow],
    phases_by_run: Mapping[str, list[PerformancePhase]],
    providers_by_run: Mapping[str, list[_ProviderRow]],
    costs_by_run: Mapping[str, list[_CostRow]],
    cost_log_name: str,
) -> PerformanceCoverage:
    anchor_ids = set(anchors)
    return {
        "correlated_runs_total": len(anchor_ids),
        "excluded_observer_runs": sum(
            anchor["command"] in _OBSERVER_COMMANDS for anchor in anchors.values()
        ),
        "runs_shown": len(runs),
        "phase_rows_total": len(phase_loaded.rows),
        "phase_rows_joined": sum(len(rows) for rows in phases_by_run.values()),
        "provider_rows_total": len(provider_loaded.rows),
        "provider_rows_joined": sum(len(rows) for rows in providers_by_run.values()),
        "cost_rows_total": len(cost_loaded.rows),
        "cost_rows_joined": sum(len(rows) for rows in costs_by_run.values()),
        "legacy_unjoinable_phase_rows": _legacy_count(phase_loaded.rows),
        "legacy_unjoinable_provider_rows": _legacy_count(provider_loaded.rows),
        "legacy_unjoinable_cost_rows": _legacy_count(cost_loaded.rows),
        "unanchored_phase_rows": _unanchored_count(phase_loaded.rows, anchor_ids),
        "unanchored_provider_rows": _unanchored_count(provider_loaded.rows, anchor_ids),
        "unanchored_cost_rows": _unanchored_count(cost_loaded.rows, anchor_ids),
        "malformed_phase_rows": phase_loaded.malformed,
        "malformed_provider_rows": provider_loaded.malformed,
        "malformed_cost_rows": cost_loaded.malformed,
        "unreadable_logs": _unreadable_log_names(
            phase_loaded,
            provider_loaded,
            cost_loaded,
            cost_log_name,
        ),
    }


def load_performance_evidence(
    ops_dir: Path,
    *,
    cost_log_path: Path | None = None,
    limit: int = 10,
) -> PerformanceEvidence:
    """Join recent non-observer command runs by exact non-empty ``run_id``."""
    phase_loaded = _read_rows(ops_dir / "phase_telemetry.jsonl", _parse_phase)
    provider_loaded = _read_rows(ops_dir / "telemetry.jsonl", _parse_provider)
    resolved_cost_log = cost_log_path or (ops_dir / "cost_log.jsonl")
    cost_loaded = _read_rows(resolved_cost_log, _parse_cost)

    anchors, anchor_positions = _command_anchors(phase_loaded.rows)
    anchor_ids = set(anchors)
    phases_by_run = _group_anchored_rows(phase_loaded.rows, anchor_ids)
    providers_by_run = _group_anchored_rows(provider_loaded.rows, anchor_ids)
    costs_by_run = _group_anchored_rows(cost_loaded.rows, anchor_ids)
    newest_ids = sorted(anchor_ids, key=anchor_positions.__getitem__, reverse=True)
    eligible_ids = [
        run_id for run_id in newest_ids if anchors[run_id]["command"] not in _OBSERVER_COMMANDS
    ]
    selected_ids = eligible_ids[: max(0, limit)]
    phase_incomplete_ids = set(phase_loaded.invalid_run_ids)
    provider_incomplete_ids = set(provider_loaded.invalid_run_ids)
    cost_incomplete_ids = set(cost_loaded.invalid_run_ids)
    if provider_loaded.unreadable:
        provider_incomplete_ids.update(anchor_ids)
    if cost_loaded.unreadable:
        cost_incomplete_ids.update(anchor_ids)
    runs = _build_runs(
        selected_ids,
        anchors,
        phases_by_run,
        providers_by_run,
        costs_by_run,
        phase_incomplete_ids,
        provider_incomplete_ids,
        cost_incomplete_ids,
    )
    latest_nested_phases = (
        [row for row in phases_by_run.get(selected_ids[0], []) if row["phase"] != "command"]
        if selected_ids
        else []
    )
    return {
        "schema_version": PERFORMANCE_EVIDENCE_SCHEMA_VERSION,
        "runs": runs,
        "latest_nested_phases": latest_nested_phases,
        "coverage": _coverage(
            anchors=anchors,
            runs=runs,
            phase_loaded=phase_loaded,
            provider_loaded=provider_loaded,
            cost_loaded=cost_loaded,
            phases_by_run=phases_by_run,
            providers_by_run=providers_by_run,
            costs_by_run=costs_by_run,
            cost_log_name=resolved_cost_log.name,
        ),
        "semantics": {
            "correlation": "exact_run_id_only_no_legacy_backfill",
            "provider_time": "cumulative_call_time_not_critical_path",
            "cpu": "process_cpu_time_includes_concurrent_work_and_excludes_child_processes",
            "memory": "process_high_water_mark_not_phase_attribution",
            "artifacts": "recorded_workflow_summary_only_unknown_without_workflow_phase",
            "completeness": "invalid_named_rows_nullify_affected_run_rollups",
        },
    }


__all__ = [
    "PERFORMANCE_EVIDENCE_SCHEMA_VERSION",
    "PerformanceCommandEnvelope",
    "PerformanceCoverage",
    "PerformanceEvidence",
    "PerformancePhase",
    "PerformanceRun",
    "PerformanceSemantics",
    "PerformanceWorkflow",
    "load_performance_evidence",
]
