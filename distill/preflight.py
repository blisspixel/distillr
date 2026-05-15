"""Lightweight version-age checks for fragile dependencies.

yt-dlp ships a new release roughly weekly to keep up with YouTube changes.
A user with a stale install will see opaque extractor errors. Preflight checks
warn (never block) when yt-dlp is older than YTDLP_STALE_DAYS, with a cached
result so the version parse runs at most once per day.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

YTDLP_STALE_DAYS = 14
PREFLIGHT_CACHE_NAME = ".preflight.json"
CACHE_TTL_HOURS = 24


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


def _cache_path(library_dir: Path | None) -> Path | None:
    if library_dir is None:
        return None
    return library_dir / PREFLIGHT_CACHE_NAME


def _read_cache(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(path: Path | None, data: dict) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def _is_cache_fresh(entry: dict, now: datetime) -> bool:
    ts = entry.get("checked_at")
    if not isinstance(ts, str):
        return False
    try:
        checked = datetime.fromisoformat(ts)
    except ValueError:
        return False
    return (now - checked).total_seconds() < CACHE_TTL_HOURS * 3600


def preflight_ytdlp(console, library_dir: Path | None = None) -> None:
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

    if (
        _is_cache_fresh(entry, now)
        and entry.get("version") == version
        and entry.get("warned_age_days") is not None
    ):
        warned_age = entry["warned_age_days"]
        if isinstance(warned_age, int) and warned_age > YTDLP_STALE_DAYS:
            _emit_stale_warning(console, version, warned_age)
        return

    age = ytdlp_age_days(now=now)
    cache["yt-dlp"] = {
        "version": version,
        "checked_at": now.isoformat(timespec="seconds"),
        "warned_age_days": age,
    }
    _write_cache(cache_file, cache)

    if age is not None and age > YTDLP_STALE_DAYS:
        _emit_stale_warning(console, version, age)


def _emit_stale_warning(console, version: str | None, age: int) -> None:
    label = f"v{version}" if version else "unknown"
    # ASCII marker (`!`) instead of U+26A0 so even legacy Windows consoles that
    # somehow bypass the UTF-8 stdio bootstrap don't crash on this banner.
    with contextlib.suppress(Exception):
        console.print(
            f"[yellow]! yt-dlp {label} is {age} days old. "
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
    safe_cwd = str(Path(sys.executable).resolve().parent)
    safe_env = dict(os.environ)
    safe_env.pop("PYTHONPATH", None)
    safe_env.pop("PYTHONHOME", None)
    safe_env["PYTHONSAFEPATH"] = "1"
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
