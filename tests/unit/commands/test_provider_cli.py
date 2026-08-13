# pyright: strict
"""CLI tests for distill provider show/list/set and global --provider."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import _helpers as helpers
from distill.commands import provider as _provider
from distill.commands import root as _root

runner = CliRunner()


def _scripted_prompt(answers: list[str]) -> Callable[..., str]:
    """Return a ``tty_prompt`` stand-in that yields *answers* in call order."""
    responses = iter(answers)

    def _prompt(message: str, *, default: str, non_tty_default: str | None = None) -> str:
        del message, default, non_tty_default
        return next(responses)

    return _prompt


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
    assert payload["data"]["model"] == "grok-4.6"


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


def test_provider_root_no_subcommand_shows_human_route(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider"])
    assert result.exit_code == 0, result.output
    assert "grok-4.6" in result.output
    assert "Provider" in result.output
    assert "Pricing" in result.output
    assert "Change default" in result.output


def test_provider_list_unknown_provider_json(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["--json", "provider", "list", "bogus"])
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "usage_error"
    assert "Unknown provider" in payload["error"]


def test_provider_list_unknown_provider_human(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "list", "zzz"])
    assert result.exit_code == 2
    assert "Unknown provider" in result.output


def test_provider_list_gemini_human_table(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "list", "gemini"])
    assert result.exit_code == 0, result.output
    assert "gemini-3.6-flash" in result.output
    assert "recommended" in result.output


def test_provider_list_ollama_human_shows_note(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "list", "ollama"])
    assert result.exit_code == 0, result.output
    assert "local inventory" in result.output


def test_provider_list_agent_human_shows_note(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "list", "agent"])
    assert result.exit_code == 0, result.output
    assert "Host-managed deferred work" in result.output


def test_provider_list_all_human_table(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "list"])
    assert result.exit_code == 0, result.output
    assert "gemini" in result.output
    assert "xai" in result.output
    assert "Set default route" in result.output


def test_provider_list_all_json(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["--json", "provider", "list"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    provider_ids = [row["id"] for row in payload["data"]["providers"]]
    assert "xai" in provider_ids
    assert "ollama" in provider_ids


def test_provider_set_human_output_with_price(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "set", "gemini", "gemini-3.6-flash"])
    assert result.exit_code == 0, result.output
    assert "Set" in result.output
    assert "DISTILL_PROVIDER=gemini" in result.output
    assert "Pricing" in result.output
    assert "One-run override" in result.output


def test_provider_set_local_model_has_no_price(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "set", "ollama", "qwen3.5:27b"])
    assert result.exit_code == 0, result.output
    assert "DISTILL_PROVIDER=ollama" in result.output
    assert "DISTILL_MODEL=qwen3.5:27b" in result.output
    # No catalog price for a local model id -> the pricing line is omitted.
    assert "Pricing" not in result.output


def test_provider_set_requires_model_for_local_without_tty(isolated_cwd: Path) -> None:
    result = runner.invoke(cli.app, ["provider", "set", "ollama"])
    assert result.exit_code == 2
    assert "Model is required for provider 'ollama'" in result.output


def test_provider_set_env_file_error_human(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(_provider, "set_env_var", _boom)
    result = runner.invoke(cli.app, ["provider", "set", "gemini", "gemini-3.6-flash"])
    assert result.exit_code == 1
    assert "Could not update" in result.output


def test_provider_set_env_file_error_json(
    isolated_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(_provider, "set_env_var", _boom)
    result = runner.invoke(cli.app, ["--json", "provider", "set", "gemini", "gemini-3.6-flash"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "env_file_error"


def test_resolve_set_selection_prompts_provider_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_provider, "isatty", lambda: True)
    # Interactive prompting is also gated on JSON mode being off. A real CLI run
    # sets that per invocation; calling the helper directly can otherwise inherit
    # a previous test's global.
    monkeypatch.setattr(_provider, "json_mode_active", lambda: False)
    # First prompt picks provider #2 (gemini); second picks model #1 (default).
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt(["2", "1"]))
    provider, model = _provider._resolve_set_selection(  # pyright: ignore[reportPrivateUsage]
        provider=None, model=None, yes=False
    )
    assert provider == "gemini"
    assert model == "gemini-3.6-flash"


def test_resolve_set_selection_empty_model_after_prompt_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_provider, "isatty", lambda: True)
    monkeypatch.setattr(_provider, "json_mode_active", lambda: False)

    def _empty_model(_provider_name: str, *, default: str) -> str:
        del _provider_name, default
        return ""

    monkeypatch.setattr(_provider, "_prompt_model", _empty_model)
    with pytest.raises(ValueError, match="Model is required"):
        _provider._resolve_set_selection(  # pyright: ignore[reportPrivateUsage]
            provider="gemini", model=None, yes=False
        )


def test_prompt_provider_accepts_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt(["anthropic"]))
    assert _provider._prompt_provider() == "anthropic"  # pyright: ignore[reportPrivateUsage]


def test_prompt_provider_out_of_range_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt(["99"]))
    with pytest.raises(ValueError, match="out of range"):
        _provider._prompt_provider()  # pyright: ignore[reportPrivateUsage]


def test_prompt_provider_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt([""]))
    with pytest.raises(ValueError, match="No provider selected"):
        _provider._prompt_provider()  # pyright: ignore[reportPrivateUsage]


def test_prompt_model_digit_selects_from_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt(["1"]))
    assert (
        _provider._prompt_model("gemini", default="gemini-3.6-flash")  # pyright: ignore[reportPrivateUsage]
        == "gemini-3.6-flash"
    )


def test_prompt_model_empty_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt([""]))
    assert (
        _provider._prompt_model("gemini", default="gemini-3.6-flash")  # pyright: ignore[reportPrivateUsage]
        == "gemini-3.6-flash"
    )


def test_prompt_model_out_of_range_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt(["99"]))
    with pytest.raises(ValueError, match="out of range"):
        _provider._prompt_model("gemini", default="gemini-3.6-flash")  # pyright: ignore[reportPrivateUsage]


def test_prompt_model_freeform_id_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt(["gemini-custom-id"]))
    assert (
        _provider._prompt_model("gemini", default="gemini-3.6-flash")  # pyright: ignore[reportPrivateUsage]
        == "gemini-custom-id"
    )


def test_prompt_model_no_catalog_returns_typed_id(monkeypatch: pytest.MonkeyPatch) -> None:
    # ollama has no catalog models -> the free-form exact-id branch is used.
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt(["qwen3.5:27b"]))
    assert _provider._prompt_model("ollama", default="") == "qwen3.5:27b"  # pyright: ignore[reportPrivateUsage]


def test_prompt_model_no_catalog_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_provider, "tty_prompt", _scripted_prompt([""]))
    with pytest.raises(ValueError, match="Model is required"):
        _provider._prompt_model("ollama", default="")  # pyright: ignore[reportPrivateUsage]
