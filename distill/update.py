"""distillr self-update and update-availability checks.

Mirrors :mod:`distill.preflight`: a cached, non-blocking PyPI version check that
nudges the user when a newer distillr is published, plus the machinery behind
``distill update`` — which detects how distillr was installed (uv tool / pipx /
pip / source checkout) and runs the right upgrade for the user.

Network is touched at most once per day (cached), with a short timeout and
total failure-swallowing, so an offline or slow PyPI never degrades the CLI.
``DISTILL_NO_UPDATE_CHECK=1`` opts out of the availability check entirely.
"""

# pyright: strict

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from rich.console import Console

from distill.library.paths import atomic_write_text
from distill.process_security import package_install_context, resolve_executable

PACKAGE = "distillr"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"
UPDATE_CACHE_NAME = ".update_check.json"
CACHE_TTL_HOURS = 24
FETCH_TIMEOUT_S = 3.0

# Install methods distill can upgrade itself under.
METHOD_UV = "uv"
METHOD_PIPX = "pipx"
METHOD_PIP = "pip"
METHOD_SOURCE = "source"  # editable / git checkout — never auto-upgraded


def get_installed_version() -> str | None:
    """Installed distillr version from package metadata, or None if undetected."""
    for dist in (PACKAGE, "distill"):
        with contextlib.suppress(Exception):
            v = importlib.metadata.version(dist)
            if v:
                return v
    return None


def fetch_latest_version(timeout: float = FETCH_TIMEOUT_S) -> str | None:
    """Latest published distillr version from PyPI, or None on any failure.

    Deliberately swallows everything (offline, DNS, 5xx, malformed JSON): an
    update check must never raise into the CLI.
    """
    try:
        import requests

        resp = requests.get(PYPI_URL, timeout=timeout)
        resp.raise_for_status()
        version = resp.json()["info"]["version"]
        return version if isinstance(version, str) and version else None
    except Exception:
        return None


def latest_is_newer(current: str | None, latest: str | None) -> bool:
    """True when *latest* is a strictly newer release than *current*.

    Uses PEP 440 comparison; an unparseable version on either side is treated
    as "no newer version" rather than guessing.
    """
    if not current or not latest:
        return False
    try:
        from packaging.version import InvalidVersion, Version

        try:
            return Version(latest) > Version(current)
        except InvalidVersion:
            return False
    except Exception:
        return False


def _editable_install() -> bool:
    """Whether distillr is installed editable / from a source checkout."""
    with contextlib.suppress(Exception):
        dist = importlib.metadata.distribution(PACKAGE)
        raw = dist.read_text("direct_url.json")
        if raw:
            info = json.loads(raw)
            return bool(info.get("dir_info", {}).get("editable"))
    return False


def detect_install_method() -> str:
    """Best-effort detection of how distillr was installed.

    Editable checkouts are detected precisely (``direct_url.json``); uv vs pipx
    vs plain pip is inferred from the environment path, which is where each tool
    isolates its venvs. Defaults to plain pip when nothing more specific matches.
    """
    if _editable_install():
        return METHOD_SOURCE
    prefix = sys.prefix.replace("\\", "/").lower()
    if "/pipx/" in prefix or prefix.endswith("/pipx"):
        return METHOD_PIPX
    if "/uv/tools/" in prefix or "/uv/" in prefix:
        return METHOD_UV
    return METHOD_PIP


def upgrade_command(method: str) -> list[str] | None:
    """The argv that upgrades distillr for *method*, or None for source installs."""
    if method == METHOD_UV:
        return ["uv", "tool", "upgrade", PACKAGE]
    if method == METHOD_PIPX:
        return ["pipx", "upgrade", PACKAGE]
    if method == METHOD_PIP:
        return [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]
    return None  # source checkout


def _safe_subprocess_env() -> tuple[str, dict[str, str]]:
    """A trusted cwd + sanitized env for running package managers.

    Strips Python path-injection vars so a malicious ``pip.py`` in the user's
    cwd can't shadow the real module (the same hardening preflight uses).
    """
    return package_install_context()


