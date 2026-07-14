# pyright: strict
"""Memory-limited subprocess worker for local PDF text extraction."""

from __future__ import annotations

import os
import sys
from itertools import islice
from pathlib import Path


def _set_posix_memory_limit(limit_bytes: int) -> None:
    if os.name == "nt":
        return
    import resource

    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    bounded_hard = limit_bytes if hard == resource.RLIM_INFINITY else min(hard, limit_bytes)
    bounded_soft = bounded_hard if soft == resource.RLIM_INFINITY else min(soft, bounded_hard)
    resource.setrlimit(resource.RLIMIT_AS, (bounded_soft, bounded_hard))


def extract_pdf_to_file(
    source: Path,
    destination: Path,
    *,
    max_chars: int,
    max_pages: int,
) -> None:
    """Incrementally extract bounded page text to ``destination``."""

    from pypdf import PdfReader

    reader = PdfReader(str(source))
    extracted_chars = 0
    wrote_page = False
    with destination.open("w", encoding="utf-8", errors="ignore", newline="\n") as output:
        for page in islice(reader.pages, max_pages):
            separator_chars = 2 if wrote_page else 0
            remaining = max_chars - extracted_chars - separator_chars
            if remaining <= 0:
                break
            page_text = page.extract_text() or ""
            start = next(
                (index for index, character in enumerate(page_text) if not character.isspace()),
                len(page_text),
            )
            bounded_text = page_text[start : start + remaining].rstrip()
            if not bounded_text:
                continue
            if wrote_page:
                output.write("\n\n")
            output.write(bounded_text)
            wrote_page = True
            extracted_chars += separator_chars + len(bounded_text)


def main() -> int:
    if len(sys.argv) != 6:
        return 2
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    try:
        max_chars = int(sys.argv[3])
        max_pages = int(sys.argv[4])
        memory_limit = int(sys.argv[5])
        _set_posix_memory_limit(memory_limit)
        if sys.stdin.buffer.read(1) != b"1":
            return 3
        extract_pdf_to_file(
            source,
            destination,
            max_chars=max_chars,
            max_pages=max_pages,
        )
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
