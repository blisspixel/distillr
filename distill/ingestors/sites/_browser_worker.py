# pyright: strict
"""Scratch-only browser crawl worker launched by the bounded parent."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from distill.ingestors.sites.scraper import (
    BROWSER_WORKER_RESULT_BYTES,
    BROWSER_WORKER_SCHEMA_VERSION,
    SiteSeed,
    crawl_site_in_browser_worker,
)


def _seed_from_payload(payload: object) -> SiteSeed:
    if not isinstance(payload, dict):
        raise ValueError("browser seed must be a JSON object")
    row = cast(dict[str, Any], payload)
    allowed = {
        "url",
        "topic",
        "site_name",
        "label",
        "section_label",
        "source_hint",
        "freshness_hint",
        "crawl_prefix",
        "discover_crawl",
        "max_depth",
        "max_pages",
        "same_section_only",
    }
    if set(row) != allowed:
        raise ValueError("browser seed fields do not match the supported schema")
    return SiteSeed(**row)


def _write_result(path: Path, pages: list[object]) -> None:
    encoded = json.dumps(
        {
            "schema_version": BROWSER_WORKER_SCHEMA_VERSION,
            "pages": pages,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > BROWSER_WORKER_RESULT_BYTES:
        raise ValueError("browser crawl result exceeds its byte limit")
    path.write_bytes(encoded)


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    try:
        payload = json.loads(input_path.read_bytes())
        seed = _seed_from_payload(payload)
        if sys.stdin.buffer.read(1) != b"1":
            return 3
        pages = crawl_site_in_browser_worker(seed)
        _write_result(output_path, [asdict(page) for page in pages])
    except Exception as exc:
        detail = str(exc).replace("\r", " ").replace("\n", " ")[:500]
        sys.stderr.write(f"{type(exc).__name__}: {detail}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
