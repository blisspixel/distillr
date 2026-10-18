import json

from typer.testing import CliRunner

from distill import cli
from distill.commands import theme as command
from distill.ingestors.net import NetworkError
from distill.web import theme, theme_install

runner = CliRunner()


def _custom():
    return (
        (theme.BUILTIN_THEMES / "house-dark.toml")
        .read_text(encoding="utf-8")
        .replace('slug = "house-dark"', 'slug = "custom"')
    )


def test_theme_local_lifecycle_json_and_human(tmp_path):
    source = tmp_path / "custom.toml"
    source.write_text(_custom(), encoding="utf-8")
    listed = runner.invoke(cli.app, ["--json", "theme", "list"])
    assert len(json.loads(listed.stdout)["data"]["themes"]) == 12
    installed = runner.invoke(cli.app, ["--json", "theme", "install", str(source)])
    assert installed.exit_code == 0, installed.output
    assert json.loads(installed.stdout)["data"]["installed"] == ["custom"]
    assert "custom" in runner.invoke(cli.app, ["theme", "list"]).stdout
    assert runner.invoke(cli.app, ["theme", "update"]).exit_code == 0
    removed = runner.invoke(cli.app, ["--json", "theme", "remove", "custom"])
    assert json.loads(removed.stdout)["data"]["removed"] == "custom"
    refused = runner.invoke(cli.app, ["--json", "theme", "remove", "house-dark"])
    assert refused.exit_code == 1
    assert json.loads(refused.stdout)["status"] == "error"
    installed = runner.invoke(cli.app, ["theme", "install", str(source)])
    assert "Installed: custom" in installed.stdout
    removed = runner.invoke(cli.app, ["theme", "remove", "custom"])
    assert "Removed user theme: custom" in removed.stdout


def test_theme_fetch_failure_is_one_refusal_without_traceback(monkeypatch):
    def fail(*_a, **_k):
        raise NetworkError("DNS unavailable", url="https://github.com/example/themes")

    monkeypatch.setattr(command, "install_theme", fail)
    result = runner.invoke(
        cli.app, ["--json", "theme", "install", "https://github.com/example/themes"]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "error"
    assert "DNS unavailable" in result.stdout
    assert "Traceback" not in result.output
    monkeypatch.setattr(command, "update_themes", fail)
    result = runner.invoke(cli.app, ["theme", "update"])
    assert result.exit_code == 1
    assert "Theme update refused" in result.output


def test_theme_repository_ignored_files_and_update_messages(monkeypatch):
    report = theme_install.ThemeInstallReport(("custom",), ("repo/code.py",))
    monkeypatch.setattr(command, "install_theme", lambda *_a: report)
    monkeypatch.setattr(command, "update_themes", lambda: (report,))
    installed = runner.invoke(cli.app, ["theme", "install", "https://github.com/example/themes"])
    assert "Ignored non-theme or linked file: repo/code.py" in installed.stdout
    assert "Updated: custom" in runner.invoke(cli.app, ["theme", "update"]).stdout
    updated = runner.invoke(cli.app, ["--json", "theme", "update"])
    assert json.loads(updated.stdout)["data"]["updated"] == [["custom"]]


def test_theme_list_reports_repairs_and_invalid_dropped_files(monkeypatch):
    root = theme.user_themes_dir()
    root.mkdir(parents=True)
    (root / "custom.toml").write_text(
        _custom().replace('accent = "#2dd4bf"', 'accent = "#555555"'), encoding="utf-8"
    )
    (root / "bad.toml").write_text("invalid TOML", encoding="utf-8")
    result = runner.invoke(cli.app, ["theme", "list"])
    assert result.exit_code == 0
    assert "Repair: accent:" in result.output
    assert 'Theme "bad.toml" not loaded' in result.output
