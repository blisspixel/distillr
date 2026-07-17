"""CLI tests for the bundled Agent Skill lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from distill.agent_skills.bundle import SkillBundleError
from distill.agent_skills.lifecycle import SkillInstallError
from distill.cli import app
from distill.commands import skill as skill_module

runner = CliRunner()


def _json(result) -> dict[str, object]:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_skill_doctor_json_reports_bundle_client_and_billing(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--json",
            "skill",
            "doctor",
            "--client",
            "portable",
            "--project-root",
            str(tmp_path),
        ],
    )
    data = _json(result)["data"]
    assert data["bundle"]["name"] == "distill-corpus"
    assert data["clients"][0]["direct_install"]["state"] == "absent"
    assert "do not prove" in data["billing"]


def test_skill_install_preview_apply_doctor_and_uninstall(tmp_path: Path) -> None:
    base = [
        "--json",
        "skill",
        "install",
        "--client",
        "portable",
        "--project-root",
        str(tmp_path),
    ]
    preview = _json(runner.invoke(app, base))["data"]
    assert preview["approved"] is False
    assert preview["plan"]["action"] == "install"
    assert str(tmp_path) in preview["next"]
    target = tmp_path / ".agents" / "skills" / "distill-corpus"
    assert not target.exists()

    applied = _json(runner.invoke(app, [*base, "--yes"]))["data"]
    assert applied["changed"] is True
    assert applied["install"]["state"] == "current"
    assert target.is_dir()

    current = _json(runner.invoke(app, base))["data"]
    assert current["plan"]["action"] == "none"

    uninstall = [
        "--json",
        "skill",
        "uninstall",
        "--client",
        "portable",
        "--project-root",
        str(tmp_path),
    ]
    removal_preview = _json(runner.invoke(app, uninstall))["data"]
    assert removal_preview["plan"]["action"] == "remove"
    removed = _json(runner.invoke(app, [*uninstall, "--yes"]))["data"]
    assert removed["install"]["state"] == "absent"


def test_skill_install_refuses_conflict_and_invalid_options(tmp_path: Path) -> None:
    target = tmp_path / ".agents" / "skills" / "distill-corpus"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("custom", encoding="utf-8")
    conflict = runner.invoke(
        app,
        [
            "--json",
            "skill",
            "install",
            "--project-root",
            str(tmp_path),
        ],
    )
    assert conflict.exit_code == 1
    assert json.loads(conflict.stdout)["data"]["reason"] == "skill_install_conflict"

    invalid = runner.invoke(app, ["--json", "skill", "doctor", "--client", "unknown"])
    assert invalid.exit_code == 2
    assert json.loads(invalid.stdout)["data"]["reason"] == "skill_target_invalid"


def test_skill_export_json_and_existing_path_refusal(tmp_path: Path) -> None:
    output = tmp_path / "distill-corpus.skill"
    args = ["--json", "skill", "export", "--output", str(output)]
    data = _json(runner.invoke(app, args))["data"]
    assert Path(data["path"]) == output
    assert output.with_name("distill-corpus.skill.sha256").is_file()

    conflict = runner.invoke(app, args)
    assert conflict.exit_code == 1
    assert json.loads(conflict.stdout)["data"]["reason"] == "skill_export_failed"


def test_skill_bundle_failure_is_a_configuration_error(monkeypatch) -> None:
    def fail():
        raise SkillBundleError("broken bundle")

    monkeypatch.setattr("distill.commands.skill.load_bundled_skill", fail)
    result = runner.invoke(app, ["--json", "skill", "doctor", "--client", "portable"])
    assert result.exit_code == 3
    assert json.loads(result.stdout)["data"]["reason"] == "skill_bundle_invalid"


def test_skill_human_lifecycle_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("distill.agent_skills.lifecycle.shutil.which", lambda _name: None)
    doctor = runner.invoke(
        app,
        ["skill", "doctor", "--project-root", str(tmp_path)],
    )
    assert doctor.exit_code == 0, doctor.output
    assert "Agent Skill readiness" in doctor.output
    assert "missing" in doctor.output
    assert "n/a" in doctor.output
    assert "does not prove included-plan billing" in doctor.output

    install = ["skill", "install", "--project-root", str(tmp_path)]
    preview = runner.invoke(app, install)
    assert preview.exit_code == 0
    assert "No files changed" in " ".join(preview.output.split())
    applied = runner.invoke(app, [*install, "--yes"])
    assert applied.exit_code == 0
    assert "is current" in applied.output
    current = runner.invoke(app, install)
    assert "already current" in current.output

    uninstall = ["skill", "uninstall", "--project-root", str(tmp_path)]
    removal_preview = runner.invoke(app, uninstall)
    assert "Plan: remove" in removal_preview.output
    removed = runner.invoke(app, [*uninstall, "--yes"])
    assert removed.exit_code == 0
    assert "Removed the managed" in removed.output
    absent = runner.invoke(app, uninstall)
    assert "No direct" in absent.output
    absent_yes = runner.invoke(app, [*uninstall, "--yes"])
    assert "No direct" in absent_yes.output

    output = tmp_path / "distill-corpus.skill"
    exported = runner.invoke(app, ["skill", "export", "--output", str(output)])
    assert exported.exit_code == 0
    assert "SHA-256" in exported.output
    assert "Checksum" in exported.output


def test_skill_human_error_and_invalid_scope(tmp_path: Path) -> None:
    invalid = runner.invoke(app, ["skill", "doctor", "--scope", "system"])
    assert invalid.exit_code == 2
    assert "Unknown scope" in invalid.output

    target = tmp_path / ".agents" / "skills" / "distill-corpus"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("custom", encoding="utf-8")
    conflict = runner.invoke(
        app,
        ["skill", "uninstall", "--project-root", str(tmp_path)],
    )
    assert conflict.exit_code == 1
    assert "unmanaged destination differs" in conflict.output

    invalid_target = runner.invoke(app, ["--json", "skill", "install", "--client", "unknown"])
    assert invalid_target.exit_code == 2
    assert json.loads(invalid_target.stdout)["data"]["reason"] == "skill_target_invalid"

    assert skill_module._approval_command("install", "portable", "project", None).endswith("--yes")

    normalized = runner.invoke(
        app,
        [
            "--json",
            "skill",
            "install",
            "--client",
            " PORTABLE ",
            "--project-root",
            str(tmp_path / "normalized"),
        ],
    )
    assert _json(normalized)["data"]["plan"]["client"] == "portable"


@pytest.mark.parametrize(
    ("command", "patch_target", "reason"),
    [
        (
            ["skill", "install", "--yes"],
            "distill.commands.skill.apply_install",
            "skill_install_failed",
        ),
        (
            ["skill", "uninstall", "--yes"],
            "distill.commands.skill.remove_install",
            "skill_uninstall_failed",
        ),
    ],
)
def test_skill_apply_errors_have_stable_json_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    patch_target: str,
    reason: str,
) -> None:
    project_args = ["--project-root", str(tmp_path)]
    if "uninstall" in command:
        installed = runner.invoke(
            app,
            ["--json", "skill", "install", *project_args, "--yes"],
        )
        assert installed.exit_code == 0

    def fail(*_args, **_kwargs):
        raise SkillInstallError("simulated lifecycle failure")

    monkeypatch.setattr(patch_target, fail)
    result = runner.invoke(app, ["--json", *command, *project_args])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["data"]["reason"] == reason
