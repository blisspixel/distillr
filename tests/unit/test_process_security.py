"""Security contracts for child-process executable and environment boundaries."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import distill.process_security as process_security
from distill.process_security import resolve_executable, sanitized_package_env


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
            "XAI_API_KEY": "xai-secret",
            "openai_api_key": "openai-secret",
            "GEMINI_API_KEY": "gemini-secret",
            "GOOGLE_API_KEY": "google-secret",
            "ANTHROPIC_API_KEY": "anthropic-secret",
            "GITHUB_TOKEN": "github-secret",
            "ORDINARY_SETTING": "kept",
        }
    )

    assert env["PATH"] == "trusted-path"
    assert env["ORDINARY_SETTING"] == "kept"
    assert env["PYTHONSAFEPATH"] == "1"
    assert not {
        "pythonpath",
        "pythonhome",
        "xai_api_key",
        "openai_api_key",
        "gemini_api_key",
        "google_api_key",
        "anthropic_api_key",
        "github_token",
    }.intersection(key.casefold() for key in env)
