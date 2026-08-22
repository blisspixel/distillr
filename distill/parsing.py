"""Small total parsers shared across external-input boundaries."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

__all__ = [
    "LENIENT_LOCAL_JSON_ERRORS",
    "MAX_ASCII_UINT_DIGITS",
    "MAX_LOOKBACK_DAYS",
    "MAX_LOOKBACK_HOURS",
    "as_whole_number",
    "default_library_dir",
    "is_recent_iso_timestamp",
    "parse_ascii_uint",
    "parse_bounded_json_int",
    "parse_iso_day_hour_duration",
    "read_bounded_json_object",
    "read_bounded_jsonl_objects",
    "read_local_utf8_text",
    "resolve_library_dir",
    "strict_json_loads",
]

LENIENT_LOCAL_JSON_ERRORS = (OSError, RecursionError, UnicodeError, ValueError)


def is_recent_iso_timestamp(
    value: object,
    *,
    now: datetime,
    max_age: timedelta,
) -> bool:
    """Return whether an ISO timestamp is at or before ``now`` and still recent.

    Cache timestamps are untrusted local state. Invalid values, timestamps from
    the future, and mixed naive/aware datetimes all fail closed so callers can
    refresh the cache instead of crashing or trusting it indefinitely.
    """

    if not isinstance(value, str) or max_age <= timedelta(0):
        return False
    normalized = f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    try:
        checked = datetime.fromisoformat(normalized)
        if (checked.utcoffset() is None) != (now.utcoffset() is None):
            return False
        age = now - checked
    except (OverflowError, TypeError, ValueError):
        return False
    return timedelta(0) <= age < max_age


def as_whole_number(value: object) -> int | None:
    """Return an int when ``value`` is a finite whole number.

    JSON ``5`` decodes as ``int`` and JSON ``5.0`` as ``float``. Both are
    whole numbers. Booleans are excluded because ``bool`` is an ``int``
    subclass and ``true`` must not become ``1``.
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        as_int = int(value)
        if float(as_int) == value:
            return as_int
    return None


def default_library_dir(package_dir: Path | None = None) -> Path:
    """Return an absolute default library directory.

    From a source checkout (distillr's own ``pyproject.toml`` sits one level
    up), keep the convenient ``<repo>/library`` so development data stays
    beside the code. When pip-installed, ``<package>/..`` is
    ``site-packages`` -- a bad home for user data (wiped on every
    reinstall/upgrade, may need admin write) -- so default to
    ``~/.distill/library`` instead. Override with DISTILL_OUTPUT_DIR.

    Two guards harden the checkout heuristic (a downstream integration hit
    the misfire live, 2026-06-12: a stray ``pyproject.toml`` in
    ``site-packages`` -- some badly packaged wheels ship one -- made an
    installed copy claim "source checkout" and the whole library landed
    inside ``site-packages\\library``): the parent must not be a
    ``site-packages``/``dist-packages`` tree, and the marker file must
    actually be distillr's own pyproject.
    """

    distill_pkg = package_dir or Path(__file__).resolve().parent
    parent = distill_pkg.parent
    in_installed_tree = any(
        part.lower() in {"site-packages", "dist-packages"} for part in parent.parts
    )
    marker = parent / "pyproject.toml"
    if not in_installed_tree and marker.exists():
        try:
            if 'name = "distillr"' in marker.read_text(encoding="utf-8"):
                return parent / "library"
        except OSError:
            pass
    try:
        home = Path.home()
    except RuntimeError:
        home = Path.cwd()
    return home / ".distill" / "library"


def resolve_library_dir(
    path: Path | str | None = None,
    *,
    package_dir: Path | None = None,
) -> Path:
    """Return an absolute library directory.

    Unset (or blank) uses the checkout/installed default. Relative values
    resolve against the process cwd so ``DISTILL_OUTPUT_DIR=library`` from a
    project directory stays in that project instead of under site-packages.
    """

    if path is None:
        return default_library_dir(package_dir)
    text = str(path).strip()
    if not text:
        return default_library_dir(package_dir)
    resolved = Path(text)
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def read_local_utf8_text(path: Path) -> str | None:
    """Read a local UTF-8 file, returning None when it is unreadable."""

    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


