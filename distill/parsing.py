"""Small total parsers shared across external-input boundaries."""

from __future__ import annotations

import json
import math
import re
from datetime import timedelta
from pathlib import Path
from typing import cast

__all__ = [
    "LENIENT_LOCAL_JSON_ERRORS",
    "MAX_ASCII_UINT_DIGITS",
    "MAX_LOOKBACK_DAYS",
    "MAX_LOOKBACK_HOURS",
    "parse_ascii_uint",
    "parse_bounded_json_int",
    "parse_iso_day_hour_duration",
    "read_bounded_json_object",
    "read_bounded_jsonl_objects",
    "read_local_utf8_text",
    "strict_json_loads",
]

LENIENT_LOCAL_JSON_ERRORS = (OSError, RecursionError, UnicodeError, ValueError)


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
