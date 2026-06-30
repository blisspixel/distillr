# pyright: strict
"""Structural citation-reference helpers for generated corpus prose."""

from __future__ import annotations

import re

__all__ = ["citation_refusal_reason", "extract_source_citations"]

_SOURCE_CITATION_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9_.-]*)\]")
_NON_SOURCE_BRACKET_LABELS = frozenset(
    {"Analysis", "Confirmed", "Estimated", "Reported", "Speculated"}
)


def extract_source_citations(text: str) -> list[str]:
    """Return bracketed source stems from generated prose, preserving first use."""

    citations: list[str] = []
    seen: set[str] = set()
    for match in _SOURCE_CITATION_RE.finditer(text):
        citation = match.group(1)
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
