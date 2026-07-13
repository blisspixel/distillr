# pyright: strict
"""Small total parsers kept inside the deliberately isolated LLM package."""

from __future__ import annotations

_MAX_ASCII_UINT_DIGITS = 100


def parse_ascii_uint(text: str) -> int | None:
    """Parse a bounded nonempty ASCII unsigned integer without exceptions."""

    if not text or len(text) > _MAX_ASCII_UINT_DIGITS or not text.isascii() or not text.isdecimal():
        return None
    try:
        return int(text)
    except ValueError:
        return None
