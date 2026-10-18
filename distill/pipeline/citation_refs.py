# pyright: strict
"""Structural citation-reference helpers for generated corpus prose."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import PurePosixPath

__all__ = [
    "citation_refusal_reason",
    "extract_source_citations",
    "unresolved_numbered_citation_reason",
]

_SOURCE_CITATION_RE = re.compile(
    r"\[([A-Za-z0-9][A-Za-z0-9_.-]*(?:\s*,\s*[A-Za-z0-9][A-Za-z0-9_.-]*)*)\]"
)
_NUMBERED_REPORT_CITATION_RE = re.compile(r"\[cite:\s*[\d,\s]+\]", flags=re.IGNORECASE)
_NON_SOURCE_BRACKET_LABELS = frozenset(
    {"Analysis", "Confirmed", "Estimated", "Reported", "Speculated"}
)


def artifact_citation_handles(paths: Iterable[str]) -> dict[str, str]:
    """Disambiguate identical legacy basenames by exact artifact identity."""
    ordered = list(paths)
    counts = Counter(PurePosixPath(path).stem for path in ordered)
    return {
        path: PurePosixPath(path).stem
        + (
            "_" + hashlib.sha256(path.encode()).hexdigest()[:12]
            if counts[PurePosixPath(path).stem] > 1
            else ""
        )
        for path in ordered
    }


def extract_source_citations(text: str) -> list[str]:
    """Return bracketed source stems from generated prose, preserving first use."""

    citations: list[str] = []
    seen: set[str] = set()
    for match in _SOURCE_CITATION_RE.finditer(text):
        for citation in (part.strip() for part in match.group(1).split(",")):
            if citation in _NON_SOURCE_BRACKET_LABELS or citation in seen:
                continue
            seen.add(citation)
            citations.append(citation)
    return citations


def citation_refusal_reason(
    citations: list[str],
    resolved: list[str],
    allowed_stems: list[str],
    *,
    subject: str,
    action: str,
) -> str:
    """Return the structural refusal reason for generated citation identity."""

    allowed = set(allowed_stems)
    unknown = [citation for citation in citations if citation not in allowed]
    if unknown:
        sample = ", ".join(unknown[:5])
        extra = "" if len(unknown) <= 5 else f", +{len(unknown) - 5} more"
        return f"{subject} cites unknown source(s): {sample}{extra}"
    if not resolved:
        return f"{subject} includes no valid source citations; nothing to {action}"
    return ""


def unresolved_numbered_citation_reason(content: str) -> str:
    """Return a refusal reason for report citations that have no resolvable map."""

    refs = tuple(_NUMBERED_REPORT_CITATION_RE.findall(content))
    if not refs:
        return ""
    joined = ", ".join(refs[:3])
    suffix = "" if len(refs) <= 3 else f", and {len(refs) - 3} more"
    return f"unresolved numbered report citation(s): {joined}{suffix}"
