"""Doctor and install-hint edges for a first run outside a checkout."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import _doctor_report as report
from distill.commands import doctor as doctor_mod
from distill.commands.init import set_env_var
from distill.config import DistillConfig
from distill.env_files import existing_env_files, load_distill_dotenv, writable_env_path
from distill.update import optional_extra_install_hint, optional_package_install_hint

runner = CliRunner()


def test_install_hints_follow_uv_pipx_and_pip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("distill.update.detect_install_method", lambda: "uv")
    assert optional_package_install_hint("faster-whisper") == (
        "uv tool install distillr --with faster-whisper"
    )
    assert (
        optional_extra_install_hint("entailment")
        == "uv tool install 'distillr[entailment]' --force"
    )

    monkeypatch.setattr("distill.update.detect_install_method", lambda: "pipx")
    assert optional_package_install_hint("faster-whisper") == "pipx inject distillr faster-whisper"
    assert optional_extra_install_hint("entailment") == "pipx install 'distillr[entailment]'"

    monkeypatch.setattr("distill.update.detect_install_method", lambda: "pip")
    assert optional_package_install_hint("faster-whisper") == "pip install faster-whisper"
    assert optional_extra_install_hint("entailment") == "pip install 'distillr[entailment]'"


def test_reported_browser_status_names_a_system_browser_without_launching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("distill.commands.init.chromium_status", lambda: "installed")
    assert report.reported_browser_status() == "installed"
    monkeypatch.setattr("distill.commands.init.chromium_status", lambda: "unsafe")
    assert report.reported_browser_status() == "unsafe"
    monkeypatch.setattr("distill.commands.init.chromium_status", lambda: "missing")
    monkeypatch.setattr(
        "distill.ingestors.sites.system_browser.candidate_browser_path",
        lambda: "/usr/bin/chromium",
    )
    assert report.reported_browser_status() == "system (/usr/bin/chromium)"
    monkeypatch.setattr(
        "distill.ingestors.sites.system_browser.candidate_browser_path",
        lambda: None,
    )
    assert report.reported_browser_status() == "missing"


def test_ollama_cloud_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        def __init__(self, status: str) -> None:
            self._status = status

        async def cloud_status(self) -> str:
            return self._status

    monkeypatch.setattr(
        "distill.llm.providers.ollama.OllamaProvider",
        lambda: Provider("enabled"),
    )
    assert report._ollama_cloud_notice() == "cloud: ENABLED, local routes refused"
    monkeypatch.setattr(
        "distill.llm.providers.ollama.OllamaProvider",
        lambda: Provider("disabled"),
    )
    assert report._ollama_cloud_notice() == "cloud: disabled (config)"
    monkeypatch.setattr(
        "distill.llm.providers.ollama.OllamaProvider",
        lambda: Provider("unknown"),
    )
    assert report._ollama_cloud_notice() == ""

    class Boom:
        def __init__(self) -> None:
            raise RuntimeError("down")

    monkeypatch.setattr("distill.llm.providers.ollama.OllamaProvider", Boom)
    assert report._ollama_cloud_notice() == ""


def test_user_env_is_visible_from_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    path = writable_env_path()
    set_env_var(path, "DISTILL_MODEL", "gemma4:e4b")
    monkeypatch.delenv("DISTILL_MODEL", raising=False)
    monkeypatch.chdir(second)

    load_distill_dotenv()

    assert os.environ["DISTILL_MODEL"] == "gemma4:e4b"
    assert path in existing_env_files()

    config = DistillConfig(distill_output_dir=tmp_path / "library", distill_cost_mode="no-metered")
    config.library_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(doctor_mod, "get_config", lambda: config)
    monkeypatch.setattr(doctor_mod, "_check_ollama_status", lambda: ("unavailable", ()))
    monkeypatch.setattr(
        doctor_mod,
        "_check_lmstudio_models",
        lambda: ("unavailable", ()),
        raising=False,
    )
    monkeypatch.setattr("distill.commands.init.chromium_status", lambda: "installed")
    monkeypatch.setattr("distill.commands._doctor_report._ollama_cloud_notice", lambda: "")

    result = runner.invoke(cli.app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "Config files" in result.output
    assert str(path) in result.output
