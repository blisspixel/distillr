"""Search engine for the Distill corpus.

Provides term-frequency based search across all artifact types in a topic,
with preview generation and section extraction for JIT context retrieval.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from distill.config import DistillConfig
from distill.library.paths import strip_frontmatter

__all__ = ["SearchResult", "extract_section", "search_corpus"]

# Artifact types and their score boosts
_TYPE_BOOST: dict[str, float] = {
    "synthesis": 1.5,
    "corpus": 1.5,
    "topic_synthesis": 1.5,
    "corpus_synthesis": 1.5,
    "paper_synthesis": 1.5,
    "site_synthesis": 1.5,
}

_HEADING_BOOST = 2.0

# Patterns for detecting artifact types from file paths/names
_ARTIFACT_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("topic_synthesis", "synthesis"),
    ("corpus_synthesis", "corpus"),
    ("paper_synthesis", "synthesis"),
    ("site_synthesis", "synthesis"),
    ("topic_diff", "diff"),
    ("topic_trends", "trends"),
    ("synthesis", "synthesis"),
    ("insights", "insights"),
    ("paper", "paper"),
    ("content", "insights"),
    ("diff", "diff"),
    ("trends", "trends"),
]

_MARKDOWN_STRIP_RE = re.compile(
    r"(?:"
    r"^#{1,6}\s+"  # heading markers
    r"|\*\*([^*]+)\*\*"  # bold
    r"|\*([^*]+)\*"  # italic
    r"|\[([^\]]+)\]\([^)]+\)"  # links
    r"|`([^`]+)`"  # inline code
    r")",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SearchResult:
    """A single search hit from the corpus."""

    path: str  # Relative path from library root
    preview: str  # Single line, <= 120 chars, no frontmatter
    score: float  # Relevance score (higher = more relevant)
    artifact_type: str  # insights | synthesis | diff | trends | corpus | paper


def search_corpus(
    config: DistillConfig,
    topic: str,
    query: str,
    *,
    limit: int = 10,
) -> list[SearchResult]:
    """Search all artifacts in a topic, return ranked results."""
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return []

    terms = _tokenize(query)
    if not terms:
        return []

    results: list[SearchResult] = []
    library_root = config.library_dir

    for md_file in topic_dir.rglob("*.md"):
        if not md_file.is_file():
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        body = strip_frontmatter(content)
        if not body.strip():
            continue

        artifact_type = _detect_artifact_type(md_file)
        score = _score_document(body, terms, artifact_type)

        if score <= 0:
            continue

        preview = _generate_preview(body, terms)
        rel_path = str(md_file.relative_to(library_root))

        results.append(
            SearchResult(
                path=rel_path,
                preview=preview,
                score=score,
                artifact_type=artifact_type,
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def extract_section(content: str, section_name: str) -> tuple[str, bool]:
    """Extract a section by heading name from markdown content.

    Returns (content, found). If not found, returns (full_content, False).
    """
    lines = content.split("\n")
    target = section_name.strip().lower()

    # Find the heading line
    start_idx = -1
    start_level = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            heading_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip().lower()
                if heading_text == target:
                    start_idx = i
                    start_level = level
                    break

    if start_idx < 0:
        return (content, False)

    # Find the end: next heading of equal or higher level
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            heading_match = re.match(r"^(#{1,6})\s+", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                if level <= start_level:
                    end_idx = i
                    break

    section_lines = lines[start_idx:end_idx]
    return ("\n".join(section_lines).strip(), True)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase terms."""
    return [t for t in re.split(r"[\s\W]+", text.lower()) if t]


def _detect_artifact_type(path: Path) -> str:
    """Detect artifact type from filename."""
    name = path.stem.lower()
    for pattern, atype in _ARTIFACT_TYPE_PATTERNS:
        if pattern in name:
            return atype
    # Check parent directory names
    parts = [p.lower() for p in path.parts]
    if "papers" in parts:
        return "paper"
    if "sites" in parts:
        return "insights"
    return "insights"


def _score_document(body: str, terms: list[str], artifact_type: str) -> float:
    """Score a document against query terms."""
    body_lower = body.lower()
    lines = body_lower.split("\n")

    matched_terms = 0
    total_hits = 0

    for term in terms:
        count = body_lower.count(term)
        if count > 0:
            matched_terms += 1
            total_hits += count

            # Check for heading boost
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("#") and term in stripped:
                    total_hits += int(_HEADING_BOOST)
                    break

    if matched_terms == 0:
        return 0.0

    # Base score: fraction of query terms matched x log-scaled hit count
    base = (matched_terms / len(terms)) * (1 + math.log(max(total_hits, 1)))

    # Type boost for higher-level artifacts
    type_boost = _TYPE_BOOST.get(artifact_type, 1.0)

    return base * type_boost


def _generate_preview(body: str, terms: list[str]) -> str:
    """Generate a single-line preview ≤120 chars from artifact content."""
    lines = body.split("\n")

    # Find first line containing a query term match
    best_line = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip pure heading markers
        if re.match(r"^#{1,6}\s*$", stripped):
            continue
        line_lower = stripped.lower()
        if any(term in line_lower for term in terms):
            best_line = stripped
            break

    # Fall back to first non-empty line after frontmatter
    if not best_line:
        for line in lines:
            stripped = line.strip()
            if stripped and not re.match(r"^#{1,6}\s*$", stripped):
                best_line = stripped
                break

    if not best_line:
        return ""

    # Strip markdown formatting
    cleaned = _strip_markdown(best_line)

    # Truncate at word boundary to 120 chars
    return _truncate_at_word(cleaned, 120)


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting from text."""
    # Remove heading markers
    text = re.sub(r"^#{1,6}\s+", "", text)
    # Replace bold with content
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    # Replace italic with content
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    # Replace links with text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Replace inline code with content
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove remaining markdown chars
    text = re.sub(r"^[-*+]\s+", "", text)
    return text.strip()


def _truncate_at_word(text: str, max_len: int) -> str:
    """Truncate text at a word boundary."""
    if len(text) <= max_len:
        return text
    # Find last space before max_len
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > max_len // 2:
        return truncated[:last_space].rstrip() + "..."
    return truncated[: max_len - 3].rstrip() + "..."
