# pyright: strict
"""Scratch-only worker for bounded local HTML parsing."""

from __future__ import annotations

import sys
from pathlib import Path

from distill.ingestors.local.extract import HTML_WORKER_INPUT_BYTES, html_to_text


def main() -> int:
    if len(sys.argv) != 4:
        return 2
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    try:
        max_chars = int(sys.argv[3])
        if max_chars <= 0:
            return 2
        if sys.stdin.buffer.read(1) != b"1":
            return 3
        raw = source.read_bytes()
        if len(raw) > HTML_WORKER_INPUT_BYTES:
            raise ValueError("HTML input exceeds its byte limit")
        text = html_to_text(
            raw.decode("utf-8", errors="replace"),
            max_chars=max_chars,
        )
        destination.write_text(text, encoding="utf-8")
    except Exception as exc:
        detail = str(exc).replace("\r", " ").replace("\n", " ")[:500]
        sys.stderr.write(f"{type(exc).__name__}: {detail}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
