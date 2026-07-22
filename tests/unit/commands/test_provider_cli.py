# pyright: strict
"""CLI tests for distill provider show/list/set and global --provider."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import _helpers as helpers
from distill.commands import root as _root

runner = CliRunner()


@pytest.fixture
def isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setenv("DISTILL_PROVIDER", "xai")
    monkeypatch.delenv("DISTILL_MODEL", raising=False)
    monkeypatch.setenv("DISTILL_COST_MODE", "auto")
    return tmp_path


def test_provider_show_json(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["--json", "provider", "show"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["data"]["provider"] == "xai"
    assert payload["data"]["model"] == "grok-4.3"


def test_provider_list_gemini_json(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["--json", "provider", "list", "gemini"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["data"]["provider"] == "gemini"
    model_ids = [row["id"] for row in payload["data"]["models"]]
    assert "gemini-3.6-flash" in model_ids
    assert "gemini-3.5-flash-lite" in model_ids


def test_provider_set_persists_env(isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result = runner.invoke(
        cli.app,
        ["--json", "provider", "set", "gemini", "gemini-3.6-flash"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["data"]["provider"] == "gemini"
    assert payload["data"]["model"] == "gemini-3.6-flash"

    env_text = (isolated_cwd / ".env").read_text(encoding="utf-8")
    assert "DISTILL_PROVIDER=gemini" in env_text
    assert "DISTILL_MODEL=gemini-3.6-flash" in env_text
    assert os.environ["DISTILL_PROVIDER"] == "gemini"
    assert os.environ["DISTILL_MODEL"] == "gemini-3.6-flash"


def test_provider_set_default_model_with_yes(
    isolated_cwd: Path,
) -> None:
    result = runner.invoke(cli.app, ["--json", "provider", "set", "gemini", "--yes"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["data"]["model"] == "gemini-3.6-flash"


def test_provider_set_rejects_cross_family(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "set", "xai", "gemini-3.6-flash"])
    assert result.exit_code == 2
    assert "belongs to provider" in result.output


def test_provider_set_requires_args_without_tty(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "set"])
    assert result.exit_code == 2
    assert "Provider is required" in result.output


def test_global_provider_flag_sets_env(
    isolated_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Ctx:
        invoked_subcommand = "status"
        obj = None

        def ensure_object(self, _type: object) -> dict[str, object]:
            if self.obj is None:
                self.obj = {}
            return self.obj

    monkeypatch.setattr("distill._logging.configure_logging", lambda **_kwargs: None)
    monkeypatch.setattr(
        _root,
        "get_config",
        lambda: (_ for _ in ()).throw(RuntimeError("no config")),
    )

    _root.default_callback(
        Ctx(),  # type: ignore[arg-type]
        debug=False,
        quiet=False,
        verbose=False,
        json_output=False,
        model="gemini-3.5-flash-lite",
        provider="gemini",
        cost_mode="",
        version=False,
    )
    assert os.environ["DISTILL_PROVIDER"] == "gemini"
    assert os.environ["DISTILL_MODEL"] == "gemini-3.5-flash-lite"


def test_global_model_flag_infers_cloud_provider(
    isolated_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Ctx:
        invoked_subcommand = "status"
        obj = None

        def ensure_object(self, _type: object) -> dict[str, object]:
            if self.obj is None:
                self.obj = {}
            return self.obj

    monkeypatch.setattr("distill._logging.configure_logging", lambda **_kwargs: None)
    monkeypatch.setattr(
        _root,
        "get_config",
        lambda: (_ for _ in ()).throw(RuntimeError("no config")),
    )

    _root.default_callback(
        Ctx(),  # type: ignore[arg-type]
        debug=False,
        quiet=False,
        verbose=False,
        json_output=False,
        model="gemini-3.6-flash",
        provider="",
        cost_mode="",
        version=False,
    )
    assert os.environ["DISTILL_PROVIDER"] == "gemini"
    assert os.environ["DISTILL_MODEL"] == "gemini-3.6-flash"


def test_apply_output_mode_rejects_unknown_provider() -> None:
    import typer

    class Ctx:
        obj = None

        def ensure_object(self, _type: object) -> dict[str, object]:
            if self.obj is None:
                self.obj = {}
            return self.obj

    with pytest.raises(typer.Exit) as raised:
        helpers._apply_output_mode(
            Ctx(),  # type: ignore[arg-type]
            quiet=False,
            verbose=False,
            debug=False,
            json_output=False,
            model="",
            provider="not-a-provider",
        )
    assert raised.value.exit_code == 2


def test_get_provider_override_reads_context() -> None:
    class Ctx:
        def __init__(self, obj: dict[str, object] | None = None) -> None:
            self.obj = obj

    assert _root.get_provider_override(Ctx({"provider": "gemini"})) == "gemini"  # type: ignore[arg-type]
    assert _root.get_provider_override(Ctx({})) == ""  # type: ignore[arg-type]
    assert _root.get_provider_override(None) == ""
