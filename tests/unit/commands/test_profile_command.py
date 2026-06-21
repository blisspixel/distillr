from __future__ import annotations

import json
import os

from typer.testing import CliRunner

from distill import cli
from distill.commands import profile as _profile
from distill.config import DistillConfig


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

    result = CliRunner().invoke(
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

    result = CliRunner().invoke(
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

    result = CliRunner().invoke(
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

        return ProfileRunResult(
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

    monkeypatch.setattr(_profile, "run_profile_preview", _fake_run)

    result = CliRunner().invoke(
        cli.app,
        ["--json", "profile", "run", str(profile_path), "--yes", "--no-fetch"],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert data["okf_bundle_valid"] is True
    assert "okf-agent-loops" in data["okf_bundle_dir"]
    assert (tmp_path / "output" / "okf-agent-loops" / "index.md").exists()


def test_global_cost_mode_option_sets_process_policy(tmp_path, monkeypatch):
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
                "cost_mode: auto",
                "queries:",
                "  - long running agent loops",
            ]
        ),
        encoding="utf-8",
    )

    try:
        result = CliRunner().invoke(
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
    finally:
        if old_cost_mode is None:
            os.environ.pop("DISTILL_COST_MODE", None)
        else:
            os.environ["DISTILL_COST_MODE"] = old_cost_mode