def run_self_update(timeout: int = 300) -> tuple[bool, str, bool]:
    """Upgrade distillr in place using the detected install method.

    Returns ``(success, detail, was_noop)``. ``was_noop`` is True when the
    upgrade ran cleanly but the version didn't change (already latest). For a
    source checkout, returns ``(False, <guidance>, False)`` — distill won't
    git-pull someone's working tree.
    """
    method = detect_install_method()
    if method == METHOD_SOURCE:
        return (
            False,
            "Source/editable install: update with `git pull` then `uv sync` "
            "(or `pip install -e .`).",
            False,
        )
    cmd = upgrade_command(method)
    if cmd is None:  # pragma: no cover - guarded by the source branch above
        return False, f"No upgrade command for install method '{method}'.", False

    tool_name = cmd[0]
    if not Path(tool_name).is_absolute():
        executable = resolve_executable(tool_name)
        if executable is None:
            return False, f"`{tool_name}` not found on PATH; install it or upgrade manually.", False
        cmd[0] = executable

    old_version = get_installed_version()
    safe_cwd, safe_env = _safe_subprocess_env()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=safe_cwd,
            env=safe_env,
        )
    except FileNotFoundError:
        return False, f"`{tool_name}` not found on PATH; install it or upgrade manually.", False
    except subprocess.TimeoutExpired:
        return False, f"`{' '.join(cmd)}` timed out after {timeout}s.", False
    except Exception as exc:
        return False, str(exc), False

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "upgrade exited non-zero").strip()
        return False, detail[:500], False

    new_version = get_installed_version() or "unknown"
    was_noop = old_version is not None and new_version == old_version
    return True, new_version, was_noop


# ── Cached availability notice (the bare-`distill` nudge) ──────────────────────


def _cache_path(library_dir: Path | None) -> Path | None:
    if library_dir is None:
        return None
    return library_dir / ".distill" / UPDATE_CACHE_NAME


def _read_cache(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


def _write_cache(path: Path | None, data: dict[str, Any]) -> None:
    if path is None:
        return
    with contextlib.suppress(Exception):
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(data))


def _is_fresh(entry: dict[str, Any], now: datetime) -> bool:
    ts = entry.get("checked_at")
    if not isinstance(ts, str):
        return False
    try:
        checked = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (now - checked).total_seconds() < CACHE_TTL_HOURS * 3600


def latest_version_cached(library_dir: Path | None, now: datetime | None = None) -> str | None:
    """Latest PyPI version, hitting the network at most once per ``CACHE_TTL_HOURS``.

    A fresh cache entry is returned without any network call; otherwise PyPI is
    queried once and the result cached. Returns None when offline with no cache.
    """
    now = now or datetime.now()
    cache_file = _cache_path(library_dir)
    cache = _read_cache(cache_file)
    entry = cache.get(PACKAGE, {})
    if _is_fresh(entry, now):
        latest = entry.get("latest")
        return latest if isinstance(latest, str) else None
    latest = fetch_latest_version()
    cache[PACKAGE] = {"latest": latest, "checked_at": now.isoformat(timespec="seconds")}
    _write_cache(cache_file, cache)
    return latest


def check_for_update(console: Console, library_dir: Path | None = None) -> None:
    """Print a single non-blocking notice if a newer distillr is published.

    Cached (once-per-day network), failure-silent, and opt-out via
    ``DISTILL_NO_UPDATE_CHECK=1``. Safe to call on the bare-``distill`` path.
    """
    if os.environ.get("DISTILL_NO_UPDATE_CHECK"):
        return
    current = get_installed_version()
    if current is None or current == "dev":
        return  # a source/dev build has no meaningful "newer release"
    latest = latest_version_cached(library_dir)
    if latest_is_newer(current, latest):
        with contextlib.suppress(Exception):
            console.print(
                f"[yellow]! distillr {latest} is available (you have {current}). "
                f"Run [bold]distill update[/bold] to upgrade.[/yellow]"
            )
