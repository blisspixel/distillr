from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from distill import cli
from distill.commands import profile as _profile
from distill.config import DistillConfig
from distill.library.okf import OkfExportResult, OkfIssue, OkfValidationResult
from distill.library.profiles import ProfileValidationError
from distill.pipeline.profile_preview import (
    ProfilePreviewCandidate,
    ProfilePreviewResult,
    ProfilePreviewWarning,
    command_shell_label,
    command_text,
)
from distill.pipeline.profile_run import (
    CommandExecution,
    ProfileRunCommand,
    ProfileRunEvent,
    ProfileRunResult,
)

runner = CliRunner()


def test_profile_preview_json_for_yaml_path(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                "name: agent-loops",
                "topic: agent-loops",
                "goal_file: goals/agent-loops.md",
                "cost_mode: no-metered",
                "sources:",
                "  youtube_channels:",
                "    - handle: '@Example'",
                "      label: Example",
                "queries:",
                "  - long running agent loops",
                "limits:",
                "  max_new_items: 5",
                "  max_metered_usd: 0",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli.app,
        ["--json", "profile", "preview", str(profile_path), "--no-fetch"],
    )

    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "ok"
    data = envelope["data"]
    assert data["schema_version"] == "profile-preview.v1"
    assert data["profile"] == "agent-loops"
    assert [candidate["kind"] for candidate in data["candidates"]] == [
        "youtube_channel",
        "query",
    ]
    assert data["candidates"][0]["command"] == [
        "distill",
        "--cost-mode",
        "no-metered",
        "channel",
        "https://www.youtube.com/@Example",
        "--topic",
        "agent-loops",
        "--limit",
        "5",
    ]


