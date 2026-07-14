"""Wiki-link integrity checking and repair for the corpus."""

# pyright: strict

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import deal

from distill.library.paths import atomic_update_text
from distill.library.wikilinks import WIKI_LINK_PATTERN

__all__ = [
    "BrokenLink",
    "LinkCheckResult",
    "check_links",
    "fix_broken_links",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BrokenLink:
    """A wiki-link that does not resolve to an existing artifact."""

    source_file: Path
    line_number: int
    link_text: str  # The full [[...]] text
    target_slug: str  # The slug portion that failed to resolve


@dataclass(frozen=True, slots=True)
class LinkCheckResult:
    """Summary of a corpus-wide link integrity check."""

    total_links: int
    broken_links: list[BrokenLink]
    files_scanned: int

    @property
    def is_healthy(self) -> bool:
        return len(self.broken_links) == 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return {
            "total_links": self.total_links,
            "broken_links": [
                {
                    "source_file": str(bl.source_file),
                    "line_number": bl.line_number,
                    "link_text": bl.link_text,
                    "target_slug": bl.target_slug,
                }
                for bl in self.broken_links
            ],
            "files_scanned": self.files_scanned,
            "is_healthy": self.is_healthy,
        }


def _link_check_result_shape(result: LinkCheckResult) -> bool:
    return (
        result.total_links >= len(result.broken_links)
        and result.files_scanned >= 0
        and result.is_healthy == (len(result.broken_links) == 0)
        and all(
            broken.line_number > 0
            and broken.link_text.startswith("[[")
            and broken.link_text.endswith("]]")
            and broken.target_slug
            and WIKI_LINK_PATTERN.fullmatch(broken.link_text) is not None
            for broken in result.broken_links
        )
    )


def _fix_count_within_requested_links(
    library_dir: Path, broken: list[BrokenLink], *, result: int
) -> bool:
    del library_dir
    return 0 <= result <= len(broken)


@deal.post(_link_check_result_shape)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def check_links(library_dir: Path) -> LinkCheckResult:
    """Scan all markdown files in library_dir for broken wiki-links.

    Algorithm:
    1. Build a file index (set of all artifact stems in the corpus)
    2. Scan all .md files for [[...]] patterns
    3. For each link, check if the target slug resolves to an existing file stem
    """
    # Phase 1: Build file index (set of all artifact stems in corpus)
    file_index: set[str] = set()
    for md_file in library_dir.rglob("*.md"):
        stem = md_file.stem
        file_index.add(stem)

    # Phase 2: Scan all files for wiki-links
    total_links = 0
    broken: list[BrokenLink] = []
    files_scanned = 0

    for md_file in library_dir.rglob("*.md"):
        files_scanned += 1
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Could not read file: %s", md_file)
            continue

        for line_num, line in enumerate(content.splitlines(), start=1):
            for match in WIKI_LINK_PATTERN.finditer(line):
                total_links += 1
                target_slug = match.group(1).strip()
                if target_slug not in file_index:
                    broken.append(
                        BrokenLink(
                            source_file=md_file,
                            line_number=line_num,
                            link_text=match.group(0),
                            target_slug=target_slug,
                        )
                    )

    return LinkCheckResult(
        total_links=total_links,
        broken_links=broken,
        files_scanned=files_scanned,
    )


@deal.ensure(_fix_count_within_requested_links)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def fix_broken_links(library_dir: Path, broken: list[BrokenLink]) -> int:
    """Replace broken wiki-links with plain-text citations.

    For each broken link, replaces the [[slug|Display Title]] with just
    the display title (or the slug if no display title). Returns count of
    links fixed.
    """
    # Group broken links by source file for efficient processing
    by_file: dict[Path, list[BrokenLink]] = {}
    for bl in broken:
        by_file.setdefault(bl.source_file, []).append(bl)

    fixed_count = 0
    for file_path, file_broken in by_file.items():
        try:
            fixed_count += atomic_update_text(
                file_path,
                lambda content, repairs=file_broken: _repair_broken_links(content, repairs),
            )
        except OSError:
            logger.warning("Could not read file for fixing: %s", file_path)

    return fixed_count


def _repair_broken_links(content: str, broken: list[BrokenLink]) -> tuple[str, int]:
    """Repair links still present in the latest locked file content."""

    fixed_count = 0
    for item in broken:
        if item.link_text not in content:
            continue
        match = WIKI_LINK_PATTERN.search(item.link_text)
        if match:
            display = match.group(2)
            replacement = display.strip() if display else match.group(1).strip()
        else:
            replacement = item.target_slug
        updated = content.replace(item.link_text, replacement, 1)
        if updated != content:
            content = updated
            fixed_count += 1
    return content, fixed_count
