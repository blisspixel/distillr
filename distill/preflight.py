"""Lightweight version-age checks for fragile dependencies.

yt-dlp ships frequently to keep up with YouTube changes, and a stale install
shows up as opaque extractor errors. Preflight warns (never blocks) when a
*newer release actually exists* -- not merely when the installed one is old.

Age alone was the original signal and it cried wolf: yt-dlp had not published in
45 days, so a perfectly current install was told to run an update that would do
nothing, every single command. A warning that fires on a healthy install is one
operators learn to ignore, which is precisely the wrong habit for the dependency
this project names as its most fragile.

Age is still consulted first, as a free local pre-filter: a recent install
cannot be behind, so the network is never touched in the common case. The PyPI
answer is cached for a day alongside the version parse.
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

from distill.process_security import package_install_context

YTDLP_STALE_DAYS = 14
PREFLIGHT_CACHE_NAME = ".preflight.json"
CACHE_TTL_HOURS = 24
YTDLP_PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
YTDLP_FETCH_TIMEOUT_S = 3.0


def get_ytdlp_version() -> str | None:
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:
        return None


def parse_ytdlp_release_date(version: str | None) -> datetime | None:
    """yt-dlp uses date-stamped versions like '2026.3.17'."""
    if not version:
        return None
    parts = version.split(".")
    if len(parts) < 3:
        return None
    try:
        year = int(parts[0])
        month = int(parts[1])
        day = int(parts[2].split("+")[0].split("-")[0])
        return datetime(year, month, day)
    except (ValueError, TypeError):
        return None


def ytdlp_age_days(now: datetime | None = None) -> int | None:
    release = parse_ytdlp_release_date(get_ytdlp_version())
    if release is None:
        return None
    return ((now or datetime.now()) - release).days


def fetch_latest_ytdlp_version(timeout: float = YTDLP_FETCH_TIMEOUT_S) -> str | None:
    """Latest published yt-dlp version from PyPI, or None on any failure.

    Deliberately swallows everything (offline, DNS, 5xx, malformed JSON): a
    freshness hint must never raise into a command, and must never delay one
    for long. Mirrors ``distill.update.fetch_latest_version``.
    """
    try:
        import requests

        response = requests.get(YTDLP_PYPI_URL, timeout=timeout)
        response.raise_for_status()
        version = response.json()["info"]["version"]
        return version if isinstance(version, str) and version else None
    except Exception:
        return None


def ytdlp_update_available(installed: str | None) -> bool | None:
    """True/False when PyPI could be reached, None when it could not.

    The tri-state matters: "no newer release" and "could not check" must not
    print the same thing, or the check quietly stops meaning anything offline.
    """
    latest = fetch_latest_ytdlp_version()
    if latest is None:
        return None
    from distill.update import latest_is_newer

    return latest_is_newer(installed, latest)


def _cache_path(library_dir: Path | None) -> Path | None:
    if library_dir is None:
        return None
    return library_dir / PREFLIGHT_CACHE_NAME


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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        return


def _is_cache_fresh(entry: dict[str, Any], now: datetime) -> bool:
    ts = entry.get("checked_at")
    if not isinstance(ts, str):
        return False
    try:
        checked = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (now - checked).total_seconds() < CACHE_TTL_HOURS * 3600


def preflight_ytdlp(console: Console, library_dir: Path | None = None) -> None:
    """Print a single non-blocking warning if yt-dlp is stale.

    Caches the result in ``library_dir/.preflight.json`` so the check only
    actually runs once per day. ``DISTILL_NO_PREFLIGHT=1`` opts out entirely.
    """
    if os.environ.get("DISTILL_NO_PREFLIGHT"):
        return

    now = datetime.now()
    cache_file = _cache_path(library_dir)
    cache = _read_cache(cache_file)
    entry = cache.get("yt-dlp", {})
    version = get_ytdlp_version()

    if _is_cache_fresh(entry, now) and entry.get("version") == version:
        cached_age = entry.get("warned_age_days")
        cached_newer = entry.get("update_available")
        if isinstance(cached_age, int):
            _warn_if_behind(console, version, cached_age, cached_newer)
        return

    age = ytdlp_age_days(now=now)
    # Only ask PyPI once the local age makes it plausible we are behind. A
    # recently released install cannot be, so the common case costs no network.
    update_available = (
        ytdlp_update_available(version) if age is not None and age > YTDLP_STALE_DAYS else False
    )
    cache["yt-dlp"] = {
        "version": version,
        "checked_at": now.isoformat(timespec="seconds"),
        "warned_age_days": age,
        "update_available": update_available,
    }
    _write_cache(cache_file, cache)

    if age is not None:
        _warn_if_behind(console, version, age, update_available)


def _warn_if_behind(
    console: Console,
    version: str | None,
    age: int,
    update_available: object,
) -> None:
    """Warn only when there is something to actually do about it."""
    if age <= YTDLP_STALE_DAYS:
        return
    if update_available is False:
        return  # old, but already the newest published release: nothing to do
    _emit_stale_warning(console, version, age, verified=update_available is True)


def _emit_stale_warning(
    console: Console,
    version: str | None,
    age: int,
    *,
    verified: bool,
) -> None:
    label = f"v{version}" if version else "unknown"
    reason = (
        "a newer release is available"
        if verified
        else f"{age} days old and PyPI could not be reached to confirm"
    )
    # ASCII marker (`!`) instead of U+26A0 so even legacy Windows consoles that
    # somehow bypass the UTF-8 stdio bootstrap don't crash on this banner.
    with contextlib.suppress(Exception):
        console.print(
            f"[yellow]! yt-dlp {label}: {reason}. "
            f"YouTube extractors may be stale; run "
            f"[bold]distill doctor --update[/bold] to refresh.[/yellow]"
        )


def update_ytdlp(timeout: int = 300) -> tuple[bool, str, bool]:
    """Run ``pip install --upgrade yt-dlp``.

    Returns ``(success, detail, was_noop)`` where ``was_noop`` is True when pip
    exited cleanly but the installed version did not change — i.e. the user
    already had the latest published release. Callers should report this case
    as "already at the latest release" rather than "upgraded".
    """
    old_version = get_ytdlp_version()
    # Run pip from a trusted cwd and strip Python path injection variables so
    # an attacker-controlled ``pip.py``/``pip/`` package in the user's current
    # directory cannot shadow the legitimate installed pip module via
    # ``python -m pip``'s module search path. ``PYTHONSAFEPATH`` is honored on
    # newer Python versions; the trusted cwd keeps this safe on older supported
    # versions too.
    safe_cwd, safe_env = package_install_context()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=safe_cwd,
            env=safe_env,
        )
    except subprocess.TimeoutExpired:
        return False, "pip upgrade timed out", False
    except Exception as exc:
        return False, str(exc), False

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "pip exited non-zero").strip()
        return False, detail[:500], False

    new_version = get_ytdlp_version() or "unknown"
    was_noop = old_version is not None and new_version == old_version
    return True, new_version, was_noop


def invalidate_preflight_cache(library_dir: Path | None) -> None:
    """Force the next preflight to re-check (call after an update)."""
    cache_file = _cache_path(library_dir)
    if cache_file is None or not cache_file.exists():
        return
    with contextlib.suppress(Exception):
        cache_file.unlink()