def test_profile_preview_json_missing_yaml_keeps_single_suffix(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    monkeypatch.setattr(_profile, "get_config", lambda: config)

    result = runner.invoke(
        cli.app,
        ["--json", "profile", "preview", "missing.yaml", "--no-fetch"],
    )

    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "error"
    assert envelope["error"].endswith(r"library\profiles\missing.yaml") or envelope[
        "error"
    ].endswith("library/profiles/missing.yaml")
    assert "missing.yaml.yaml" not in envelope["error"]


def test_profile_run_json_without_yes_returns_approval_plan(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                "name: agent-loops",
                "topic: agent-loops",
                "goal_file: goals/agent-loops.md",
                "cost_mode: no-metered",
                "queries:",
                "  - long running agent loops",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        cli.app,
        ["--json", "profile", "run", str(profile_path), "--no-fetch"],
    )

    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "ok"
    data = envelope["data"]
    assert data["schema_version"] == "profile-run.v1"
    assert data["approved"] is False
    assert data["health"]["status"] == "approval_required"
    assert data["pending_count"] == 1
    assert data["commands"][0]["command"] == [
        "distill",
        "--cost-mode",
        "no-metered",
        "latest",
        "long running agent loops",
        "--topic",
        "agent-loops",
        "--preview",
    ]
    assert data["next_actions"][0]["command"] == [
        "distill",
        "--cost-mode",
        "no-metered",
        "profile",
        "run",
        str(profile_path),
        "--yes",
    ]
    assert data["next_actions"][0]["verifier"]["command"] == [
        "distill",
        "--cost-mode",
        "no-metered",
        "--json",
        "profile",
        "run",
        str(profile_path),
    ]
    assert not (config.library_dir / ".distill" / "profiles").exists()


def test_profile_run_with_okf_export_writes_bundle(tmp_path, monkeypatch):
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                "name: agent-loops",
                "topic: agent-loops",
                "goal_file: goals/agent-loops.md",
                "outputs:",
                "  okf_export: true",
                "queries:",
                "  - long running agent loops",
            ]
        ),
        encoding="utf-8",
    )
    topic_dir = config.topic_dir("agent-loops")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "agent-loops_Topic_Synthesis.md").write_text("# Topic\n", encoding="utf-8")

    def _fake_run(preview, **kwargs):
        from distill.pipeline.profile_run import ProfileRunResult

        run_result = ProfileRunResult(
            schema_version="profile-run.v1",
            profile=preview.profile,
            topic=preview.topic,
            cost_mode=preview.cost_mode,
            generated_at="2026-06-18T12:00:00Z",
            state_path=str(
                config.library_dir / ".distill" / "profiles" / "agent-loops" / "run_state.json"
            ),
            approved=kwargs.get("approved", False),
            executed=kwargs.get("approved", False),
            fresh_item_limit=preview.fresh_item_limit,
            ordering=preview.ordering,
        )
        finalizer = kwargs.get("result_finalizer")
        return finalizer(run_result) if finalizer is not None else run_result

    monkeypatch.setattr(_profile, "run_profile_preview", _fake_run)

    result = runner.invoke(
        cli.app,
        ["--json", "profile", "run", str(profile_path), "--yes", "--no-fetch"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert data["okf_bundle_valid"] is True
    assert "okf-agent-loops" in data["okf_bundle_dir"]
    assert (tmp_path / "output" / "okf-agent-loops" / "index.md").exists()


def test_global_no_metered_cannot_be_weakened_by_paid_profile(tmp_path, monkeypatch):
    old_cost_mode = os.environ.get("DISTILL_COST_MODE")
    monkeypatch.delenv("DISTILL_COST_MODE", raising=False)
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                "name: agent-loops",
                "topic: agent-loops",
                "goal_file: goals/agent-loops.md",
                "cost_mode: paid-ok",
                "queries:",
                "  - long running agent loops",
            ]
        ),
        encoding="utf-8",
    )

    try:
        result = runner.invoke(
            cli.app,
            [
                "--cost-mode",
                "no-metered",
                "--json",
                "profile",
                "preview",
                str(profile_path),
                "--no-fetch",
            ],
        )

        assert result.exit_code == 0
        assert os.environ["DISTILL_COST_MODE"] == "no-metered"
        data = json.loads(result.stdout)["data"]
        assert data["cost_mode"] == "no-metered"
        assert data["max_metered_usd"] == 0.0
        assert data["candidates"]
        for candidate in data["candidates"]:
            assert candidate["command"][1:3] == ["--cost-mode", "no-metered"]
            assert "paid-ok" not in candidate["command"]
    finally:
        if old_cost_mode is None:
            os.environ.pop("DISTILL_COST_MODE", None)
        else:
            os.environ["DISTILL_COST_MODE"] = old_cost_mode


def _config(tmp_path) -> DistillConfig:
    return DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )


def _write_profile(tmp_path, *, okf_export: bool = False) -> Path:
    lines = [
        "schema_version: research-profile.v1",
        "name: agent-loops",
        "topic: agent-loops",
        "goal_file: goals/agent-loops.md",
        "cost_mode: no-metered",
        "queries:",
        "  - long running agent loops",
    ]
    if okf_export:
        lines[5:5] = ["outputs:", "  okf_export: true"]
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("\n".join(lines), encoding="utf-8")
    return profile_path


def _preview_result(*, okf_export_required: bool = False) -> ProfilePreviewResult:
    return ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="no-metered",
        ordering="published_desc",
        fresh_item_limit=5,
        okf_export_required=okf_export_required,
        candidates=[
            ProfilePreviewCandidate(
                kind="query",
                title="Agent loops query",
                url="",
                source="queries",
                source_label="queries",
                command=["distill", "latest", "long running agent loops", "--topic", "agent-loops"],
                published_at="2026-06-01",
            )
        ],
        warnings=[ProfilePreviewWarning(source="feed", message="feed unreachable")],
    )


