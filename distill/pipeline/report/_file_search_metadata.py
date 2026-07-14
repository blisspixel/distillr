# pyright: strict
"""Metadata parsing helpers for Gemini File Search corpus assembly."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from distill.library.confined import read_confined_text
from distill.parsing import strict_json_loads

logger = logging.getLogger(__name__)
_MAX_METADATA_BYTES = 1024 * 1024


def read_metadata(meta_file: Path, *, root: Path | None = None) -> dict[str, object]:
    try:
        if root is None:
            raw_text = meta_file.read_text(encoding="utf-8")
        else:
            raw_text = read_confined_text(meta_file, root, max_bytes=_MAX_METADATA_BYTES)
            if raw_text is None:
                return {}
        raw_meta = strict_json_loads(raw_text)
    except (OSError, RecursionError, ValueError):
        logger.debug("failed to read File Search metadata from %s", meta_file, exc_info=True)
        return {}
    if not isinstance(raw_meta, dict):
        logger.debug("File Search metadata was not an object: %s", meta_file)
        return {}
    return cast("dict[str, object]", raw_meta)


def metadata_str(meta: dict[str, object], key: str, default: str = "") -> str:
    value = meta.get(key)
    return value if isinstance(value, str) else default
