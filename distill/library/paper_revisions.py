# pyright: strict
"""Separate arXiv work identity from the exact revision captured."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from distill.library.ingested import normalize_arxiv_id
from distill.library.insights import discover_insights, read_discovered_insight
from distill.library.paths import extract_frontmatter

RevisionStatus = Literal["new", "captured", "older", "update", "unknown"]
_REVISION = re.compile(r"v([1-9][0-9]*)$")


def captured_revision_dates(topic_dir: Path) -> dict[str, tuple[str, str]]:
    """Read revision and capture dates without substituting filesystem times."""
    dates: dict[str, tuple[str, str]] = {}
    for ref in discover_insights(topic_dir):
        content = read_discovered_insight(ref, topic_dir.parent.parent)
        if content is None:
            continue
        metadata = extract_frontmatter(content)
        dates[ref.source_id] = (
            metadata.get("updated_at") or "unknown",
            metadata.get("generated_at") or "unknown",
        )
    return dates


def parse_revision_status(value: str) -> RevisionStatus:
    match value:
        case "new":
            return "new"
        case "captured":
            return "captured"
        case "older":
            return "older"
        case "update":
            return "update"
        case "unknown":
            return "unknown"
        case _:
            raise ValueError("Invalid paper revision status")


@dataclass(frozen=True)
class PaperRevision:
    work_id: str
    discovered_id: str
    captured_ids: tuple[str, ...]
    status: RevisionStatus


def classify_paper_revision(paper_id: str, ingested: frozenset[str]) -> PaperRevision:
    work = normalize_arxiv_id(paper_id)
    captured = tuple(
        sorted(identity for identity in ingested if normalize_arxiv_id(identity) == work)
    )
    version = _REVISION.search(paper_id)
    revisions = [
        int(match.group(1)) for identity in captured if (match := _REVISION.search(identity))
    ]
    if not captured:
        status: RevisionStatus = "new"
    elif version is None or not revisions:
        status = "unknown"
    elif paper_id in captured:
        status = "captured"
    else:
        status = "update" if int(version.group(1)) > max(revisions) else "older"
    return PaperRevision(work, paper_id, captured, status)
