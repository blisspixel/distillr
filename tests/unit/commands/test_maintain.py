"""Focused tests for maintain command edge branches."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from distill.cli import app
from distill.commands import maintain as _maintain
from distill.config import DistillConfig
from distill.library import Library
from distill.library.paths import slugify_title

runner = CliRunner()


def _config(tmp_path) -> DistillConfig:
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _patch_config(monkeypatch: pytest.MonkeyPatch, config: DistillConfig) -> None:
    monkeypatch.setattr(_maintain, "get_config", lambda: config)


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


def test_costs_json_and_human_output_include_cost_warnings(tmp_path, monkeypatch):
    config = _config(tmp_path)
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
    assert {warning["kind"] for warning in warnings} >= {"xai-media-model", "daily-threshold"}

    human_result = runner.invoke(app, ["costs", "--last", "3"])

    assert human_result.exit_code == 0, human_result.output
    assert "Cost warnings" in human_result.output
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
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(subprocess, "run", lambda argv: opened_by_process.append(list(argv)))
    monkeypatch.setattr(
        _maintain.webbrowser, "open", lambda target: opened_by_browser.append(target)
    )

    _maintain.open_cmd(topic=None, channel=None, what="output", vault=False, path="")

    assert opened_by_process == [["/usr/bin/xdg-open", str(output_dir)]]

    monkeypatch.setattr(shutil, "which", lambda _name: None)
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