def _run_result(
    *,
    approved: bool = False,
    failed: bool = False,
    okf: bool = False,
) -> ProfileRunResult:
    command = ProfileRunCommand(
        key="query-1",
        kind="query",
        title="Agent loops query",
        source_label="queries",
        command=["distill", "latest", "long running agent loops", "--topic", "agent-loops"],
        resume_policy="retry",
        status="selected",
    )
    events: list[ProfileRunEvent] = []
    if failed:
        events.append(
            ProfileRunEvent(
                key="query-1",
                kind="query",
                title="Agent loops query",
                command=command.command,
                resume_policy="retry",
                status="failed",
                attempted_at="2026-06-18T12:00:00Z",
                execution=CommandExecution(
                    exit_code=1,
                    elapsed_seconds=1.0,
                    stderr_tail="command failed",
                ),
            )
        )
    return ProfileRunResult(
        schema_version="profile-run.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="no-metered",
        generated_at="2026-06-18T12:00:00Z",
        state_path="/tmp/run_state.json",
        approved=approved,
        executed=approved,
        fresh_item_limit=5,
        ordering="published_desc",
        commands=[command],
        events=events,
        warnings=[{"source": "feed", "message": "skipped stale item"}] if okf else [],
        okf_bundle_dir="/tmp/okf-agent-loops" if okf else "",
        okf_bundle_valid=okf,
    )


def _apply_fake_finalizer(result: ProfileRunResult, kwargs: dict[str, object]) -> ProfileRunResult:
    finalizer = kwargs.get("result_finalizer")
    return finalizer(result) if callable(finalizer) else result


