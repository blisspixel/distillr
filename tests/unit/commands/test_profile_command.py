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
from distill.library.profiles import ProfileValidationError, load_research_profile
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

    assert result.exit_code == 5
    envelope = json.loads(result.stdout)
    assert envelope["status"] == "error"
    assert envelope["error"] == "Profile not found: missing.yaml"
    assert "missing.yaml.yaml" not in envelope["error"]
    assert envelope["data"]["reason"] == "not_found"
    assert envelope["data"]["phase"] == "gate.not_found"
    assert envelope["data"]["action"] == "profile"


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


def _library_research_profile(library: Path, name: str, *, cost_mode: str = "no-metered") -> None:
    profiles = library / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (library / "goals").mkdir(parents=True, exist_ok=True)
    (library / "goals" / f"{name}.md").write_text("goal", encoding="utf-8")
    (profiles / f"{name}.yaml").write_text(
        "\n".join(
            [
                "schema_version: research-profile.v1",
                f"name: {name}",
                f"topic: {name}",
                f"goal_file: goals/{name}.md",
                f"cost_mode: {cost_mode}",
                "freshness:",
                "  cadence: daily",
                "  stale_after: P1D",
                "queries:",
                "  - overnight wiki fuel",
                "limits:",
                "  max_new_items: 25",
                f"  max_metered_usd: {'0' if cost_mode == 'no-metered' else '5'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


class _LocalRouter:
    def resolve(self, _workload: str = "") -> tuple[str, str]:
        return ("ollama", "qwen3.8:27b")


def test_profile_refresh_json_preview_packs_due_profiles(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _library_research_profile(config.library_dir, "alpha")
    _library_research_profile(config.library_dir, "bravo")
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)

    result = runner.invoke(
        cli.app,
        [
            "--cost-mode",
            "no-metered",
            "--json",
            "profile",
            "refresh",
            "--max-hours",
            "6",
            "--no-fetch",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["schema_version"] == "profile-refresh.v1"
    assert data["selected_count"] == 2
    assert [slot["name"] for slot in data["selected"]] == ["alpha", "bravo"]
    assert data["local"] is True
    assert "executed" not in data


def test_profile_refresh_yes_executes_packed_profiles(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _library_research_profile(config.library_dir, "alpha")
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)
    ran: list[str] = []

    def _fake_run(preview, **kwargs):
        ran.append(preview.profile)
        return ProfileRunResult(
            schema_version="profile-run.v1",
            profile=preview.profile,
            topic=preview.topic,
            cost_mode=preview.cost_mode,
            generated_at="2026-08-19T06:00:00Z",
            state_path=str(
                config.library_dir / ".distill" / "profiles" / preview.profile / "run_state.json"
            ),
            approved=True,
            executed=True,
            fresh_item_limit=preview.fresh_item_limit,
            ordering=preview.ordering,
        )

    monkeypatch.setattr(_profile, "run_profile_preview", _fake_run)

    result = runner.invoke(
        cli.app,
        [
            "--cost-mode",
            "no-metered",
            "--json",
            "profile",
            "refresh",
            "--max-hours",
            "6",
            "--yes",
            "--no-fetch",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["schema_version"] == "profile-refresh.v1"
    assert ran == ["alpha"]
    assert data["executed"] == [
        {"profile": "alpha", "status": "complete", "succeeded": 0, "failed": 0}
    ]


def test_profile_refresh_console_preview_and_empty_window(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)

    empty = runner.invoke(
        cli.app,
        ["--cost-mode", "no-metered", "profile", "refresh", "--max-hours", "6", "--no-fetch"],
    )
    assert empty.exit_code == 0, empty.output
    assert "Overnight profile refresh" in empty.output
    assert "Nothing due" in empty.output

    _library_research_profile(config.library_dir, "alpha")
    preview = runner.invoke(
        cli.app,
        ["--cost-mode", "no-metered", "profile", "refresh", "--max-hours", "6", "--no-fetch"],
    )
    assert preview.exit_code == 0, preview.output
    assert "alpha" in preview.output
    assert "Preview only" in preview.output
    assert "wall clock is the budget" in preview.output or "distill bench" in preview.output


def test_profile_refresh_cloud_route_prints_metered_notice(tmp_path, monkeypatch):
    class _CloudRouter:
        def resolve(self, _workload: str = "") -> tuple[str, str]:
            return ("xai", "grok-4.6")

    config = _config(tmp_path)
    monkeypatch.setenv("DISTILL_COST_MODE", "paid-ok")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _CloudRouter)
    _library_research_profile(config.library_dir, "alpha")

    result = runner.invoke(
        cli.app,
        ["--cost-mode", "paid-ok", "profile", "refresh", "--max-hours", "6", "--no-fetch"],
    )
    assert result.exit_code == 0, result.output
    assert "Metered cloud API" in result.output


def test_profile_refresh_yes_records_slot_errors_and_stops_on_empty_window(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _library_research_profile(config.library_dir, "alpha")
    _library_research_profile(config.library_dir, "bravo")
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)
    clock = [0.0]
    monkeypatch.setattr(_profile.time, "monotonic", lambda: clock[0])

    def _fake_run(preview, **kwargs):
        clock[0] += 6 * 3600
        raise ProfileValidationError(f"{preview.profile} is invalid")

    monkeypatch.setattr(_profile, "run_profile_preview", _fake_run)

    result = runner.invoke(
        cli.app,
        [
            "--cost-mode",
            "no-metered",
            "--json",
            "profile",
            "refresh",
            "--max-hours",
            "6",
            "--yes",
            "--no-fetch",
        ],
    )
    assert result.exit_code == 1, result.output
    data = json.loads(result.stdout)["data"]
    assert data["executed"] == [
        {"profile": "alpha", "status": "error", "error": "alpha is invalid"}
    ]


def test_profile_refresh_yes_with_nothing_due_emits_empty_execution(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)

    result = runner.invoke(
        cli.app,
        [
            "--cost-mode",
            "no-metered",
            "--json",
            "profile",
            "refresh",
            "--yes",
            "--no-fetch",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["selected_count"] == 0
    assert data["executed"] == []


def _write_bench(library: Path) -> None:
    bench = library / ".distill" / "bench"
    bench.mkdir(parents=True, exist_ok=True)
    (bench / "results.jsonl").write_text(
        '{"outcome":"success","model":"qwen3.8:27b","provider":"ollama",'
        '"prefill_tokens_per_second":200.0,"decode_tokens_per_second":50.0,'
        '"load_plus_queue_seconds":1.0}\n',
        encoding="utf-8",
    )


def test_profile_refresh_console_yes_renders_and_stops_when_window_elapses(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _library_research_profile(config.library_dir, "alpha")
    _library_research_profile(config.library_dir, "bravo")
    _library_research_profile(config.library_dir, "cloud", cost_mode="paid-ok")
    _write_bench(config.library_dir)
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)
    clock = [0.0]
    monkeypatch.setattr(_profile.time, "monotonic", lambda: clock[0])

    def _fake_run(preview, **kwargs):
        clock[0] += 6 * 3600
        return ProfileRunResult(
            schema_version="profile-run.v1",
            profile=preview.profile,
            topic=preview.topic,
            cost_mode=preview.cost_mode,
            generated_at="2026-08-19T06:00:00Z",
            state_path=str(
                config.library_dir / ".distill" / "profiles" / preview.profile / "run_state.json"
            ),
            approved=True,
            executed=True,
            fresh_item_limit=preview.fresh_item_limit,
            ordering=preview.ordering,
        )

    monkeypatch.setattr(_profile, "run_profile_preview", _fake_run)

    result = runner.invoke(
        cli.app,
        [
            "--cost-mode",
            "no-metered",
            "profile",
            "refresh",
            "--max-hours",
            "6",
            "--yes",
            "--no-fetch",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Overnight profile refresh" in result.output
    assert "Deferred" in result.output or "Tonight" in result.output
    assert "Window almost empty" in result.output
    assert "(1/" in result.output


def test_profile_refresh_console_yes_prints_slot_errors(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _library_research_profile(config.library_dir, "alpha")
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)
    monkeypatch.setattr(
        _profile,
        "run_profile_preview",
        lambda preview, **kwargs: (_ for _ in ()).throw(ProfileValidationError("alpha is invalid")),
    )

    result = runner.invoke(
        cli.app,
        [
            "--cost-mode",
            "no-metered",
            "profile",
            "refresh",
            "--max-hours",
            "6",
            "--yes",
            "--no-fetch",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "alpha is invalid" in result.output


def test_profile_refresh_console_yes_with_nothing_due(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)
    result = runner.invoke(
        cli.app,
        [
            "--cost-mode",
            "no-metered",
            "profile",
            "refresh",
            "--yes",
            "--no-fetch",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Nothing due" in result.output


def test_profile_refresh_yes_treats_failed_health_as_nonzero(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _library_research_profile(config.library_dir, "alpha")
    monkeypatch.setenv("DISTILL_COST_MODE", "no-metered")
    monkeypatch.setattr(_profile, "get_config", lambda: config)
    monkeypatch.setattr(_profile, "RouterConfig", _LocalRouter)
    monkeypatch.setattr(
        _profile,
        "run_profile_preview",
        lambda preview, **kwargs: _run_result(approved=True, failed=True),
    )

    result = runner.invoke(
        cli.app,
        [
            "--cost-mode",
            "no-metered",
            "--json",
            "profile",
            "refresh",
            "--yes",
            "--no-fetch",
        ],
    )
    assert result.exit_code == 1, result.output
    data = json.loads(result.stdout)["data"]
    assert data["executed"][0]["status"] == "failed"


def test_apply_profile_cost_policy_auto_inherits_configured_mode(tmp_path):
    profile_path = _write_profile(tmp_path)
    loaded = load_research_profile(profile_path)
    auto = loaded.model_copy(update={"cost_mode": "auto"})
    applied = _profile._apply_profile_cost_policy(auto, "paid-ok")
    assert applied.cost_mode == "paid-ok"


class TestProfileRegister:
    def test_register_attaches_profile_subapp(self):
        app = typer.Typer()
        _profile.register(app)
        assert any(group.name == "profile" for group in app.registered_groups)
