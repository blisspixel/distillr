# pyright: strict
"""System Chromium selection when Playwright's browser is not installed.

Only the executable changes. Launch flags and the pinned browser network stay
with the existing Playwright calls.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

__all__ = [
    "browser_can_launch",
    "bundled_browser_missing",
    "candidate_browser_path",
    "chromium_launch_kwargs",
    "playwright_os_supported",
    "validate_browser_executable",
    "validated_system_browser",
]

_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
    "google-chrome",
    "brave-browser",
    "brave",
)
_SUPPORTED_OS_IDS = frozenset(
    {
        "debian",
        "elementary",
        "linuxmint",
        "neon",
        "pop",
        "raspbian",
        "ubuntu",
        "zorin",
    }
)
_VALIDATE_TIMEOUT_SECONDS = 20
_bundled_missing: bool | None = None


class ChromiumLaunchOptions(TypedDict, total=False):
    """Optional Playwright launch fields this module is allowed to set."""

    executable_path: str


def _read_os_release() -> str:
    try:
        return Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _release_ids(text: str) -> set[str]:
    found: set[str] = set()
    for line in text.splitlines():
        if line.startswith("ID=") or line.startswith("ID_LIKE="):
            raw = line.split("=", 1)[1].strip().strip("\"'")
            found.update(part.strip().lower() for part in raw.split() if part.strip())
    return found


def playwright_os_supported(release_text: str | None = None) -> bool:
    """Whether Playwright publishes a browser build for this OS.

    Non-Linux and an empty or missing ID are treated as supported so a download
    is still attempted when we cannot tell. Arch and other non-Debian IDs are not.
    """

    if sys.platform != "linux":
        return True
    text = _read_os_release() if release_text is None else release_text
    ids = _release_ids(text)
    if not ids:
        return True
    return bool(ids & _SUPPORTED_OS_IDS)


def candidate_browser_path() -> str | None:
    """Explicit executable or the first candidate on PATH. Does not launch it."""

    explicit = os.environ.get("DISTILL_BROWSER_EXECUTABLE", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    for name in _CANDIDATES:
        found = shutil.which(name)
        if found and Path(found).is_file():
            return found
    return None


def validate_browser_executable(path: str) -> bool:
    """True when *path* can dump a blank page headlessly."""

    if not path or not Path(path).is_file():
        return False
    try:
        result = subprocess.run(
            [path, "--headless", "--disable-gpu", "--dump-dom", "about:blank"],
            check=False,
            capture_output=True,
            timeout=_VALIDATE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def validated_system_browser() -> str | None:
    """A system browser that launched, or None."""

    path = candidate_browser_path()
    if path and validate_browser_executable(path):
        return path
    return None


def bundled_browser_missing() -> bool:
    """Whether Playwright's downloaded Chromium executable is absent.

    Cached for the process so a seed-only crawl does not start the driver twice.
    """

    global _bundled_missing
    if _bundled_missing is not None:
        return _bundled_missing
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            exe = playwright.chromium.executable_path
            _bundled_missing = not bool(exe) or not Path(exe).is_file()
    except Exception:
        _bundled_missing = True
    return _bundled_missing


def chromium_launch_kwargs(*, bundled_executable: str | None = None) -> ChromiumLaunchOptions:
    """``executable_path`` when a system or explicit browser should be used.

    An explicit ``DISTILL_BROWSER_EXECUTABLE`` wins even if the bundled browser
    exists. Otherwise the bundled executable is preferred when it is present.
    Call this from inside an open Playwright session and pass that session's
    ``executable_path`` so this function does not start a second driver.
    """

    explicit = os.environ.get("DISTILL_BROWSER_EXECUTABLE", "").strip()
    if explicit and Path(explicit).is_file():
        return {"executable_path": explicit}
    if bundled_executable and Path(bundled_executable).is_file():
        return {}
    found = candidate_browser_path()
    if found:
        return {"executable_path": found}
    return {}


def browser_can_launch() -> bool:
    """True when a bundled, explicit, or on-PATH browser executable exists."""

    explicit = os.environ.get("DISTILL_BROWSER_EXECUTABLE", "").strip()
    if explicit and Path(explicit).is_file():
        return True
    if not bundled_browser_missing():
        return True
    return candidate_browser_path() is not None
