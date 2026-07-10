"""Tests for `distill init` -- the guided first-run setup wizard.

The two failure modes the Frame named get explicit coverage: init must never
clobber an existing .env (it holds the user's keys), and it must never hang on a
prompt with no TTY (the loop-ready invariant).
"""

from __future__ import annotations

import builtins
import json
import os
import stat
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import httpx
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

        def fail_fdopen(descriptor, mode, *, encoding, newline):
            assert descriptor >= 0
            assert mode == "w"
            assert encoding == "utf-8"
            assert newline == "\n"
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
    @pytest.mark.parametrize(
        ("executable_exists", "expected"),
        [(True, "installed"), (False, "missing")],
    )
    def test_status_checks_browser_executable(
        self, tmp_path, monkeypatch, executable_exists, expected
    ):
        executable = tmp_path / "chromium"
        if executable_exists:
            executable.write_text("browser", encoding="utf-8")
        playwright = SimpleNamespace(chromium=SimpleNamespace(executable_path=str(executable)))
        monkeypatch.setattr(
            "playwright.sync_api.sync_playwright",
            lambda: nullcontext(playwright),
        )

        assert init_mod.chromium_status() == expected

    def test_status_is_unknown_when_playwright_cannot_import(self, monkeypatch):
        real_import = builtins.__import__

        def import_without_playwright(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "playwright.sync_api":
                raise ImportError("playwright unavailable")
            return real_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", import_without_playwright)

        assert init_mod.chromium_status() == "unknown"

    def test_status_is_missing_when_playwright_probe_fails(self, monkeypatch):
        def fail_probe():
            raise RuntimeError("browser registry unavailable")

        monkeypatch.setattr("playwright.sync_api.sync_playwright", fail_probe)

        assert init_mod.chromium_status() == "missing"

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
        def fail_run(argv, *, env, check):
            assert argv[-2:] == ["install", "chromium"]
            assert isinstance(env, dict)
            assert check is False
            raise OSError("process unavailable")

        monkeypatch.setattr(subprocess, "run", fail_run)

        assert init_mod._install_chromium() is False


class TestProviderBoundaries:
    def test_xai_validation_delegates_to_canonical_doctor_check(self, monkeypatch):
        config = object()
        observed = {}

        def validate(provider, received_config):
            observed.update(provider=provider, config=received_config)
            return "ok", "grok-4.3"

        monkeypatch.setattr("distill.commands._helpers.get_config", lambda: config)
        monkeypatch.setattr("distill.doctor.checks.doctor_validate_key", validate)

        assert init_mod._validate_xai() == ("ok", "grok-4.3")
        assert observed == {"provider": "xai", "config": config}

    @pytest.mark.parametrize(
        ("provider", "env_name", "base_url", "status_code", "expected_url", "expected"),
        [
            (
                "ollama",
                "OLLAMA_BASE_URL",
                "http://ollama.test/",
                200,
                "http://ollama.test/api/tags",
                "reachable",
            ),
            (
                "ollama",
                "OLLAMA_BASE_URL",
                "http://ollama.test/",
                503,
                "http://ollama.test/api/tags",
                "unreachable",
            ),
            (
                "lmstudio",
                "LMSTUDIO_BASE_URL",
                "http://lmstudio.test/v1/",
                200,
                "http://lmstudio.test/v1/models",
                "reachable",
            ),
            (
                "lmstudio",
                "LMSTUDIO_BASE_URL",
                "http://lmstudio.test/v1/",
                503,
                "http://lmstudio.test/v1/models",
                "unreachable",
            ),
        ],
    )
    def test_local_reachability_uses_provider_endpoint(
        self,
        monkeypatch,
        provider,
        env_name,
        base_url,
        status_code,
        expected_url,
        expected,
    ):
        observed = {}

        def get(url, *, timeout):
            observed.update(url=url, timeout=timeout)
            return SimpleNamespace(status_code=status_code)

        monkeypatch.setenv(env_name, base_url)
        monkeypatch.setattr(httpx, "get", get)

        assert init_mod._local_reachable(provider) == expected
        assert observed == {"url": expected_url, "timeout": 2.0}

    def test_local_reachability_handles_request_failure(self, monkeypatch):
        def fail_get(url, *, timeout):
            assert url == "http://localhost:11434/api/tags"
            assert timeout == 2.0
            raise httpx.ConnectError("local provider unavailable")

        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        monkeypatch.setattr(httpx, "get", fail_get)

        assert init_mod._local_reachable("ollama") == "unreachable"


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


def test_interactive_cloud_path_saves_entered_key(in_tmp, monkeypatch):
    responses = iter(["cloud", "xai-entered"])
    prompt_messages = []

    def prompt(message, *, default, non_tty_default):
        prompt_messages.append(message)
        assert default in {"cloud", ""}
        assert non_tty_default in {"cloud", ""}
        return next(responses)

    monkeypatch.setattr(init_mod, "tty_prompt", prompt)
    monkeypatch.setattr(init_mod, "_validate_xai", lambda: ("ok", "grok-4.3"))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    assert len(prompt_messages) == 2
    assert "Saved" in result.output
    assert "XAI_API_KEY=xai-entered" in (in_tmp / ".env").read_text(encoding="utf-8")


def test_local_non_json_path_sets_default_and_renders_status(in_tmp, monkeypatch):
    def reachable(provider):
        assert provider == "ollama"
        return "reachable"

    monkeypatch.setattr(init_mod, "_local_provider", lambda: "")
    monkeypatch.setattr(init_mod, "_local_reachable", reachable)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["init", "--provider", "local", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Set" in result.output
    assert "ollama: reachable" in result.output
    assert "DISTILL_PROVIDER=ollama" in (in_tmp / ".env").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("provider", "expected_blocker"),
    [
        (
            "ollama",
            "Start Ollama and pull a model, e.g. `ollama pull qwen3.5:27b`, "
            "then re-run `distill init`.",
        ),
        (
            "lmstudio",
            "Start LM Studio and load a model, then re-run `distill init`.",
        ),
    ],
)
def test_local_unreachable_path_reports_blocker(in_tmp, monkeypatch, provider, expected_blocker):
    def unreachable(received_provider):
        assert received_provider == provider
        return "unreachable"

    monkeypatch.setattr(init_mod, "_local_provider", lambda: provider)
    monkeypatch.setattr(init_mod, "_local_reachable", unreachable)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["local_reachable"] is False
    assert payload["data"]["blocking"] == [expected_blocker]


@pytest.mark.parametrize(
    ("install_succeeds", "expected_exit"),
    [(True, 0), (False, 1)],
)
def test_yes_installs_missing_browser(in_tmp, monkeypatch, install_succeeds, expected_exit):
    monkeypatch.setattr(init_mod, "_validate_xai", lambda: ("ok", "grok-4.3"))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "missing")
    monkeypatch.setattr(init_mod, "_install_chromium", lambda: install_succeeds)

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == expected_exit
    assert "Installing Chromium" in result.output
    expected_status = "installed" if install_succeeds else "missing"
    assert f"Browser: {expected_status}" in result.output
