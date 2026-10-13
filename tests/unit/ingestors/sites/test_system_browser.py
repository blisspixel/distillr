"""System Chromium selection does not start a second Playwright driver."""

from __future__ import annotations

import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from distill.ingestors.sites import system_browser as browser_mod


@pytest.fixture(autouse=True)
def _reset_bundled_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_mod, "_bundled_missing", None)
    monkeypatch.delenv("DISTILL_BROWSER_EXECUTABLE", raising=False)


def test_playwright_os_support_matches_debian_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_mod.sys, "platform", "linux")
    assert browser_mod.playwright_os_supported('ID=ubuntu\nID_LIKE="debian"\n') is True
    assert browser_mod.playwright_os_supported("ID=arch\n") is False
    assert browser_mod.playwright_os_supported("ID=pop\nID_LIKE=ubuntu debian\n") is True
    assert browser_mod.playwright_os_supported("") is True
    monkeypatch.setattr(browser_mod.sys, "platform", "darwin")
    assert browser_mod.playwright_os_supported("ID=arch\n") is True


def test_candidate_prefers_explicit_file_then_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "chrome"
    explicit.write_text("", encoding="utf-8")
    monkeypatch.setenv("DISTILL_BROWSER_EXECUTABLE", str(explicit))
    assert browser_mod.candidate_browser_path() == str(explicit)

    monkeypatch.setenv("DISTILL_BROWSER_EXECUTABLE", str(tmp_path / "missing"))
    monkeypatch.setattr(browser_mod.shutil, "which", lambda name: None)
    assert browser_mod.candidate_browser_path() is None

    found = tmp_path / "chromium"
    found.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        browser_mod.shutil,
        "which",
        lambda name: str(found) if name == "chromium" else None,
    )
    assert browser_mod.candidate_browser_path() == str(found)


def test_validate_browser_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "chromium"
    binary.write_text("", encoding="utf-8")
    calls: list[list[str]] = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        assert kwargs["timeout"] == 20
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(browser_mod.subprocess, "run", run)
    assert browser_mod.validate_browser_executable(str(binary)) is True
    assert calls[0][:4] == [str(binary), "--headless", "--disable-gpu", "--dump-dom"]
    assert browser_mod.validate_browser_executable("") is False
    assert browser_mod.validate_browser_executable(str(tmp_path / "absent")) is False

    monkeypatch.setattr(
        browser_mod.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )
    assert browser_mod.validate_browser_executable(str(binary)) is False
    monkeypatch.setattr(
        browser_mod.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired([], 20)),
    )
    assert browser_mod.validate_browser_executable(str(binary)) is False


def test_validated_system_browser_requires_a_successful_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "chromium"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(browser_mod, "candidate_browser_path", lambda: str(binary))
    monkeypatch.setattr(browser_mod, "validate_browser_executable", lambda path: True)
    assert browser_mod.validated_system_browser() == str(binary)
    monkeypatch.setattr(browser_mod, "validate_browser_executable", lambda path: False)
    assert browser_mod.validated_system_browser() is None
    monkeypatch.setattr(browser_mod, "candidate_browser_path", lambda: None)
    assert browser_mod.validated_system_browser() is None


def test_bundled_browser_missing_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def present():
        calls.append("present")
        return nullcontext(
            SimpleNamespace(chromium=SimpleNamespace(executable_path=sys.executable))
        )

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=present),
    )
    assert browser_mod.bundled_browser_missing() is False
    assert browser_mod.bundled_browser_missing() is False
    assert calls == ["present"]

    monkeypatch.setattr(browser_mod, "_bundled_missing", None)

    def absent():
        return nullcontext(SimpleNamespace(chromium=SimpleNamespace(executable_path="/no/browser")))

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=absent),
    )
    assert browser_mod.bundled_browser_missing() is True

    monkeypatch.setattr(browser_mod, "_bundled_missing", None)

    def broken():
        raise RuntimeError("driver failed")

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=broken),
    )
    assert browser_mod.bundled_browser_missing() is True


def test_launch_kwargs_prefer_explicit_then_bundled_then_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "explicit"
    bundled = tmp_path / "bundled"
    system = tmp_path / "system"
    for path in (explicit, bundled, system):
        path.write_text("", encoding="utf-8")
    monkeypatch.setenv("DISTILL_BROWSER_EXECUTABLE", str(explicit))
    assert browser_mod.chromium_launch_kwargs(bundled_executable=str(bundled)) == {
        "executable_path": str(explicit)
    }
    monkeypatch.delenv("DISTILL_BROWSER_EXECUTABLE", raising=False)
    assert browser_mod.chromium_launch_kwargs(bundled_executable=str(bundled)) == {}
    monkeypatch.setattr(browser_mod, "candidate_browser_path", lambda: str(system))
    assert browser_mod.chromium_launch_kwargs(bundled_executable=str(tmp_path / "missing")) == {
        "executable_path": str(system)
    }
    monkeypatch.setattr(browser_mod, "candidate_browser_path", lambda: None)
    assert browser_mod.chromium_launch_kwargs(bundled_executable=None) == {}


def test_browser_can_launch_checks_explicit_bundled_and_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "chromium"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setenv("DISTILL_BROWSER_EXECUTABLE", str(binary))
    monkeypatch.setattr(browser_mod, "bundled_browser_missing", lambda: True)
    assert browser_mod.browser_can_launch() is True

    monkeypatch.delenv("DISTILL_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.setattr(browser_mod, "bundled_browser_missing", lambda: False)
    assert browser_mod.browser_can_launch() is True

    monkeypatch.setattr(browser_mod, "bundled_browser_missing", lambda: True)
    monkeypatch.setattr(browser_mod, "candidate_browser_path", lambda: str(binary))
    assert browser_mod.browser_can_launch() is True
    monkeypatch.setattr(browser_mod, "candidate_browser_path", lambda: None)
    assert browser_mod.browser_can_launch() is False
