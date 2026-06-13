"""Tests for `distill init` -- the guided first-run setup wizard.

The two failure modes the Frame named get explicit coverage: init must never
clobber an existing .env (it holds the user's keys), and it must never hang on a
prompt with no TTY (the loop-ready invariant).
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from distill.cli import app
from distill.commands import init as init_mod

runner = CliRunner()


# ─── Pure file helpers ────────────────────────────────────────────────


class TestEnvFileHelpers:
    def test_create_when_missing(self, tmp_path):
        path = tmp_path / ".env"
        assert init_mod.create_env_file(path) is True
        assert path.exists()
        assert "XAI_API_KEY=" in path.read_text(encoding="utf-8")

    def test_never_clobbers_existing(self, tmp_path):
        """The key-destruction failure mode: an existing .env is left untouched."""
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=secret-do-not-lose\n", encoding="utf-8")
        assert init_mod.create_env_file(path) is False
        assert path.read_text(encoding="utf-8") == "XAI_API_KEY=secret-do-not-lose\n"

    def test_force_overwrites(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("OLD=1\n", encoding="utf-8")
        assert init_mod.create_env_file(path, force=True) is True
        assert "OLD=1" not in path.read_text(encoding="utf-8")

    def test_set_env_var_replaces_in_place(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=\nGEMINI_API_KEY=keep\n", encoding="utf-8")
        init_mod.set_env_var(path, "XAI_API_KEY", "xai-new")
        text = path.read_text(encoding="utf-8")
        assert "XAI_API_KEY=xai-new" in text
        assert "GEMINI_API_KEY=keep" in text  # other lines preserved

    def test_set_env_var_leaves_comments_alone(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("# DISTILL_PROVIDER=ollama\n", encoding="utf-8")
        init_mod.set_env_var(path, "DISTILL_PROVIDER", "ollama")
        text = path.read_text(encoding="utf-8")
        # The commented line stays; a real assignment is appended.
        assert "# DISTILL_PROVIDER=ollama" in text
        assert "\nDISTILL_PROVIDER=ollama" in text

    def test_set_env_var_creates_file_if_absent(self, tmp_path):
        path = tmp_path / ".env"
        init_mod.set_env_var(path, "XAI_API_KEY", "k")
        assert path.exists()
        assert "XAI_API_KEY=k" in path.read_text(encoding="utf-8")


# ─── Command behavior ─────────────────────────────────────────────────


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """Run init in an isolated cwd so .env lands in tmp, not the repo."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_no_tty_does_not_hang_and_creates_env(in_tmp, monkeypatch):
    """The loop-ready failure mode: no stdin, no flags -> completes, no hang."""
    monkeypatch.setattr(init_mod, "_validate_xai", lambda: ("missing", ""))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "missing")
    # CliRunner provides a non-TTY stdin; with no input the wizard must not block.
    result = runner.invoke(app, ["init"], input="")
    assert result.exit_code == 1  # not ready (no key, no browser)
    assert (in_tmp / ".env").exists()


def test_cloud_ready_path(in_tmp, monkeypatch):
    monkeypatch.setattr(init_mod, "_validate_xai", lambda: ("ok", "grok-4.3"))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")
    result = runner.invoke(app, ["init", "--yes"])
    assert result.exit_code == 0, result.output
    assert "ready" in result.output.lower()
    assert "distill papers" in result.output


def test_json_verdict(in_tmp, monkeypatch):
    monkeypatch.setattr(init_mod, "_validate_xai", lambda: ("ok", "grok-4.3"))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")
    result = runner.invoke(app, ["--json", "init", "--yes"])
    env = json.loads(result.stdout)
    assert env["status"] == "ok"
    assert env["data"]["ready"] is True
    assert env["data"]["provider"] == "cloud"
    assert env["data"]["xai_key"] == "ok"


def test_existing_env_not_clobbered_by_command(in_tmp, monkeypatch):
    (in_tmp / ".env").write_text("XAI_API_KEY=keepme\n", encoding="utf-8")
    monkeypatch.setattr(init_mod, "_validate_xai", lambda: ("ok", "grok-4.3"))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")
    runner.invoke(app, ["init", "--yes"])
    assert "keepme" in (in_tmp / ".env").read_text(encoding="utf-8")


def test_local_provider_path(in_tmp, monkeypatch):
    monkeypatch.setattr(init_mod, "_local_reachable", lambda prov: "reachable")
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")
    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    env = json.loads(result.stdout)
    assert env["data"]["provider"] == "local"
    assert env["data"]["ready"] is True
    # DISTILL_PROVIDER was written to .env
    assert "DISTILL_PROVIDER=ollama" in (in_tmp / ".env").read_text(encoding="utf-8")