MAX_ASCII_UINT_DIGITS = 100
MAX_LOOKBACK_DAYS = 3_650
MAX_LOOKBACK_HOURS = MAX_LOOKBACK_DAYS * 24

_ISO_DAY_HOUR_DURATION_RE = re.compile(
    r"^P(?:(?P<days>[0-9]+)D(?:T(?P<day_hours>[0-9]+)H)?|T(?P<hours>[0-9]+)H)$"
)


def parse_ascii_uint(text: str) -> int | None:
    """Parse a nonempty ASCII unsigned integer without leaking exceptions.

    Unicode predicates such as :meth:`str.isdigit` accept numeric lookalikes
    that Python's :class:`int` does not consistently accept. Very long decimal
    strings can also exceed Python's integer-conversion safety limit. External
    boundaries use this parser when their wire or operator contract is ASCII.
    """

    if not text or len(text) > MAX_ASCII_UINT_DIGITS or not text.isascii() or not text.isdecimal():
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_bounded_json_int(text: str) -> int:
    """Parse one JSON integer with a process-independent digit bound."""

    digits = text[1:] if text.startswith("-") else text
    if (
        not digits
        or len(digits) > MAX_ASCII_UINT_DIGITS
        or not digits.isascii()
        or not digits.isdecimal()
    ):
        raise ValueError("JSON integer exceeds the supported digit bound")
    return int(text)


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _contains_non_finite_number(value: object) -> bool:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, float) and not math.isfinite(current):
            return True
        if isinstance(current, dict):
            pending.extend(cast(dict[object, object], current).values())
        elif isinstance(current, list):
            pending.extend(cast(list[object], current))
    return False


def strict_json_loads(content: str | bytes) -> object:
    """Parse standards-compliant JSON with bounded integers and finite floats."""

    loaded = cast(
        object,
        json.loads(
            content,
            parse_int=parse_bounded_json_int,
            parse_constant=_reject_non_finite_json_constant,
        ),
    )
    if _contains_non_finite_number(loaded):
        raise ValueError("non-finite JSON number is not allowed")
    return loaded


def read_bounded_json_object(path: Path, *, max_bytes: int) -> dict[str, object]:
    """Read one bounded strict JSON object, returning empty on invalid input."""

    if max_bytes < 1:
        return {}
    try:
        with path.open("rb") as stream:
            content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            return {}
        loaded = strict_json_loads(content)
    except (OSError, RecursionError, ValueError):
        return {}
    return cast(dict[str, object], loaded) if isinstance(loaded, dict) else {}


def read_bounded_jsonl_objects(
    path: Path,
    *,
    max_bytes: int,
    max_rows: int,
) -> list[dict[str, object]]:
    """Read strict object rows from the newest bounded tail of a JSONL file."""

    if max_bytes < 1 or max_rows < 1:
        return []
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size - max_bytes)
            stream.seek(start)
            content = stream.read(max_bytes)
    except OSError:
        return []
    if start:
        first_line_end = content.find(b"\n")
        content = content[first_line_end + 1 :] if first_line_end >= 0 else b""
    rows: list[dict[str, object]] = []
    for raw_line in content.splitlines()[-max_rows:]:
        try:
            loaded = strict_json_loads(raw_line)
        except (RecursionError, ValueError):
            continue
        if isinstance(loaded, dict):
            rows.append(cast(dict[str, object], loaded))
    return rows


def parse_iso_day_hour_duration(text: str) -> timedelta | None:
    """Parse the supported nonnegative ISO day/hour duration subset.

    Distill profile freshness accepts whole days, whole hours, or whole days
    followed by whole hours. The parser rejects non-ASCII digits and durations
    outside :class:`datetime.timedelta`'s representable range.
    """

    match = _ISO_DAY_HOUR_DURATION_RE.fullmatch(text)
    if match is None:
        return None
    raw_days = match.group("days") or "0"
    raw_hours = match.group("day_hours") or match.group("hours") or "0"
    days = parse_ascii_uint(raw_days)
    hours = parse_ascii_uint(raw_hours)
    if days is None or hours is None:
        return None
    try:
        return timedelta(days=days, hours=hours)
    except OverflowError:
        return None
