"""Tests for `distill init` -- the guided first-run setup wizard.

The two failure modes the Frame named get explicit coverage: init must never
clobber an existing .env (it holds the user's keys), and it must never hang on a
prompt with no TTY (the loop-ready invariant).
"""

from __future__ import annotations

import builtins
import errno
import json
import os
import stat
import subprocess
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from distill.cli import app
from distill.commands import init as init_mod
from distill.llm.router import RouterConfig

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
        assert requested_modes[-1] == 0o600

    def test_existing_env_permissions_are_tightened_without_clobber(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=keep\n", encoding="utf-8")
        chmod_modes = []

        def record_chmod(descriptor, mode):
            assert isinstance(descriptor, int)
            chmod_modes.append(mode)

        monkeypatch.setattr(init_mod, "_POSIX_PERMISSIONS", True)
        monkeypatch.setattr(init_mod.os, "fchmod", record_chmod, raising=False)

        descriptor = init_mod._open_existing_env(path)
        assert descriptor is not None
        os.close(descriptor)
        assert path.read_text(encoding="utf-8") == "XAI_API_KEY=keep\n"
        assert chmod_modes == [0o600]

    def test_existing_env_descriptor_must_reference_regular_file(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=old\n", encoding="utf-8")
        closed = []
        monkeypatch.setattr(init_mod.os, "open", lambda file_path, flags: 41)
        monkeypatch.setattr(
            init_mod.os,
            "fstat",
            lambda descriptor: SimpleNamespace(st_mode=stat.S_IFDIR),
        )
        monkeypatch.setattr(init_mod.os, "close", lambda descriptor: closed.append(descriptor))

        with pytest.raises(ValueError, match="non-file env path"):
            init_mod._open_existing_env(path)

        assert closed == [41]

    @pytest.mark.parametrize(
        ("error_number", "expected_exception"),
        [(errno.ELOOP, ValueError), (errno.EACCES, PermissionError)],
    )
    def test_existing_env_open_errors_fail_closed(
        self, tmp_path, monkeypatch, error_number, expected_exception
    ):
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=old\n", encoding="utf-8")

        def fail_open(file_path, flags):
            raise OSError(error_number, "refused")

        monkeypatch.setattr(init_mod.os, "open", fail_open)

        with pytest.raises(expected_exception):
            init_mod._open_existing_env(path)

    def test_env_path_rejects_directory(self, tmp_path):
        with pytest.raises(ValueError, match="non-file env path"):
            init_mod.create_env_file(tmp_path)

    @pytest.mark.skipif(os.name != "nt", reason="Windows symlink-following descriptor semantics")
    def test_windows_symlink_swap_and_replace_fails_identity_check(self, tmp_path, monkeypatch):
        target = tmp_path / "operator-notes.txt"
        target.write_text("preserve me\n", encoding="utf-8")
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=old\n", encoding="utf-8")
        probe = tmp_path / "symlink-probe"
        try:
            probe.symlink_to(target)
            probe.unlink()
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        real_open = os.open
        real_lstat = type(path).lstat
        swapped = False

        def lstat_then_swap(file_path):
            nonlocal swapped
            result = real_lstat(file_path)
            if file_path == path and not swapped:
                file_path.unlink()
                file_path.symlink_to(target)
                swapped = True
            return result

        def open_then_replace(file_path, flags, mode=0o777):
            descriptor = real_open(file_path, flags, mode)
            path.unlink()
            path.write_text("replacement\n", encoding="utf-8")
            return descriptor

        monkeypatch.setattr(type(path), "lstat", lstat_then_swap)
        monkeypatch.setattr(init_mod.os, "open", open_then_replace)

        with pytest.raises(ValueError, match="changed while it was being opened"):
            init_mod._open_existing_env(path)

        assert target.read_text(encoding="utf-8") == "preserve me\n"

    @pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO semantics")
    def test_fifo_swap_after_validation_is_rejected_without_blocking(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=old\n", encoding="utf-8")
        real_lstat = type(path).lstat
        swapped = False

        def lstat_then_swap(file_path):
            nonlocal swapped
            result = real_lstat(file_path)
            if file_path == path and not swapped:
                file_path.unlink()
                os.mkfifo(file_path)
                swapped = True
            return result

        monkeypatch.setattr(type(path), "lstat", lstat_then_swap)

        with pytest.raises(ValueError, match="non-file env path"):
            init_mod._open_existing_env(path)

    def test_atomic_write_failure_does_not_create_env(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"
        real_create = init_mod._create_env_text_exclusive

        def fail_write(file_path, content):
            if file_path == path:
                assert "XAI_API_KEY=" in content
                raise OSError("stream unavailable")
            return real_create(file_path, content)

        monkeypatch.setattr(init_mod, "_create_env_text_exclusive", fail_write)

        with pytest.raises(OSError, match="stream unavailable"):
            init_mod.create_env_file(path)
        assert not path.exists()

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

    def test_exclusive_create_never_replaces_existing_file(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("KEEP=1\n", encoding="utf-8")

        assert init_mod._create_env_text_exclusive(path, "REPLACE=1\n") is False
        assert path.read_text(encoding="utf-8") == "KEEP=1\n"

    def test_create_preserves_file_that_wins_missing_path_race(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"

        def lose_race(file_path, content):
            file_path.write_text("RACER=keep\n", encoding="utf-8")
            return False

        monkeypatch.setattr(init_mod, "_create_env_text_exclusive", lose_race)

        assert init_mod.create_env_file(path) is False
        assert path.read_text(encoding="utf-8") == "RACER=keep\n"

    def test_set_env_var_rereads_file_that_wins_creation_race(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"

        def lose_race(file_path, content):
            file_path.write_text("RACER=keep\n", encoding="utf-8")
            return False

        monkeypatch.setattr(init_mod, "_create_env_text_exclusive", lose_race)

        init_mod.set_env_var(path, "XAI_API_KEY", "new")

        assert path.read_text(encoding="utf-8") == "RACER=keep\nXAI_API_KEY=new\n"

    def test_concurrent_env_updates_preserve_both_keys(self, tmp_path, monkeypatch):
        path = tmp_path / ".env"
        path.write_text("BASE=1\n", encoding="utf-8")
        first_read = threading.Event()
        release_first = threading.Event()
        second_read = threading.Event()
        failures: list[BaseException] = []
        real_read = init_mod._read_existing_env

        def observed_read(file_path):
            content = real_read(file_path)
            if file_path == path:
                if threading.current_thread().name == "first-env-update":
                    first_read.set()
                    assert release_first.wait(timeout=2)
                else:
                    second_read.set()
            return content

        def update(key: str) -> None:
            try:
                init_mod.set_env_var(path, key, "1")
            except BaseException as exc:
                failures.append(exc)

        monkeypatch.setattr(init_mod, "_read_existing_env", observed_read)
        first = threading.Thread(target=update, args=("KEY_A",), name="first-env-update")
        second = threading.Thread(target=update, args=("KEY_B",), name="second-env-update")
        first.start()
        assert first_read.wait(timeout=2)
        second.start()
        try:
            assert not second_read.wait(timeout=0.1)
        finally:
            release_first.set()
            first.join(timeout=2)
            second.join(timeout=2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert failures == []
        assert path.read_text(encoding="utf-8") == "BASE=1\nKEY_A=1\nKEY_B=1\n"

    def test_preexisting_empty_env_lock_is_initialized(self, tmp_path):
        path = tmp_path / ".env"
        lock_path = tmp_path / ".env.distill.lock"
        path.write_text("BASE=1\n", encoding="utf-8")
        lock_path.touch()

        init_mod.set_env_var(path, "KEY", "1")

        assert path.read_text(encoding="utf-8") == "BASE=1\nKEY=1\n"
        assert lock_path.read_bytes() == b"\0"

    def test_existing_non_utf8_env_is_preserved_without_force(self, tmp_path):
        path = tmp_path / ".env"
        original = b"XAI_API_KEY=\xff\n"
        path.write_bytes(original)

        assert init_mod.create_env_file(path) is False
        assert path.read_bytes() == original

    def test_force_overwrites_existing_non_utf8_env(self, tmp_path):
        path = tmp_path / ".env"
        path.write_bytes(b"XAI_API_KEY=\xff\n")

        assert init_mod.create_env_file(path, force=True) is True
        assert "XAI_API_KEY=" in path.read_text(encoding="utf-8")

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

    def test_set_env_var_canonicalizes_duplicate_and_export_assignments(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text(
            "# XAI_API_KEY=commented\n"
            "XAI_API_KEY=old-first\n"
            "OTHER=keep\n"
            "export XAI_API_KEY = stale-last\n",
            encoding="utf-8",
        )

        init_mod.set_env_var(path, "XAI_API_KEY", "new-value")

        text = path.read_text(encoding="utf-8")
        active = [
            line
            for line in text.splitlines()
            if not line.lstrip().startswith("#") and "XAI_API_KEY" in line
        ]
        assert active == ["XAI_API_KEY=new-value"]
        assert "# XAI_API_KEY=commented" in text
        assert "OTHER=keep" in text
        assert init_mod._env_file_value(text, "XAI_API_KEY") == "new-value"

    def test_set_env_var_creates_file_if_absent(self, tmp_path):
        path = tmp_path / ".env"
        init_mod.set_env_var(path, "XAI_API_KEY", "k")
        assert path.exists()
        assert "XAI_API_KEY=k" in path.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        ("key", "value", "message"),
        [
            ("INVALID-KEY", "value", "name is invalid"),
            ("VALID_KEY", "line\nbreak", "control characters"),
            ("VALID_KEY", "nul\x00byte", "control characters"),
        ],
    )
    def test_set_env_var_rejects_unsafe_assignments(self, tmp_path, key, value, message):
        path = tmp_path / ".env"

        with pytest.raises(ValueError, match=message):
            init_mod.set_env_var(path, key, value)

        assert not path.exists()

    @pytest.mark.parametrize("operation", ["set", "force"])
    def test_env_writes_reject_symlinks_without_touching_the_target(self, tmp_path, operation):
        target = tmp_path / "operator-notes.txt"
        target.write_text("preserve me\n", encoding="utf-8")
        path = tmp_path / ".env"
        try:
            path.symlink_to(target)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        with pytest.raises(ValueError, match="symbolic link"):
            if operation == "set":
                init_mod.set_env_var(path, "XAI_API_KEY", "attacker-value")
            else:
                init_mod.create_env_file(path, force=True)

        assert path.is_symlink()
        assert target.read_text(encoding="utf-8") == "preserve me\n"

    @pytest.mark.parametrize("operation", ["set", "create"])
    def test_env_reads_reject_hardlinks_without_touching_target(self, tmp_path, operation):
        target = tmp_path / "operator-notes.txt"
        target.write_text("preserve me\n", encoding="utf-8")
        path = tmp_path / ".env"
        try:
            path.hardlink_to(target)
        except OSError as exc:
            pytest.skip(f"hard-link creation unavailable: {exc}")

        with pytest.raises(ValueError, match="multiply linked"):
            if operation == "set":
                init_mod.set_env_var(path, "XAI_API_KEY", "attacker-value")
            else:
                init_mod.create_env_file(path)

        assert target.read_text(encoding="utf-8") == "preserve me\n"

    @pytest.mark.skipif(
        os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
        reason="POSIX no-follow descriptor semantics",
    )
    def test_env_symlink_swap_after_validation_cannot_touch_target(self, tmp_path, monkeypatch):
        target = tmp_path / "operator-notes.txt"
        target.write_text("preserve me\n", encoding="utf-8")
        target.chmod(0o640)
        path = tmp_path / ".env"
        path.write_text("XAI_API_KEY=old\n", encoding="utf-8")
        real_validate = init_mod._validate_env_path
        swapped = False

        def validate_then_swap(file_path):
            nonlocal swapped
            real_validate(file_path)
            if not swapped:
                file_path.unlink()
                file_path.symlink_to(target)
                swapped = True

        monkeypatch.setattr(init_mod, "_validate_env_path", validate_then_swap)

        with pytest.raises(ValueError, match="symbolic link"):
            init_mod.set_env_var(path, "XAI_API_KEY", "attacker-value")

        assert target.read_text(encoding="utf-8") == "preserve me\n"
        assert stat.S_IMODE(target.stat().st_mode) == 0o640


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

    @pytest.mark.parametrize(
        "variable",
        ["PLAYWRIGHT_NODEJS_PATH", "PLAYWRIGHT_BROWSERS_PATH"],
    )
    def test_status_refuses_playwright_execution_override_before_probe(
        self,
        monkeypatch,
        variable,
    ):
        probed = []
        monkeypatch.setenv(variable, "untrusted-override")
        monkeypatch.setattr(
            "playwright.sync_api.sync_playwright",
            lambda: probed.append(True),
        )

        assert init_mod.chromium_status() == "unsafe"
        assert probed == []

    def test_install_uses_fixed_argv_and_strips_python_injection(self, monkeypatch):
        observed = {}

        def run(argv, *, cwd, env, check):
            observed.update(argv=argv, cwd=cwd, env=env, check=check)
            return SimpleNamespace(returncode=0)

        monkeypatch.setenv("PYTHONPATH", "injected-path")
        monkeypatch.setenv("PYTHONHOME", "injected-home")
        monkeypatch.setenv("PYTHONWARNINGS", "ignore::injected.Warning")
        monkeypatch.setenv("PYTHONUSERBASE", "injected-userbase")
        monkeypatch.setenv("PYTHONINSPECT", "1")
        monkeypatch.setenv("PLAYWRIGHT_NODEJS_PATH", "injected-node")
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "injected-browser")
        monkeypatch.setenv("NODE_OPTIONS", "--require injected.js")
        monkeypatch.setenv("DISTILL_TEST_MARKER", "kept")
        monkeypatch.setattr(subprocess, "run", run)

        assert init_mod._install_chromium() is True
        assert observed["argv"] == [
            sys.executable,
            "-P",
            "-m",
            "playwright",
            "install",
            "chromium",
        ]
        assert observed["env"]["DISTILL_TEST_MARKER"] == "kept"
        assert "PYTHONPATH" not in observed["env"]
        assert "PYTHONHOME" not in observed["env"]
        assert "PYTHONWARNINGS" not in observed["env"]
        assert "PYTHONUSERBASE" not in observed["env"]
        assert "PYTHONINSPECT" not in observed["env"]
        assert "PLAYWRIGHT_NODEJS_PATH" not in observed["env"]
        assert "PLAYWRIGHT_BROWSERS_PATH" not in observed["env"]
        assert "NODE_OPTIONS" not in observed["env"]
        assert observed["env"]["PYTHONSAFEPATH"] == "1"
        assert observed["env"]["PYTHONNOUSERSITE"] == "1"
        assert observed["cwd"] == str(Path(sys.executable).resolve().parent)
        assert observed["check"] is False

    def test_install_failure_returns_false(self, monkeypatch):
        def fail_run(argv, *, cwd, env, check):
            assert argv[-2:] == ["install", "chromium"]
            assert Path(cwd).is_absolute()
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


# ─── Command behavior ─────────────────────────────────────────────────


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    """Run init in an isolated cwd so .env lands in tmp, not the repo."""
    monkeypatch.chdir(tmp_path)
    base_names = (
        "DISTILL_PROVIDER",
        "DISTILL_COST_MODE",
        "OLLAMA_BASE_URL",
        "LMSTUDIO_BASE_URL",
    )
    route_names = tuple(
        f"DISTILL_{field_name.upper()}"
        for field_name in RouterConfig.model_fields
        if field_name == "model"
        or field_name.endswith("_model")
        or field_name.endswith("_provider")
    )
    names = tuple(dict.fromkeys((*base_names, *route_names)))
    original = {name: os.environ.get(name) for name in names}
    for name in names:
        monkeypatch.delenv(name, raising=False)
    yield tmp_path
    for name, value in original.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def test_no_tty_does_not_hang_and_creates_env(in_tmp, monkeypatch):
    """The loop-ready failure mode: no stdin, no flags -> completes, no hang."""
    monkeypatch.setattr(init_mod, "_validate_xai", lambda _model="": ("missing", ""))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "missing")
    # CliRunner provides a non-TTY stdin; with no input the wizard must not block.
    result = runner.invoke(app, ["init"], input="")
    assert result.exit_code == 1  # not ready (no key, no browser)
    assert (in_tmp / ".env").exists()


def test_cloud_ready_path(in_tmp, monkeypatch):
    monkeypatch.setattr(init_mod, "_validate_xai", lambda model="": ("ok", model))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")
    result = runner.invoke(app, ["init", "--yes"])
    assert result.exit_code == 0, result.output
    assert "ready" in result.output.lower()
    assert "distill --cost-mode paid-ok papers" in result.output
    assert "Analysis route:" in result.output
    compact = " ".join(result.output.split())
    assert "distill provider list" in compact
    assert "distill provider set gemini gemini-3.6-flash" in compact


def test_cloud_setup_blocks_conflicting_shell_provider(in_tmp, monkeypatch):
    monkeypatch.setenv("DISTILL_PROVIDER", "ollama")

    def forbidden_validation(_model=""):
        pytest.fail("conflicting shell routing must be resolved before a live key probe")

    monkeypatch.setattr(init_mod, "_validate_xai", forbidden_validation)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "cloud", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["ready"] is False
    assert payload["data"]["xai_key"] == "not-checked"
    assert "shell-level DISTILL_PROVIDER" in payload["data"]["blocking"][0]
    assert "DISTILL_PROVIDER=xai" in (in_tmp / ".env").read_text(encoding="utf-8")


def test_cloud_setup_blocks_stale_local_model_override(in_tmp, monkeypatch):
    (in_tmp / ".env").write_text(
        "DISTILL_PROVIDER=ollama\nDISTILL_MODEL=qwen3.5:27b\n",
        encoding="utf-8",
    )

    def forbidden_validation(_model=""):
        pytest.fail("incompatible model routing must be resolved before a live key probe")

    monkeypatch.setattr(init_mod, "_validate_xai", forbidden_validation)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "cloud", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["ready"] is False
    assert "not an xAI text model" in payload["data"]["blocking"][0]
    assert "DISTILL_PROVIDER=xai" in (in_tmp / ".env").read_text(encoding="utf-8")


def test_cloud_setup_validates_exact_resolved_xai_model(in_tmp, monkeypatch):
    (in_tmp / ".env").write_text(
        "DISTILL_PROVIDER=xai\nDISTILL_MODEL=grok-does-not-exist\n",
        encoding="utf-8",
    )
    validated: list[str] = []

    def reject_unknown_model(model: str):
        validated.append(model)
        return ("unknown", "model not found")

    monkeypatch.setattr(init_mod, "_validate_xai", reject_unknown_model)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "cloud", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert validated == ["grok-does-not-exist"]
    assert payload["data"]["ready"] is False
    assert payload["data"]["xai_key"] == "unknown"


def test_cloud_policy_skip_reports_actionable_blocker(in_tmp, monkeypatch):
    monkeypatch.setattr(
        init_mod,
        "_validate_xai",
        lambda _model="": ("skipped", "Route blocked by no-metered cost policy"),
    )
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["xai_key"] == "skipped"
    assert "DISTILL_COST_MODE=no-metered" in payload["data"]["blocking"][0]
    assert "valid XAI_API_KEY" not in payload["data"]["blocking"][0]


def test_json_verdict(in_tmp, monkeypatch):
    monkeypatch.setattr(init_mod, "_validate_xai", lambda model="": ("ok", model))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")
    result = runner.invoke(app, ["--json", "init", "--yes"])
    env = json.loads(result.stdout)
    assert env["status"] == "ok"
    assert env["data"]["ready"] is True
    assert env["data"]["provider"] == "cloud"
    assert env["data"]["xai_key"] == "ok"
    assert env["data"]["next"].startswith("distill --cost-mode paid-ok papers ")
    assert env["data"]["analysis_provider"] == "xai"
    assert env["data"]["analysis_model"] == "grok-4.3"


def test_existing_env_not_clobbered_by_command(in_tmp, monkeypatch):
    (in_tmp / ".env").write_text("XAI_API_KEY=keepme\n", encoding="utf-8")
    monkeypatch.setattr(init_mod, "_validate_xai", lambda model="": ("ok", model))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")
    runner.invoke(app, ["init", "--yes"])
    assert "keepme" in (in_tmp / ".env").read_text(encoding="utf-8")


def test_invalid_env_type_is_clean_configuration_error(in_tmp):
    (in_tmp / ".env").mkdir()

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == 3
    assert "Environment configuration failed" in result.output
    assert "Traceback" not in result.output


def test_env_lock_timeout_is_json_runtime_error(in_tmp, monkeypatch):
    def time_out(_path, *, force=False):
        raise TimeoutError("timed out waiting for the env lock")

    monkeypatch.setattr(init_mod, "create_env_file", time_out)

    result = runner.invoke(app, ["--json", "init", "--yes"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["data"] == {
        "reason": "env_file_error",
        "env_file": str(in_tmp / ".env"),
    }
    assert "timed out waiting for the env lock" in payload["error"]
    assert "Traceback" not in result.output


def test_local_provider_path(in_tmp, monkeypatch):
    monkeypatch.setattr(
        init_mod,
        "_local_model_inventory",
        lambda prov: ("running", ["qwen3.5:27b"]),
    )
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")
    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    env = json.loads(result.stdout)
    assert env["data"]["provider"] == "local"
    assert env["data"]["ready"] is True
    assert env["data"]["local_model"] == "qwen3.5:27b"
    assert env["data"]["local_model_ready"] is True
    assert env["data"]["local_models"] == ["qwen3.5:27b"]
    assert env["data"]["next"].startswith("distill --cost-mode no-metered papers ")
    assert env["data"]["analysis_provider"] == "ollama"
    assert env["data"]["analysis_model"] == "qwen3.5:27b"
    env_text = (in_tmp / ".env").read_text(encoding="utf-8")
    assert "DISTILL_PROVIDER=ollama" in env_text
    assert "DISTILL_MODEL=qwen3.5:27b" in env_text


def test_local_setup_blocks_conflicting_shell_provider_before_probe(in_tmp, monkeypatch):
    monkeypatch.setenv("DISTILL_PROVIDER", "xai")

    def forbidden_inventory(provider):
        pytest.fail("conflicting shell routing must be resolved before a local probe")

    monkeypatch.setattr(init_mod, "_local_model_inventory", forbidden_inventory)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["ready"] is False
    assert payload["data"]["local_reachable"] is False
    assert "shell-level DISTILL_PROVIDER" in payload["data"]["blocking"][0]
    assert "DISTILL_PROVIDER=ollama" in (in_tmp / ".env").read_text(encoding="utf-8")


def test_interactive_cloud_path_saves_entered_key(in_tmp, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    responses = iter(["cloud", "xai-entered"])
    prompt_messages = []

    def prompt(message, *, default, non_tty_default):
        prompt_messages.append(message)
        assert default in {"cloud", ""}
        assert non_tty_default in {"cloud", ""}
        return next(responses)

    monkeypatch.setattr(init_mod, "tty_prompt", prompt)
    monkeypatch.setattr(init_mod, "_validate_xai", lambda model="": ("ok", model))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    assert len(prompt_messages) == 2
    assert "Saved" in result.output
    assert "XAI_API_KEY=xai-entered" in (in_tmp / ".env").read_text(encoding="utf-8")


def test_interactive_cloud_validation_uses_newly_saved_key(in_tmp, monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    (in_tmp / ".env").write_text("XAI_API_KEY=\n", encoding="utf-8")
    responses = iter(["cloud", "replacement-key"])
    monkeypatch.setattr(
        init_mod,
        "tty_prompt",
        lambda *_args, **_kwargs: next(responses),
    )

    def validate(model: str):
        assert os.environ["XAI_API_KEY"] == "replacement-key"
        return ("ok", model)

    monkeypatch.setattr(init_mod, "_validate_xai", validate)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0, result.output
    assert "XAI_API_KEY=replacement-key" in (in_tmp / ".env").read_text(encoding="utf-8")


def test_cloud_setup_blocks_conflicting_shell_key(in_tmp, monkeypatch):
    (in_tmp / ".env").write_text("XAI_API_KEY=saved-key\n", encoding="utf-8")
    monkeypatch.setenv("XAI_API_KEY", "shell-key")

    def forbidden_validation(_model=""):
        pytest.fail("conflicting shell key must be resolved before a live key probe")

    monkeypatch.setattr(init_mod, "_validate_xai", forbidden_validation)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "cloud", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["xai_key"] == "not-checked"
    assert "shell-level XAI_API_KEY" in payload["data"]["blocking"][0]


def test_local_non_json_path_sets_default_and_renders_status(in_tmp, monkeypatch):
    def inventory(provider):
        assert provider == "ollama"
        return ("running", ["qwen3.5:27b"])

    monkeypatch.setattr(init_mod, "_local_provider", lambda: "")
    monkeypatch.setattr(init_mod, "_local_model_inventory", inventory)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["init", "--provider", "local", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Set" in result.output
    assert "ollama: running" in result.output
    assert "qwen3.5:27b (loaded)" in result.output
    env_text = (in_tmp / ".env").read_text(encoding="utf-8")
    assert "DISTILL_PROVIDER=ollama" in env_text
    assert "DISTILL_MODEL=qwen3.5:27b" in env_text


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
    def unavailable(received_provider):
        assert received_provider == provider
        return ("unavailable", [])

    monkeypatch.setattr(init_mod, "_local_provider", lambda: provider)
    monkeypatch.setattr(init_mod, "_local_model_inventory", unavailable)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["local_reachable"] is False
    assert payload["data"]["local_model_ready"] is False
    assert payload["data"]["blocking"] == [expected_blocker]


def test_local_model_mismatch_reports_exact_ollama_recovery(in_tmp, monkeypatch):
    monkeypatch.setattr(
        init_mod,
        "_local_model_inventory",
        lambda provider: ("running", ["another-model"]),
    )
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["local_reachable"] is True
    assert payload["data"]["local_model"] == "qwen3.5:27b"
    assert payload["data"]["local_model_ready"] is False
    assert payload["data"]["local_models"] == ["another-model"]
    assert payload["data"]["blocking"] == [
        "Configured model 'qwen3.5:27b' is not installed in Ollama. "
        "Run `ollama pull qwen3.5:27b`, then re-run `distill init`."
    ]


def test_local_existing_model_is_preserved_and_verified(in_tmp, monkeypatch):
    (in_tmp / ".env").write_text(
        "DISTILL_PROVIDER=ollama\nDISTILL_MODEL=custom-model\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        init_mod,
        "_local_model_inventory",
        lambda provider: ("running", ["custom-model"]),
    )
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0, result.output
    assert payload["data"]["local_model"] == "custom-model"
    assert payload["data"]["local_model_ready"] is True
    assert (in_tmp / ".env").read_text(encoding="utf-8") == (
        "DISTILL_PROVIDER=ollama\nDISTILL_MODEL=custom-model\n"
    )


def test_force_local_setup_discards_values_loaded_from_replaced_env(in_tmp, monkeypatch):
    (in_tmp / ".env").write_text(
        "DISTILL_PROVIDER=ollama\n"
        "DISTILL_MODEL=stale-model\n"
        "OLLAMA_BASE_URL=https://hosted.example/v1\n",
        encoding="utf-8",
    )

    def inventory(provider):
        assert provider == "ollama"
        assert "OLLAMA_BASE_URL" not in os.environ
        return ("running", ["qwen3.5:27b"])

    monkeypatch.setattr(init_mod, "_local_model_inventory", inventory)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(
        app,
        [
            "--json",
            "--cost-mode",
            "no-metered",
            "init",
            "--provider",
            "local",
            "--yes",
            "--force",
            "--no-browser",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0, result.output
    assert payload["data"]["local_model"] == "qwen3.5:27b"
    assert payload["data"]["local_model_ready"] is True
    env_text = (in_tmp / ".env").read_text(encoding="utf-8")
    assert "DISTILL_MODEL=stale-model" not in env_text
    assert "hosted.example" not in env_text


def test_local_workload_models_are_preserved_without_global_override(in_tmp, monkeypatch):
    original = (
        "DISTILL_PROVIDER=ollama\n"
        "DISTILL_ANALYSIS_MODEL=analysis-model\n"
        "DISTILL_RERANK_MODEL=rerank-model\n"
    )
    (in_tmp / ".env").write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        init_mod,
        "_local_model_inventory",
        lambda provider: ("running", ["analysis-model", "rerank-model"]),
    )
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0, result.output
    assert payload["data"]["local_model"] == "analysis-model"
    assert payload["data"]["local_model_ready"] is True
    assert (in_tmp / ".env").read_text(encoding="utf-8") == original
    assert "DISTILL_MODEL=" not in original


def test_lmstudio_requires_explicit_loaded_model(in_tmp, monkeypatch):
    (in_tmp / ".env").write_text("DISTILL_PROVIDER=lmstudio\n", encoding="utf-8")
    monkeypatch.setattr(
        init_mod,
        "_local_model_inventory",
        lambda provider: ("running", ["loaded-model"]),
    )
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(app, ["--json", "init", "--provider", "local", "--yes"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["local_models"] == ["loaded-model"]
    assert payload["data"]["blocking"] == [
        "Set DISTILL_MODEL or DISTILL_ANALYSIS_MODEL to an exact loaded lmstudio "
        "model id, for example 'loaded-model', then re-run `distill init`."
    ]


def test_no_metered_remote_local_init_blocks_before_inventory(in_tmp, monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://hosted.example/v1")

    def inventory(provider):
        pytest.fail("blocked remote topology must not be probed")

    monkeypatch.setattr(init_mod, "_local_model_inventory", inventory)
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "installed")

    result = runner.invoke(
        app,
        ["--json", "--cost-mode", "no-metered", "init", "--provider", "local", "--yes"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["data"]["local_reachable"] is False
    assert payload["data"]["local_model_ready"] is False
    assert "non-loopback" in payload["data"]["blocking"][0]
    env_lines = (in_tmp / ".env").read_text(encoding="utf-8").splitlines()
    assert "DISTILL_MODEL=qwen3.5:27b" not in env_lines


@pytest.mark.parametrize(
    ("install_succeeds", "expected_exit"),
    [(True, 0), (False, 1)],
)
def test_yes_installs_missing_browser(in_tmp, monkeypatch, install_succeeds, expected_exit):
    monkeypatch.setattr(init_mod, "_validate_xai", lambda model="": ("ok", model))
    monkeypatch.setattr(init_mod, "chromium_status", lambda: "missing")
    monkeypatch.setattr(init_mod, "_install_chromium", lambda: install_succeeds)

    result = runner.invoke(app, ["init", "--yes"])

    assert result.exit_code == expected_exit
    assert "Installing Chromium" in result.output
    expected_status = "installed" if install_succeeds else "missing"
    assert f"Browser: {expected_status}" in result.output
