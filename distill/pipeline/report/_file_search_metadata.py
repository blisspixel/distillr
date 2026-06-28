# pyright: strict
"""Metadata parsing helpers for Gemini File Search corpus assembly."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)


def read_metadata(meta_file: Path) -> dict[str, object]:
    try:
        raw_meta: object = json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.debug("failed to read File Search metadata from %s", meta_file, exc_info=True)
        return {}
    if not isinstance(raw_meta, dict):
        logger.debug("File Search metadata was not an object: %s", meta_file)
        return {}
    return cast("dict[str, object]", raw_meta)


def metadata_str(meta: dict[str, object], key: str, default: str = "") -> str:
    value = meta.get(key)
    return value if isinstance(value, str) else default
