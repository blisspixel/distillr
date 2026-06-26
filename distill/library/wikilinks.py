"""Wiki-link formatting and resolution for Obsidian-compatible cross-references.

This module provides the ``WikiLink`` dataclass and helpers for emitting,
parsing, and validating ``[[slug_Suffix|Display Title]]`` wiki-links used
throughout the distillr corpus.
"""

# pyright: strict

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "WIKI_LINK_PATTERN",
    "WikiLink",
    "emit_wiki_link",
    "parse_wiki_links",
]

logger = logging.getLogger(__name__)

# Regex for matching Obsidian-style wiki-links: [[slug_Suffix|Display Title]]
# Group 1: slug portion (everything before the optional pipe)
# Group 2: display title (optional, after the pipe)
WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")


@dataclass(frozen=True, slots=True)
class WikiLink:
    """An Obsidian-compatible wiki-link: [[slug_Suffix|Display Title]]."""

    slug: str
    suffix: str  # e.g. "Insights", "Synthesis"
    display_title: str

    def render(self) -> str:
        """Render as [[slug_Suffix|Display Title]]."""
        return f"[[{self.slug}_{self.suffix}|{self.display_title}]]"

    @classmethod
    def from_source(
        cls,
        title: str,
        source_id: str,
        artifact_type: str = "insights",
    ) -> WikiLink:
        """Create a WikiLink from source metadata.

        Looks up the suffix from ARTIFACT_SUFFIXES, defaulting to
        ``artifact_type.title()`` if not found. Strips leading/trailing
        whitespace and removes ``[`` and ``]`` characters from the display
        title (they break wiki-link syntax).
        """
        from distill.library.paths import ARTIFACT_SUFFIXES, slugify_title

        slug = slugify_title(title, source_id)
        suffix = ARTIFACT_SUFFIXES.get(artifact_type, artifact_type.replace("-", "_").title())
        # Remove characters that would break [[slug|display]] syntax or markdown,
        # then strip whitespace
        clean_title = (
            title.replace("[", "")
            .replace("]", "")
            .replace("|", "")
            .replace("\n", " ")
            .replace("\r", "")
            .strip()
        )
        return cls(slug=slug, suffix=suffix, display_title=clean_title)


def emit_wiki_link(
    title: str,
    source_id: str,
    artifact_type: str = "insights",
    *,
    corpus_dir: Path | None = None,
) -> str:
    """Emit a wiki-link string, falling back to plain text if slug unresolvable.

    If *corpus_dir* is provided, validates the target exists by searching for
    files matching the slug and suffix pattern. If not found, returns a
    plain-text citation and logs a warning.
    """
    link = WikiLink.from_source(title, source_id, artifact_type)

    if corpus_dir is not None:
        if not corpus_dir.is_dir():
            # A missing or non-directory corpus_dir can't validate anything —
            # fall back to the plain title rather than emitting an unverified
            # wiki-link the caller asked us to validate. This matches the
            # "target not found" branch below so consumers get one consistent
            # contract: when corpus_dir is provided and the target can't be
            # confirmed, no rendered link is emitted.
            logger.warning(
                "corpus_dir is not a directory: %s (title=%r)",
                corpus_dir,
                title,
            )
            return title
        target_pattern = f"{link.slug}_{link.suffix}*"
        matches = list(corpus_dir.rglob(target_pattern))
        if not matches:
            logger.warning(
                "Wiki-link target not found in corpus: %s_%s (title=%r)",
                link.slug,
                link.suffix,
                title,
            )
            return title

    return link.render()


def parse_wiki_links(content: str) -> list[WikiLink]:
    """Extract all [[...]] wiki-links from markdown content.

    Returns a list of WikiLink objects. For links without a display title
    (no pipe separator), the slug portion is used as the display_title.
    The slug portion is split on the last underscore to separate the base
    slug from the suffix.
    """
    results: list[WikiLink] = []
    for match in WIKI_LINK_PATTERN.finditer(content):
        slug_portion = match.group(1).strip()
        display = match.group(2)
        display_title = display.strip() if display else slug_portion

        # Split slug_portion into slug and suffix on the last underscore
        last_underscore = slug_portion.rfind("_")
        if last_underscore > 0:
            slug = slug_portion[:last_underscore]
            suffix = slug_portion[last_underscore + 1 :]
        else:
            slug = slug_portion
            suffix = ""

        results.append(WikiLink(slug=slug, suffix=suffix, display_title=display_title))
    return results