class TestProfilePreviewHuman:
    def test_renders_preview_table(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        profile_path = _write_profile(tmp_path)
        monkeypatch.setattr(_profile, "get_config", lambda: config)
        monkeypatch.setattr(
            _profile,
            "_load_profile_preview",
            lambda *args, **kwargs: (config, profile_path, _preview_result()),
        )

        result = runner.invoke(
            cli.app,
            ["profile", "preview", str(profile_path)],
            terminal_width=200,
        )

        assert result.exit_code == 0
        assert "Profile Preview" in result.output
        assert (
            command_text(
                ["distill", "latest", "long running agent loops", "--topic", "agent-loops"]
            )
            in result.output
        )
        assert f"Commands ({command_shell_label()})" in result.output
        assert "Agent loops query" in result.output
        assert "feed unreachable" in result.output

    def test_renders_untrusted_titles_commands_and_warnings_as_literal_text(
        self, tmp_path, monkeypatch
    ):
        config = _config(tmp_path)
        profile_path = _write_profile(tmp_path)
        preview = ProfilePreviewResult(
            schema_version="profile-preview.v1",
            profile="[bold]profile[/bold]",
            topic="agent-loops",
            cost_mode="no-metered",
            ordering="published_desc",
            fresh_item_limit=1,
            candidates=[
                ProfilePreviewCandidate(
                    kind="query",
                    title="[red]literal title[/red]",
                    url="",
                    source="queries",
                    source_label="[blue]literal source[/blue]",
                    command=[
                        "distill",
                        "latest",
                        "[brackets] & $budget; `tick",
                        "--topic",
                        "agent-loops",
                    ],
                )
            ],
            warnings=[
                ProfilePreviewWarning(
                    source="[yellow]literal warning source[/yellow]",
                    message="[green]literal warning[/green]",
                )
            ],
        )
        monkeypatch.setattr(_profile, "get_config", lambda: config)
        monkeypatch.setattr(
            _profile,
            "_load_profile_preview",
            lambda *args, **kwargs: (config, profile_path, preview),
        )

        result = runner.invoke(
            cli.app,
            ["profile", "preview", str(profile_path)],
            terminal_width=200,
        )

        assert result.exit_code == 0
        assert "[bold]profile[/bold]" in result.output
        assert "[red]literal title[/red]" in result.output
        assert "[blue]" in result.output
        assert "[/blue]" in result.output
        assert "literal" in result.output
        assert "source" in result.output
        assert "[brackets]" in result.output
        assert "$budget;" in result.output
        assert "`tick" in result.output
        assert "[yellow]literal warning source[/yellow]" in result.output
        assert "[green]literal warning[/green]" in result.output

    def test_validation_error_human(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(_profile, "get_config", lambda: config)

        def boom(*args, **kwargs):
            raise ProfileValidationError("invalid profile schema")

        monkeypatch.setattr(_profile, "_load_profile_preview", boom)

        result = runner.invoke(cli.app, ["profile", "preview", "bad.yaml"])

        assert result.exit_code == 1
        assert "invalid profile schema" in result.output

    def test_value_error_json(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(_profile, "get_config", lambda: config)

        def boom(*args, **kwargs):
            raise ValueError("profile path unsafe")

        monkeypatch.setattr(_profile, "_load_profile_preview", boom)

        result = runner.invoke(cli.app, ["--json", "profile", "preview", "bad.yaml"])

        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["status"] == "error"
        assert envelope["error"] == "profile path unsafe"

    def test_run_value_error_json(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(_profile, "get_config", lambda: config)

        def boom(*args, **kwargs):
            raise ValueError("unsafe profile path")

        monkeypatch.setattr(_profile, "_load_profile_preview", boom)

        result = runner.invoke(cli.app, ["--json", "profile", "run", "bad.yaml"])

        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"] == "unsafe profile path"

    def test_run_validation_error_human(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(_profile, "get_config", lambda: config)

        def boom(*args, **kwargs):
            raise ProfileValidationError("profile run invalid")

        monkeypatch.setattr(_profile, "_load_profile_preview", boom)

        result = runner.invoke(cli.app, ["profile", "run", "bad.yaml"])

        assert result.exit_code == 1
        assert "profile run invalid" in result.output


class TestProfileRunHuman:
    def test_renders_run_plan_with_preview_hint(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        profile_path = _write_profile(tmp_path)
        monkeypatch.setattr(_profile, "get_config", lambda: config)
        monkeypatch.setattr(
            _profile,
            "_load_profile_preview",
            lambda *args, **kwargs: (config, profile_path, _preview_result()),
        )
        monkeypatch.setattr(
            _profile, "run_profile_preview", lambda preview, **kwargs: _run_result()
        )

        result = runner.invoke(cli.app, ["profile", "run", str(profile_path)])

        assert result.exit_code == 0
        assert "Profile Run" in result.output
        assert f"Commands ({command_shell_label()})" in result.output
        assert (
            command_text(
                ["distill", "latest", "long running agent loops", "--topic", "agent-loops"]
            )
            in result.output
        )
        assert "Preview only" in result.output
        assert "Re-run with --yes" in result.output

    def test_renders_failed_run_and_okf_bundle(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        profile_path = _write_profile(tmp_path)
        monkeypatch.setattr(_profile, "get_config", lambda: config)
        monkeypatch.setattr(
            _profile,
            "_load_profile_preview",
            lambda *args, **kwargs: (config, profile_path, _preview_result()),
        )
        monkeypatch.setattr(
            _profile,
            "run_profile_preview",
            lambda preview, **kwargs: _run_result(approved=True, failed=True, okf=True),
        )

        result = runner.invoke(cli.app, ["profile", "run", str(profile_path), "--yes"])

        assert result.exit_code == 1
        assert "OKF bundle" in result.output
        assert "profile commands failed" in result.output
        assert "skipped stale item" in result.output

    @pytest.mark.parametrize("terminal_status", ["budget_unverified", "budget_exceeded"])
    def test_approved_unhealthy_json_run_emits_result_and_exits_nonzero(
        self, tmp_path, monkeypatch, terminal_status
    ):
        config = _config(tmp_path)
        profile_path = _write_profile(tmp_path)
        base = _run_result(approved=True)
        unhealthy = (
            replace(base, max_metered_usd=1.0, metered_spend_verified=False)
            if terminal_status == "budget_unverified"
            else replace(base, max_metered_usd=1.0, metered_spend_usd=2.0)
        )
        monkeypatch.setattr(_profile, "get_config", lambda: config)
        monkeypatch.setattr(
            _profile,
            "_load_profile_preview",
            lambda *args, **kwargs: (config, profile_path, _preview_result()),
        )
        monkeypatch.setattr(_profile, "run_profile_preview", lambda preview, **kwargs: unhealthy)

        result = runner.invoke(
            cli.app,
            ["--json", "profile", "run", str(profile_path), "--yes"],
        )

        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["data"]["health"]["status"] == terminal_status

    def test_timeout_above_executor_limit_is_rejected_by_cli(self) -> None:
        result = runner.invoke(
            cli.app,
            ["profile", "run", "unused", "--timeout", "86401"],
        )

        assert result.exit_code == 2
        assert "86400" in result.output


class TestProfileOkfExport:
    def test_okf_export_failure_human(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        profile_path = _write_profile(tmp_path, okf_export=True)
        monkeypatch.setattr(_profile, "get_config", lambda: config)
        monkeypatch.setattr(
            _profile,
            "_load_profile_preview",
            lambda *args, **kwargs: (
                config,
                profile_path,
                _preview_result(okf_export_required=True),
            ),
        )
        monkeypatch.setattr(
            _profile,
            "run_profile_preview",
            lambda preview, **kwargs: _apply_fake_finalizer(_run_result(approved=True), kwargs),
        )

        def boom(*args, **kwargs):
            raise OSError("output filesystem unavailable")

        monkeypatch.setattr(_profile, "export_okf_bundle", boom)

        result = runner.invoke(
            cli.app, ["profile", "run", str(profile_path), "--yes", "--no-fetch"]
        )

        assert result.exit_code == 1
        assert "OKF export skipped" in result.output

    def test_okf_export_failure_json(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        profile_path = _write_profile(tmp_path, okf_export=True)
        monkeypatch.setattr(_profile, "get_config", lambda: config)
        monkeypatch.setattr(
            _profile,
            "_load_profile_preview",
            lambda *args, **kwargs: (
                config,
                profile_path,
                _preview_result(okf_export_required=True),
            ),
        )
        monkeypatch.setattr(
            _profile,
            "run_profile_preview",
            lambda preview, **kwargs: _apply_fake_finalizer(_run_result(approved=True), kwargs),
        )
        monkeypatch.setattr(
            _profile,
            "export_okf_bundle",
            lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("topic missing")),
        )

        result = runner.invoke(
            cli.app,
            ["--json", "profile", "run", str(profile_path), "--yes", "--no-fetch"],
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)["data"]
        assert data["okf_bundle_valid"] is False
        assert any(w["source"] == "okf_export" for w in data["warnings"])

    def test_invalid_okf_validation_emits_result_and_exits_nonzero(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        profile_path = _write_profile(tmp_path, okf_export=True)
        monkeypatch.setattr(_profile, "get_config", lambda: config)
        monkeypatch.setattr(
            _profile,
            "_load_profile_preview",
            lambda *args, **kwargs: (
                config,
                profile_path,
                _preview_result(okf_export_required=True),
            ),
        )
        monkeypatch.setattr(
            _profile,
            "run_profile_preview",
            lambda preview, **kwargs: _apply_fake_finalizer(_run_result(approved=True), kwargs),
        )
        invalid = OkfExportResult(
            output_dir=tmp_path / "output" / "okf-agent-loops",
            source_root=config.topic_dir("agent-loops"),
            topic="agent-loops",
            files_written=3,
            validation=OkfValidationResult(
                root=tmp_path / "output" / "okf-agent-loops",
                files_checked=1,
                errors=(OkfIssue("error", "index.md", "invalid bundle"),),
                warnings=(),
            ),
        )
        monkeypatch.setattr(_profile, "export_okf_bundle", lambda *args, **kwargs: invalid)

        result = runner.invoke(
            cli.app,
            ["--json", "profile", "run", str(profile_path), "--yes", "--no-fetch"],
        )

        assert result.exit_code == 1
        data = json.loads(result.stdout)["data"]
        assert data["okf_bundle_valid"] is False
        assert "validation failed" in data["warnings"][-1]["message"]


class TestProfileRegister:
    def test_register_attaches_profile_subapp(self):
        app = typer.Typer()
        _profile.register(app)
        assert any(group.name == "profile" for group in app.registered_groups)
