"""Focused tests for maintain command edge branches."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from distill.cli import app
from distill.commands import _performance_view as performance_view
from distill.commands import maintain as _maintain
from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import slugify_title
from distill.llm.cost_policy import CostPolicyError
from distill.pipeline.performance_history import PerformanceCoverage, PerformanceEvidence

runner = CliRunner()


def _config(tmp_path, **overrides: object) -> DistillConfig:
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
        **overrides,
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: DistillConfig) -> None:
    monkeypatch.setattr(_maintain, "get_config", lambda: config)


def _performance_phase(
    run_id: str,
    phase: str,
    *,
    command: str,
    outcome: str = "success",
    artifact_count: int = 0,
    byte_count: int = 0,
    timestamp: str = "2026-07-12T12:00:00+00:00",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "invocation_type": "cli",
        "timestamp": timestamp,
        "command": command,
        "phase": phase,
        "elapsed_seconds": 2.0,
        "cpu_seconds": 1.0,
        "wait_class": "mixed",
        "outcome": outcome,
        "peak_rss_bytes": 104_857_600,
        "artifact_count": artifact_count,
        "byte_count": byte_count,
        "error_type": "",
    }


def _performance_provider(run_id: str, elapsed_seconds: float) -> dict[str, object]:
    return {
        "run_id": run_id,
        "timestamp": "2026-07-12T12:00:00+00:00",
        "model": "grok-4.3",
        "workload_tag": "analysis",
        "outcome": "success",
        "elapsed_seconds": elapsed_seconds,
    }


def _performance_cost(run_id: str, command: str, actual_cost: float) -> dict[str, object]:
    return {
        "run_id": run_id,
        "timestamp": "2026-07-12T12:00:00+00:00",
        "command": command,
        "actual_cost": actual_cost,
    }


def _performance_coverage(**overrides: object) -> PerformanceCoverage:
    coverage: PerformanceCoverage = {
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
    }
    return cast("PerformanceCoverage", {**coverage, **overrides})


def _empty_performance(coverage: PerformanceCoverage) -> PerformanceEvidence:
    return {
        "schema_version": "performance-evidence.v1",
        "runs": [],
        "latest_nested_phases": [],
        "coverage": coverage,
        "semantics": {
            "correlation": "exact_run_id_only_no_legacy_backfill",
            "provider_time": "cumulative_call_time_not_critical_path",
            "cpu": "process_cpu_time_includes_concurrent_work_and_excludes_child_processes",
            "memory": "process_high_water_mark_not_phase_attribution",
            "artifacts": "recorded_workflow_summary_only_unknown_without_workflow_phase",
            "completeness": "invalid_named_rows_nullify_affected_run_rollups",
        },
    }


def test_costs_json_malformed_log_returns_empty_entries(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    log_file = config.library_dir / "cost_log.jsonl"
    log_file.write_text("not json\n[]\n\n", encoding="utf-8")

    result = runner.invoke(app, ["--json", "costs"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["status"] == "ok"
    assert parsed["data"]["runs"] == []
    assert parsed["data"]["message"] == "No cost entries found."
    assert parsed["data"]["cost_warnings"] == []


def test_costs_json_skips_unsafe_numeric_rows_and_remains_strict(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    log_file = config.library_dir / ".distill" / "cost_log.jsonl"
    log_file.parent.mkdir(parents=True)
    log_file.write_text(
        "\n".join(
            [
                '{"actual_cost": ' + "9" * 5_000 + "}",
                '{"actual_cost": NaN}',
                '{"actual_cost": Infinity}',
                '{"actual_cost": 1e999}',
                '{"actual_cost": true}',
                '{"actual_cost": 1.25, "command": "papers"}',
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--json", "costs"])

    assert result.exit_code == 0, result.output

    def reject_constant(value: str) -> None:
        raise AssertionError(f"non-standard JSON constant emitted: {value}")

    parsed = json.loads(result.output, parse_constant=reject_constant)
    assert parsed["data"]["runs"] == [{"actual_cost": 1.25, "command": "papers"}]
    assert parsed["data"]["total_cost"] == 1.25


def test_costs_json_unreadable_cost_log_is_reported_not_fatal(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    unreadable = config.library_dir / ".distill" / "cost_log.jsonl"
    unreadable.mkdir(parents=True)

    result = runner.invoke(app, ["--json", "costs"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["data"]["runs"] == []
    assert parsed["data"]["message"] == "No cost entries found."
    assert parsed["data"]["performance"]["coverage"]["unreadable_logs"] == ["cost_log.jsonl"]


def test_costs_json_includes_phase_only_performance_evidence(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    ops_dir = config.library_dir / ".distill"
    ops_dir.mkdir(parents=True, exist_ok=True)
    run_id = "phase-only-run"
    (ops_dir / "phase_telemetry.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    _performance_phase(
                        run_id,
                        "audit.scan",
                        command="audit",
                        artifact_count=1,
                        byte_count=64,
                    )
                ),
                json.dumps(_performance_phase(run_id, "command", command="audit")),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (ops_dir / "telemetry.jsonl").write_text(
        json.dumps(_performance_provider(run_id, 0.25)) + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--json", "costs"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    performance = parsed["data"]["performance"]
    assert parsed["data"]["runs"] == []
    assert performance["schema_version"] == "performance-evidence.v1"
    assert performance["runs"][0]["run_id"] == run_id
    assert performance["runs"][0]["command_envelope"]["outcome"] == "success"
    assert performance["runs"][0]["workflow"] is None
    assert performance["runs"][0]["phases_complete"] is True
    assert performance["runs"][0]["nested_phase_count"] == 1
    assert performance["runs"][0]["provider_complete"] is True
    assert performance["runs"][0]["provider_call_seconds_cumulative"] == 0.25
    assert performance["runs"][0]["cost_complete"] is True
    assert performance["runs"][0]["cost_row_count"] == 0
    assert performance["runs"][0]["actual_cost_usd"] is None
    assert performance["latest_nested_phases"][0]["phase"] == "audit.scan"
    assert performance["coverage"]["provider_rows_joined"] == 1


def test_costs_human_renders_correlated_performance_semantics_at_narrow_width(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    ops_dir = config.library_dir / ".distill"
    ops_dir.mkdir(parents=True, exist_ok=True)
    run_id = "12345678-correlated"
    (ops_dir / "phase_telemetry.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    _performance_phase(
                        run_id,
                        "report.research",
                        command="report",
                        timestamp="2026-07-12T12:00:01+00:00",
                    )
                ),
                json.dumps(
                    _performance_phase(
                        run_id,
                        "workflow:report",
                        command="report",
                        outcome="partial",
                        artifact_count=2,
                        byte_count=2048,
                        timestamp="2026-07-12T12:00:09+00:00",
                    )
                ),
                json.dumps(
                    _performance_phase(
                        run_id,
                        "command",
                        command="report",
                        timestamp="2026-07-12T12:00:10+00:00",
                    )
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (ops_dir / "telemetry.jsonl").write_text(
        "\n".join(
            [
                json.dumps(_performance_provider("", 99)),
                json.dumps(_performance_provider(run_id, 4)),
                json.dumps(_performance_provider(run_id, 3)),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (ops_dir / "cost_log.jsonl").write_text(
        "\n".join(
            [
                json.dumps(_performance_cost("", "legacy", 1)),
                json.dumps(_performance_cost(run_id, "report", 0.25)),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["costs"], terminal_width=80)

    assert result.exit_code == 0, result.output
    assert "Performance Evidence" in result.output
    assert "report" in result.output
    assert "100.0 MB" in result.output
    assert "2 / 2.0 KB" in result.output
    assert "workflow:report" in result.output
    assert "partial" in result.output
    assert "process CPU" in result.output
    assert "2 calls / 7.0s cumulative" in result.output
    assert "$0.25" in result.output
    assert "Provider time is cumulative call time" in result.output
    assert "not critical-path wall time" in result.output
    assert "process high-water mark" in result.output
    assert "concurrent MCP work" in result.output
    assert "excludes child-process CPU" in result.output
    assert "Legacy unjoinable rows" in result.output
    assert "timestamp backfill is never attempted" in result.output
    assert "Latest nested phases: report (12345678)" in result.output
    assert "report.research" in result.output


def test_costs_json_and_human_qualify_invalid_named_sibling_rows(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    ops_dir = config.library_dir / ".distill"
    ops_dir.mkdir(parents=True, exist_ok=True)
    run_id = "invalid-sibling-run"
    (ops_dir / "phase_telemetry.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    _performance_phase(
                        run_id,
                        "workflow:report",
                        command="report",
                        artifact_count=1,
                        byte_count=64,
                    )
                ),
                json.dumps(
                    {
                        **_performance_phase(run_id, "report.invalid", command="report"),
                        "elapsed_seconds": "bad",
                    }
                ),
                json.dumps(_performance_phase(run_id, "command", command="report")),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (ops_dir / "telemetry.jsonl").write_text(
        "\n".join(
            [
                json.dumps(_performance_provider(run_id, 0)),
                json.dumps({**_performance_provider(run_id, 1), "model": ""}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (ops_dir / "cost_log.jsonl").write_text(
        "\n".join(
            [
                json.dumps(_performance_cost(run_id, "report", 0)),
                json.dumps(
                    {
                        **_performance_cost(run_id, "report", 1),
                        "actual_cost": "bad",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    json_result = runner.invoke(app, ["--json", "costs"])

    assert json_result.exit_code == 0, json_result.output
    performance = json.loads(json_result.output)["data"]["performance"]
    run = performance["runs"][0]
    assert run["workflow"]["artifact_count"] == 1
    assert run["phases_complete"] is False
    assert run["nested_phase_count"] is None
    assert run["provider_complete"] is False
    assert run["provider_call_count"] is None
    assert run["provider_call_seconds_cumulative"] is None
    assert run["cost_complete"] is False
    assert run["cost_row_count"] is None
    assert run["actual_cost_usd"] is None

    human_result = runner.invoke(app, ["costs"], terminal_width=80)

    assert human_result.exit_code == 0, human_result.output
    human_text = " ".join(human_result.output.split())
    assert "phase evidence incomplete" in human_text
    assert "provider evidence incomplete" in human_text
    assert "cost evidence incomplete" in human_text
    assert "valid rows shown below are a subset" in human_text
    assert "affected rollup incomplete" in human_text


def test_performance_view_formats_unknown_workflow_and_all_coverage_cautions() -> None:
    assert performance_view._seconds(61.25) == "1m 1.2s"
    assert performance_view._seconds(0.05) == "0.050s"
    assert performance_view._seconds(0) == "0.0s"
    assert performance_view._bytes(None) == "-"
    assert performance_view._bytes(5) == "5 B"
    assert performance_view._bytes(2048) == "2.0 KB"
    assert performance_view._bytes(2 * 1024**2) == "2.0 MB"
    assert performance_view._bytes(2 * 1024**3) == "2.0 GB"
    assert performance_view._cost(None) == "-"
    assert performance_view._cost(0.005) == "$0.0050"
    assert performance_view._cost(0.25) == "$0.25"
    assert (
        performance_view._workflow_line(None, phases_complete=True) == "workflow artifacts unknown"
    )

    coverage = _performance_coverage(
        correlated_runs_total=1,
        excluded_observer_runs=1,
        runs_shown=1,
        phase_rows_total=3,
        phase_rows_joined=1,
        provider_rows_total=3,
        provider_rows_joined=1,
        cost_rows_total=3,
        cost_rows_joined=1,
        legacy_unjoinable_phase_rows=1,
        legacy_unjoinable_provider_rows=1,
        legacy_unjoinable_cost_rows=1,
        unanchored_phase_rows=1,
        unanchored_provider_rows=1,
        unanchored_cost_rows=1,
        malformed_phase_rows=1,
        malformed_provider_rows=1,
        malformed_cost_rows=1,
        unreadable_logs=["telemetry.jsonl"],
    )
    evidence: PerformanceEvidence = {
        **_empty_performance(coverage),
        "runs": [
            {
                "run_id": "12345678-run",
                "command": "audit",
                "command_envelope": {
                    "invocation_type": "mcp",
                    "timestamp": "",
                    "outcome": "success",
                    "wall_seconds": 0.05,
                    "process_cpu_seconds": 61.25,
                    "process_peak_rss_bytes": None,
                },
                "workflow": None,
                "phases_complete": False,
                "nested_phase_count": None,
                "provider_complete": False,
                "provider_call_count": None,
                "provider_call_seconds_cumulative": None,
                "cost_complete": False,
                "cost_row_count": None,
                "actual_cost_usd": None,
            }
        ],
    }
    output = Console(record=True, width=80)

    performance_view.render_performance_evidence(evidence, output)
    rendered = " ".join(output.export_text().split())

    assert "workflow evidence incomplete" in rendered
    assert "provider evidence incomplete" in rendered
    assert "cost evidence incomplete" in rendered
    assert "Excluded observer runs" in rendered
    assert "Legacy unjoinable rows" in rendered
    assert "Rows with IDs but no command anchor" in rendered
    assert "malformed or schema-invalid" in rendered
    assert "Unreadable telemetry logs" in rendered
    assert "valid rows shown below are a subset" in rendered

    evidence["runs"][0]["phases_complete"] = True
    complete_output = Console(record=True, width=80)
    performance_view._latest_phases(evidence, complete_output)

    assert "has no nested phase rows yet" in complete_output.export_text()


@pytest.mark.parametrize(
    ("coverage", "message"),
    [
        (
            _performance_coverage(correlated_runs_total=1),
            "No recent non-observer command-phase rows selected.",
        ),
        (
            _performance_coverage(correlated_runs_total=1, excluded_observer_runs=1),
            "Only excluded `costs` observer command anchors are present.",
        ),
        (_performance_coverage(), "No correlated command-phase evidence yet."),
    ],
)
def test_performance_view_empty_states(
    coverage: PerformanceCoverage,
    message: str,
) -> None:
    output = Console(record=True, width=80)

    performance_view.render_performance_evidence(_empty_performance(coverage), output)

    assert message in output.export_text()


def test_costs_json_and_human_output_include_cost_warnings(tmp_path, monkeypatch):
    config = _config(tmp_path, distill_cost_workflow_budgets="report=2")
    _patch_config(monkeypatch, config)
    ops_dir = config.library_dir / ".distill"
    ops_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-06-01T12:00:00",
            "command": "report",
            "actual_cost": 1.0,
            "metadata": {"topic": "ai"},
        },
        {
            "timestamp": "2026-06-02T12:00:00",
            "command": "report",
            "actual_cost": 1.0,
            "metadata": {"topic": "ai"},
        },
        {
            "timestamp": "2026-06-03T12:00:00",
            "command": "report",
            "actual_cost": 12.0,
            "metadata": {"topic": "ai"},
            "by_model": {"grok-imagine-image": {"calls": 24}},
        },
    ]
    (ops_dir / "cost_log.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    json_result = runner.invoke(app, ["--json", "costs"])

    assert json_result.exit_code == 0, json_result.output
    parsed = json.loads(json_result.output)
    warnings = parsed["data"]["cost_warnings"]
    assert {warning["kind"] for warning in warnings} >= {
        "daily-threshold",
        "workflow-budget",
        "xai-media-model",
    }

    human_result = runner.invoke(app, ["costs", "--last", "3"])

    assert human_result.exit_code == 0, human_result.output
    assert "Cost warnings" in human_result.output
    assert "above workflow budget $2.00" in human_result.output
    assert "xAI media-generation model spend recorded" in human_result.output


def test_costs_human_renders_sources_accuracy_and_breakdown(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    ops_dir = config.library_dir / ".distill"
    ops_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp": "2026-06-01T12:00:00",
            "command": "papers",
            "actual_cost": 0.005,
            "estimated_cost": 0.01,
            "elapsed_seconds": 75,
            "total_input_tokens": 1000,
            "total_output_tokens": 250,
            "metadata": {},
        },
        {
            "timestamp": "2026-06-02T12:00:00",
            "command": "learn",
            "actual_cost": 0.2,
            "estimated_cost": 0.1,
            "elapsed_seconds": 5,
            "full_videos": 2,
            "total_input_tokens": 2000,
            "total_output_tokens": 500,
            "metadata": {"topic": "ai", "papers": 1, "pages": 3},
            "by_call_type": {
                "analysis": {"calls": 2, "input_tokens": 1500, "output_tokens": 400},
                "malformed": "skip",
            },
        },
    ]
    (ops_dir / "cost_log.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["costs", "--last", "2"])

    assert result.exit_code == 0, result.output
    assert "papers" in result.output
    assert "2v 1p 3pg" in result.output
    assert "Estimator accuracy" in result.output
    assert "Breakdown: learn" in result.output
    assert "analysis" in result.output


def test_local_cloud_telemetry_helpers_parse_valid_and_invalid_rows(tmp_path, monkeypatch):
    config = _config(tmp_path)
    telemetry = config.library_dir / ".distill" / "telemetry.jsonl"
    telemetry.parent.mkdir(parents=True, exist_ok=True)
    telemetry.write_text(
        "\n".join(
            [
                "",
                "[]",
                "{not-json",
                json.dumps(
                    {
                        "provider_type": "local",
                        "elapsed_seconds": 2.5,
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "tokens_per_second": 60,
                    }
                ),
                json.dumps(
                    {
                        "provider_type": "cloud",
                        "elapsed_seconds": 1.0,
                        "input_tokens": 10,
                        "output_tokens": 5,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    printed: list[str] = []
    monkeypatch.setattr(
        _maintain.console,
        "print",
        lambda *args, **_kwargs: printed.append(" ".join(str(arg) for arg in args)),
    )

    stats = _maintain._compute_local_cloud_stats(config)
    _maintain._costs_local_cloud_section(config)

    assert stats["local_total_seconds"] == 2.5
    assert stats["local_total_tokens"] == 150
    assert stats["avg_tokens_per_second"] == 60.0
    assert any("Cloud calls" in line for line in printed)
    assert any("Local calls" in line for line in printed)
    assert any("Avg tokens/sec" in line for line in printed)


def test_open_non_vault_uses_platform_opener_and_browser_fallback(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    output_dir = config.library_dir.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    opened_by_process: list[list[str]] = []
    opened_by_browser: list[str] = []

    monkeypatch.setattr(_maintain.os, "startfile", None, raising=False)
    monkeypatch.setattr(
        _maintain.os, "uname", lambda: SimpleNamespace(sysname="Linux"), raising=False
    )
    monkeypatch.setattr(
        "distill.process_security.resolve_executable", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(
        "distill.process_security.package_install_context",
        lambda: ("/trusted", {"PATH": "/usr/bin"}),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **_kwargs: opened_by_process.append(list(argv)),
    )
    monkeypatch.setattr(
        _maintain.webbrowser, "open", lambda target: opened_by_browser.append(target)
    )

    _maintain.open_cmd(topic=None, channel=None, what="output", vault=False, path="")

    assert opened_by_process == [["/usr/bin/xdg-open", str(output_dir)]]

    monkeypatch.setattr("distill.process_security.resolve_executable", lambda _name: None)
    _maintain.open_cmd(topic=None, channel=None, what="library", vault=False, path="")

    assert opened_by_browser == [str(config.library_dir)]


def test_status_online_reports_up_to_date_and_failed_checks(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@Okay", "Okay")
    lib.add_channel("ai", "https://www.youtube.com/@Broken", "Broken")

    def discover(url, months=1, include_shorts=False, quiet=True):
        if "Broken" in url:
            raise RuntimeError("network down")
        return []

    monkeypatch.setattr(_maintain, "discover_videos", discover)

    result = runner.invoke(app, ["status", "--online"])

    assert result.exit_code == 0, result.output
    assert "Okay" in result.output
    assert "up to date" in result.output
    assert "all up to date" in result.output


def test_migrate_empty_library_and_existing_target_skip(tmp_path, monkeypatch):
    empty_config = _config(tmp_path / "empty")
    _patch_config(monkeypatch, empty_config)

    empty = runner.invoke(app, ["migrate", "--yes"])

    assert empty.exit_code == 0
    assert "nothing to migrate" in empty.output

    config = _config(tmp_path / "populated")
    _patch_config(monkeypatch, config)
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")
    old = config.video_dir("ai", "TestCh", "abc123xyz")
    old.mkdir(parents=True, exist_ok=True)
    title = "Great Video"
    video_id = "abc123xyz"
    (old / "metadata.json").write_text(
        json.dumps({"video_id": video_id, "title": title}), encoding="utf-8"
    )
    target = config.videos_dir("ai", "TestCh") / slugify_title(title, video_id)
    target.mkdir(parents=True, exist_ok=True)

    skipped = runner.invoke(app, ["migrate", "--yes"])

    assert skipped.exit_code == 0
    assert "Skipping abc123xyz" in skipped.output


def test_migrate_existing_topic_without_renames_and_rename_errors(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestCh", "TestCh")

    no_renames = runner.invoke(app, ["migrate", "--yes"])

    assert no_renames.exit_code == 0
    assert "already use readable names" in no_renames.output

    old = config.video_dir("ai", "TestCh", "abc123xyz")
    old.mkdir(parents=True, exist_ok=True)
    (old / "metadata.json").write_text(
        json.dumps({"video_id": "abc123xyz", "title": "Blocked Rename"}), encoding="utf-8"
    )

    def fail_rename(_self, _target):
        raise OSError("blocked")

    monkeypatch.setattr(Path, "rename", fail_rename)

    failed = runner.invoke(app, ["migrate", "--yes"])

    assert failed.exit_code == 0
    assert "Failed to rename abc123xyz" in failed.output
    assert "1 errors" in failed.output


def test_cleanup_no_metered_blocks_before_gemini_client_construction(tmp_path, monkeypatch):
    config = _config(tmp_path, distill_cost_mode="no-metered")
    _patch_config(monkeypatch, config)
    clients: list[str] = []

    def forbidden_client(*, api_key: str) -> None:
        clients.append(api_key)
        raise AssertionError("Gemini client must not be constructed")

    fake_genai = SimpleNamespace(Client=forbidden_client)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    with pytest.raises(CostPolicyError, match="Route blocked by no-metered cost policy"):
        _maintain.cleanup()

    assert clients == []


def test_cleanup_reports_non_distill_and_deletes_distill_stores(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    clients: list[str] = []
    printed: list[str] = []
    stores = [{"display_name": "unrelated", "name": "stores/other"}]
    cleanup_calls: list[object] = []

    fake_genai = SimpleNamespace(Client=lambda api_key: clients.append(api_key) or "client")
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    import distill.pipeline.report.file_search as file_search

    monkeypatch.setattr(file_search, "list_stores", lambda _client: list(stores))
    monkeypatch.setattr(
        file_search,
        "cleanup_stores",
        lambda client: cleanup_calls.append(client) or 2,
    )
    monkeypatch.setattr(
        _maintain.console,
        "print",
        lambda *args, **_kwargs: printed.append(" ".join(str(arg) for arg in args)),
    )

    _maintain.cleanup()

    assert clients == ["test-gemini"]
    assert any("No orphaned stores found" in line for line in printed)
    assert any("non-distill stores exist" in line for line in printed)
    assert cleanup_calls == []

    stores[:] = [
        {"display_name": "distill-report-one", "name": "stores/distill-1"},
        {"display_name": "other", "name": "stores/other"},
    ]

    _maintain.cleanup()

    assert cleanup_calls == ["client"]
    assert any("Found 1 distill stores" in line for line in printed)
    assert any("Deleted 2 store" in line for line in printed)


def test_corpus_failure_and_dashboard_modes(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    monkeypatch.setattr(_maintain, "_require_model", lambda: None)
    monkeypatch.setattr(_maintain, "synthesize_corpus", lambda *_args, **_kwargs: None)
    summaries: list[str] = []
    monkeypatch.setattr(
        _maintain,
        "display_summary",
        lambda summary, **_kwargs: summaries.append(summary.command),
    )

    with pytest.raises(typer.Exit) as raised:
        _maintain.corpus("ai")

    assert raised.value.exit_code == 1
    assert summaries == ["corpus"]

    calls: list[str] = []
    monkeypatch.setattr(_maintain, "show_banner", lambda *_args, **_kwargs: calls.append("banner"))
    monkeypatch.setattr(_maintain, "show_dashboard", lambda: calls.append("dashboard"))

    _maintain.dashboard(web=False)

    assert calls == ["banner", "dashboard"]


def test_serve_help_documents_loopback_default():
    from typer.testing import CliRunner

    from distill import cli

    result = CliRunner().invoke(cli.app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "127.0.0.1" in result.output
    assert "loopback" in result.output.casefold()
    assert "non-loopback" in result.output.casefold() or "expose" in result.output.casefold()


def test_dashboard_web_open_and_serve_delegate(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _patch_config(monkeypatch, config)
    html_path = tmp_path / "dashboard.html"
    opened: list[str] = []
    served: list[tuple[str, int, bool]] = []

    monkeypatch.setattr(
        _maintain, "dashboard_snapshot", lambda received: {"ok": received is config}
    )
    monkeypatch.setattr(
        _maintain, "render_dashboard_html", lambda version, snapshot: f"{version}:{snapshot['ok']}"
    )
    monkeypatch.setattr(_maintain, "_output_path", lambda _config, _name: html_path)
    monkeypatch.setattr(_maintain.webbrowser, "open", lambda uri: opened.append(uri))

    _maintain.dashboard(web=True, open_browser=True)

    assert html_path.read_text(encoding="utf-8").endswith(":True")
    assert opened == [html_path.resolve().as_uri()]

    import distill.web.server as web_server

    monkeypatch.setattr(
        web_server,
        "run_server",
        lambda received, host, port, open_browser: served.append((host, port, open_browser)),
    )

    _maintain.serve(port=9001, host="127.0.0.2", open_browser=False)

    assert served == [("127.0.0.2", 9001, False)]
