"""Tests for `distill init` -- the guided first-run setup wizard.

The two failure modes the Frame named get explicit coverage: init must never
clobber an existing .env (it holds the user's keys), and it must never hang on a
prompt with no TTY (the loop-ready invariant).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from distill.cli import app
from distill.commands import init as init_mod

runner = CliRunner()


# ─── Pure file helpers ────────────────────────────────────────────────


class TestEnvFileHelpers:
    def test_create_uses_owner_only_file_mode(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"
        real_open = os.open
        requested_modes = []

        def open_with_mode(file, flags, mode=0o777):
            requested_modes.append(mode)
            return real_open(file, flags, mode)

        monkeypatch.setattr(init_mod.os, "open", open_with_mode)
        assert init_mod.create_env_file(path) is True
        assert requested_modes == [0o600]

    def test_existing_env_permissions_are_tightened_without_clobber(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=keep\n", encoding="utf-8")
        chmod_modes = []

        def record_chmod(file_path, mode):
            assert file_path == path
            chmod_modes.append(mode)

        monkeypatch.setattr(init_mod, "_POSIX_PERMISSIONS", True)
        monkeypatch.setattr(Path, "chmod", record_chmod)

        assert init_mod.create_env_file(path) is False
        assert path.read_text(encoding="utf-8") == "XAI_API_KEY=keep\n"
        assert chmod_modes == [0o600]

    def test_write_closes_descriptor_when_stream_creation_fails(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"
        real_close = os.close
        closed_descriptors = []

        def fail_fdopen(*args, **kwargs):
            raise OSError("stream unavailable")

        def record_close(descriptor):
            closed_descriptors.append(descriptor)
            real_close(descriptor)

        monkeypatch.setattr(init_mod.os, "fdopen", fail_fdopen)
        monkeypatch.setattr(init_mod.os, "close", record_close)

        with pytest.raises(OSError, match="stream unavailable"):
            init_mod.create_env_file(path)
        assert len(closed_descriptors) == 1

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
    def test_env_file_stays_owner_only_across_writes(self, tmp_path):
        path = tmp_path / ".env"
        old_umask = os.umask(0)
        try:
            assert init_mod.create_env_file(path) is True
        finally:
            os.umask(old_umask)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

        path.chmod(0o644)
        init_mod.set_env_var(path, "XAI_API_KEY", "secret")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

        path.chmod(0o644)
        assert init_mod.create_env_file(path) is False
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

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


class TestBrowserSetup:
    def test_install_uses_fixed_argv_and_strips_python_injection(self, monkeypatch):
        observed = {}

        def run(argv, *, env, check):
            observed.update(argv=argv, env=env, check=check)
            return SimpleNamespace(returncode=0)

        monkeypatch.setenv("PYTHONPATH", "injected-path")
        monkeypatch.setenv("PYTHONHOME", "injected-home")
        monkeypatch.setenv("DISTILL_TEST_MARKER", "kept")
        monkeypatch.setattr(subprocess, "run", run)

        assert init_mod._install_chromium() is True
        assert observed["argv"] == [
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
        ]
        assert observed["env"]["DISTILL_TEST_MARKER"] == "kept"
        assert "PYTHONPATH" not in observed["env"]
        assert "PYTHONHOME" not in observed["env"]
        assert observed["check"] is False

    def test_install_failure_returns_false(self, monkeypatch):
        def fail_run(*args, **kwargs):
            raise OSError("process unavailable")

        monkeypatch.setattr(subprocess, "run", fail_run)

        assert init_mod._install_chromium() is False


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
