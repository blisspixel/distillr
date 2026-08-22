"""Security contracts for child-process executable and environment boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import distill.process_security as process_security
from distill.process_security import (
    distill_child_env,
    package_install_context,
    resolve_executable,
    sanitized_package_env,
    unsafe_package_overrides,
)


def _make_executable(path: Path) -> None:
    path.write_text("executable", encoding="utf-8")
    path.chmod(0o755)


def test_resolve_executable_ignores_current_directory_decoy(tmp_path, monkeypatch):
    working = tmp_path / "working"
    trusted = tmp_path / "trusted"
    working.mkdir()
    trusted.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    decoy = working / f"media-tool{suffix}"
    expected = trusted / f"media-tool{suffix}"
    _make_executable(decoy)
    _make_executable(expected)
    monkeypatch.chdir(working)

    resolved = resolve_executable(
        "media-tool",
        env={"PATH": os.pathsep.join((str(working), str(trusted))), "PATHEXT": ".EXE"},
    )

    assert resolved == str(expected.resolve())


def test_resolve_executable_ignores_relative_path_entries(tmp_path, monkeypatch):
    working = tmp_path / "working"
    trusted = tmp_path / "trusted"
    relative = working / "relative-bin"
    working.mkdir()
    trusted.mkdir()
    relative.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    _make_executable(relative / f"worker{suffix}")
    expected = trusted / f"worker{suffix}"
    _make_executable(expected)
    monkeypatch.chdir(working)

    resolved = resolve_executable(
        "worker",
        env={"PATH": os.pathsep.join(("relative-bin", str(trusted))), "PATHEXT": ".EXE"},
    )

    assert resolved == str(expected.resolve())


def test_resolve_executable_accepts_an_explicit_absolute_file(tmp_path):
    executable = tmp_path / "absolute-tool.exe"
    _make_executable(executable)

    assert resolve_executable(str(executable)) == str(executable.resolve())
    assert resolve_executable(str(tmp_path / "missing.exe")) is None


def test_resolve_executable_handles_explicit_suffix_and_quoted_path(tmp_path, monkeypatch):
    working = tmp_path / "working"
    trusted = tmp_path / "trusted"
    working.mkdir()
    trusted.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    expected = trusted / f"worker{suffix}"
    _make_executable(expected)
    monkeypatch.chdir(working)

    resolved = resolve_executable(
        expected.name,
        env={"PATH": f'"{trusted}"', "PATHEXT": "EXE"},
    )

    assert resolved == str(expected.resolve())


def test_windows_candidate_names_allow_only_executable_image_types():
    candidates = process_security._windows_candidate_names(
        "worker",
        os.pathsep.join(("exe", ".BAT", ".COM", ".EXE", r".\..\cmd.exe")),
    )

    assert candidates == ("worker.EXE", "worker.COM")


@pytest.mark.skipif(os.name != "nt", reason="PATHEXT is Windows-specific")
def test_resolve_executable_rejects_traversing_pathext(monkeypatch, tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)

    resolved = resolve_executable(
        "definitely-not-a-real-tool",
        env={
            "PATH": r"C:\Windows\System32\WindowsPowerShell\v1.0",
            "PATHEXT": r".\..\..\..\cmd.exe",
        },
    )

    assert resolved is None


def test_resolve_executable_rejects_empty_nested_and_missing_names(tmp_path, monkeypatch):
    working = tmp_path / "working"
    trusted = tmp_path / "trusted"
    working.mkdir()
    trusted.mkdir()
    monkeypatch.chdir(working)

    assert resolve_executable("") is None
    assert resolve_executable("nested/tool") is None
    assert resolve_executable("missing", env={"PATH": "", "PATHEXT": ".EXE"}) is None
    assert (
        resolve_executable(
            "missing",
            env={"PATH": str(trusted), "PATHEXT": os.pathsep.join(("EXE", ".COM"))},
        )
        is None
    )


def test_resolve_executable_rejects_directory_with_executable_name(tmp_path, monkeypatch):
    working = tmp_path / "working"
    trusted = tmp_path / "trusted"
    working.mkdir()
    trusted.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    (trusted / f"worker{suffix}").mkdir()
    monkeypatch.chdir(working)

    assert (
        resolve_executable(
            f"worker{suffix}",
            env={"PATH": str(trusted), "PATHEXT": ".EXE"},
        )
        is None
    )


def test_resolve_executable_fails_closed_when_working_directory_is_unavailable(
    monkeypatch,
):
    def unavailable(_cls):
        raise OSError("cwd unavailable")

    monkeypatch.setattr(process_security.Path, "cwd", classmethod(unavailable))

    assert resolve_executable("worker", env={"PATH": "C:\\trusted", "PATHEXT": ".EXE"}) is None


def test_search_directory_fails_closed_when_resolution_raises(tmp_path, monkeypatch):
    working = tmp_path / "working"
    unavailable = tmp_path / "unavailable"
    working.mkdir()
    unavailable.mkdir()
    real_resolve = process_security.Path.resolve

    def fail_selected(path, *, strict=False):
        if path == unavailable:
            raise OSError("directory unavailable")
        return real_resolve(path, strict=strict)

    monkeypatch.setattr(process_security.Path, "resolve", fail_selected)

    assert process_security._search_directory(str(unavailable), working) is None


def test_usable_executable_requires_execute_permission_off_windows(tmp_path, monkeypatch):
    executable = tmp_path / "worker"
    _make_executable(executable)
    monkeypatch.setattr(process_security.os, "name", "posix")
    monkeypatch.setattr(process_security.os, "access", lambda _path, _mode: False)

    assert process_security._usable_executable(executable) is None


def test_sanitized_package_env_strips_provider_credentials_case_insensitively():
    env = sanitized_package_env(
        {
            "PATH": "trusted-path",
            "PYTHONPATH": "untrusted-path",
            "PYTHONHOME": "untrusted-home",
            "PYTHONWARNINGS": "ignore::startup_hook.Trigger",
            "PYTHONUSERBASE": "untrusted-userbase",
            "PYTHONINSPECT": "1",
            "XAI_API_KEY": "xai-secret",
            "openai_api_key": "openai-secret",
            "GEMINI_API_KEY": "gemini-secret",
            "GOOGLE_API_KEY": "google-secret",
            "ANTHROPIC_API_KEY": "anthropic-secret",
            "GITHUB_TOKEN": "github-secret",
            "DISTILL_WORKER_CLAIM_TOKEN": "claim-secret",
            "SERVICE_PASSWORD": "password-secret",
            "PLAYWRIGHT_NODEJS_PATH": "untrusted-node",
            "PLAYWRIGHT_BROWSERS_PATH": "untrusted-browser",
            "node_options": "--require untrusted.js",
            "NODE_PATH": "untrusted-modules",
            "ORDINARY_SETTING": "kept",
        }
    )

    assert env["PATH"] == "trusted-path"
    assert env["ORDINARY_SETTING"] == "kept"
    assert env["PYTHONSAFEPATH"] == "1"
    assert env["PYTHONNOUSERSITE"] == "1"
    assert not {
        "pythonpath",
        "pythonhome",
        "pythonwarnings",
        "pythonuserbase",
        "pythoninspect",
        "xai_api_key",
        "openai_api_key",
        "gemini_api_key",
        "google_api_key",
        "anthropic_api_key",
        "github_token",
        "distill_worker_claim_token",
        "service_password",
        "playwright_nodejs_path",
        "playwright_browsers_path",
        "node_options",
        "node_path",
    }.intersection(key.casefold() for key in env)


def test_unsafe_package_overrides_reports_only_nonempty_execution_overrides() -> None:
    assert unsafe_package_overrides(
        {
            "Path": "kept",
            "playwright_nodejs_path": "replacement",
            "playwright_browsers_path": "browser-replacement",
            "NODE_OPTIONS": "--require hook.js",
            "NODE_PATH": "",
        }
    ) == ("NODE_OPTIONS", "PLAYWRIGHT_BROWSERS_PATH", "PLAYWRIGHT_NODEJS_PATH")


def test_sanitized_python_env_prevents_pythonwarnings_startup_import(tmp_path: Path) -> None:
    marker = tmp_path / "startup-imported.txt"
    hook = tmp_path / "startup_hook.py"
    hook.write_text(
        "\n".join(
            [
                f"with open({str(marker)!r}, 'w', encoding='utf-8') as marker_file:",
                "    marker_file.write('imported')",
                "class Trigger(Warning):",
                "    pass",
            ]
        ),
        encoding="utf-8",
    )
    command = [str(Path(sys.executable).resolve()), "-P", "-c", "pass"]
    controlled = sanitized_package_env()
    controlled["PYTHONPATH"] = str(tmp_path)
    unsafe = {**controlled, "PYTHONWARNINGS": "ignore::startup_hook.Trigger"}

    subprocess.run(command, env=unsafe, check=True, capture_output=True)
    assert marker.read_text(encoding="utf-8") == "imported"
    marker.unlink()

    safe = sanitized_package_env(unsafe)
    safe["PYTHONPATH"] = str(tmp_path)
    subprocess.run(command, env=safe, check=True, capture_output=True)
    assert not marker.exists()


def test_package_install_context_drops_index_overrides(monkeypatch):
    monkeypatch.setenv("PIP_INDEX_URL", "https://evil.example/simple")
    monkeypatch.setenv("UV_INDEX", "https://evil.example/simple")
    cwd, env = package_install_context()
    assert cwd
    assert "PIP_INDEX_URL" not in env
    assert "UV_INDEX" not in env
    assert env["PYTHONSAFEPATH"] == "1"


def test_distill_child_env_keeps_provider_keys_and_strips_loaders():
    env = distill_child_env(
        {
            "PATH": "trusted-path",
            "PYTHONPATH": "untrusted-path",
            "NODE_OPTIONS": "--require untrusted.js",
            "XAI_API_KEY": "xai-secret",
            "PIP_INDEX_URL": "https://evil.example/simple",
        },
        overlay={"DISTILL_TEST_RECEIPT": "receipt"},
    )

    assert env["XAI_API_KEY"] == "xai-secret"
    assert env["DISTILL_TEST_RECEIPT"] == "receipt"
    assert env["PATH"] == "trusted-path"
    assert "PYTHONPATH" not in env
    assert "NODE_OPTIONS" not in env


def test_distill_child_env_without_overlay_keeps_credentials():
    env = distill_child_env({"PATH": "trusted-path", "XAI_API_KEY": "xai-secret"})
    assert env["XAI_API_KEY"] == "xai-secret"
    assert env["PATH"] == "trusted-path"
