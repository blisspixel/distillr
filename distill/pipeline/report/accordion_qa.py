"""Deterministic parsing helpers for accordion report QA output."""

# pyright: strict

from __future__ import annotations

import re

__all__ = [
    "extract_section_feedback",
    "normalize_qa_title",
    "parse_qa_failures",
]


def normalize_qa_title(title: str) -> str:
    """Normalize cosmetic title differences before matching QA sections."""
    normalized = re.sub(r"^\s*\d+[.)]\s*", "", title.strip().lower())
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return normalized.strip()


def parse_qa_failures(qa_result: str) -> list[str]:
    """Extract section titles whose own score line contains ``FAIL``."""
    failed: list[str] = []
    current_section: str | None = None

    for line in qa_result.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            header = stripped[4:].strip()
            current_section = None if header == "OVERALL" else header
            continue
        if current_section is None:
            continue
        marker = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", stripped)
        if marker.startswith("**Score**"):
            if "FAIL" in marker.upper():
                failed.append(current_section)
            current_section = None

    return failed


def extract_section_feedback(qa_result: str) -> dict[str, str]:
    """Group QA feedback text by its section heading."""
    feedback: dict[str, str] = {}
    current_section: str | None = None
    current_lines: list[str] = []

    for line in qa_result.split("\n"):
        stripped = line.strip()
        if stripped.startswith("### "):
            if current_section and current_lines:
                feedback[current_section] = "\n".join(current_lines)
            current_section = stripped[4:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section and current_lines:
        feedback[current_section] = "\n".join(current_lines)

    return feedback
