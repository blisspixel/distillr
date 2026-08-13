# pyright: strict
"""Deterministic report assembly and structural auditing."""

from __future__ import annotations

import re
from datetime import datetime

from distill.pipeline.citation_refs import unresolved_numbered_citation_reason
from distill.prompts.report import WrittenSection

__all__ = ["assemble_report", "audit_assembled_report"]


def assemble_report(
    *,
    topic: str,
    scope_label: str,
    sections: list[WrittenSection],
    video_count: int,
    channel_count: int,
    method_label: str,
    report_title: str,
    show_video_coverage: bool,
) -> str:
    """Render ordered sections and truthful scope metadata as Markdown."""

    now = datetime.now().strftime("%B %d, %Y")
    lines = [
        f"# {report_title}: {topic.upper()}",
        "",
        f"*{scope_label} | {now}*",
    ]
    if show_video_coverage:
        lines.append(f"*{channel_count} channel(s), {video_count} videos analyzed*")
    lines.extend([f"*{method_label}*", "", "---", ""])

    lines.extend(["## Table of Contents", ""])
    for index, section in enumerate(sections, 1):
        lines.append(f"{index}. **{section['title']}** ({section['word_count']:,} words)")
    lines.extend(["", "---", ""])

    for section in sections:
        lines.extend([f"## {section['title']}", "", section["content"], "", "---", ""])

    total_words = sum(section.get("word_count", 0) for section in sections)
    lines.append(
        f"*Distill report | {method_label} | {len(sections)} sections | {total_words:,} words*"
    )
    return "\n".join(lines)


def audit_assembled_report(report: str, sections: list[WrittenSection]) -> None:
    """Enforce citation, uniqueness, and ordering invariants after model rewrites."""

    refusal = unresolved_numbered_citation_reason(report)
    if refusal:
        raise ValueError(f"assembled report refused: {refusal}")
    cursor = -1
    for section in sections:
        heading_pattern = re.compile(
            rf"^##[ \t]+{re.escape(section['title'])}[ \t]*$",
            flags=re.MULTILINE,
        )
        matches = list(heading_pattern.finditer(report))
        if len(matches) != 1:
            raise ValueError(f"assembled report must contain one heading for {section['title']}")
        next_cursor = matches[0].start()
        if next_cursor <= cursor:
            raise ValueError("assembled report section order does not match the written spine")
        cursor = next_cursor
