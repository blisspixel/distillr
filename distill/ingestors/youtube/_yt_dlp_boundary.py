"""Typed boundary helpers for yt-dlp's dynamic Python API."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any, cast

from distill.parsing import parse_ascii_uint

YtDlpInfo = Mapping[str, object]
_MAX_INTEGER_FIELD = (1 << 63) - 1


def ydl_params(params: Mapping[str, object]) -> Any:
    """Return params in the dynamic shape accepted by ``YoutubeDL``."""
    return cast(Any, params)


def date_range(start: str) -> object:
    """Create a yt-dlp date range without reaching through the package module."""
    from yt_dlp.utils import DateRange

    return DateRange(cast(Any, start))


def info_mapping(value: object) -> YtDlpInfo | None:
    """Narrow an extracted yt-dlp result to a mapping."""
    return cast(YtDlpInfo, value) if isinstance(value, Mapping) else None


def info_entries(value: object) -> list[YtDlpInfo]:
    """Return mapping entries from a yt-dlp playlist result."""
    if not isinstance(value, Iterable) or isinstance(value, str | bytes):
        return []
    rows: list[YtDlpInfo] = []
    for item in value:
        row = info_mapping(item)
        if row is not None:
            rows.append(row)
    return rows


def text_field(row: YtDlpInfo, key: str, default: str = "") -> str:
    value = row.get(key)
    return value if isinstance(value, str) else default


def first_text(row: YtDlpInfo, keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = text_field(row, key)
        if value:
            return value
    return default


def int_field(row: YtDlpInfo, key: str, default: int = 0) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return default
    if isinstance(value, str):
        parsed = parse_ascii_uint(value)
    elif isinstance(value, float):
        parsed = int(value) if math.isfinite(value) and value.is_integer() else None
    else:
        parsed = value
    if parsed is None:
        return default
    return parsed if 0 <= parsed <= _MAX_INTEGER_FIELD else default
