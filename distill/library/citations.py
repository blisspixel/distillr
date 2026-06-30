"""Local citation export helpers for paper artifacts."""

# pyright: strict

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from distill.config import DistillConfig
from distill.library.paths import extract_frontmatter, find_artifact

__all__ = [
    "CitationRecord",
    "collect_paper_citations",
    "render_bibtex",
    "render_citations",
    "render_ris",
]


@dataclass(frozen=True, slots=True)
class CitationRecord:
    topic: str
    title: str
    authors: tuple[str, ...]
    year: str
    published_at: str
    updated_at: str
    paper_id: str
    doi: str
    url: str
    pdf_url: str
    categories: tuple[str, ...]
    abstract: str
    path: Path


def collect_paper_citations(config: DistillConfig, topic: str) -> list[CitationRecord]:
    """Collect local paper citation metadata from one topic or the whole library."""
    topics = _topic_dirs(config, topic)
    records: list[CitationRecord] = []
    for topic_name, topic_dir in topics:
        papers_dir = topic_dir / "papers"
        if not papers_dir.exists():
            continue
        for paper_dir in sorted(p for p in papers_dir.iterdir() if p.is_dir()):
            record = _citation_from_paper_dir(topic_name, paper_dir)
            if record is not None:
                records.append(record)
    return sorted(records, key=lambda r: (r.topic.lower(), r.year, r.title.lower(), r.paper_id))


def render_citations(records: list[CitationRecord], export_format: str) -> str:
    normalized = export_format.strip().lower()
    if normalized in {"bib", "bibtex"}:
        return render_bibtex(records)
    if normalized == "ris":
        return render_ris(records)
    raise ValueError("citation format must be bibtex or ris")


def render_bibtex(records: list[CitationRecord]) -> str:
    records = _require_existing_record_paths(records)
    keys: dict[str, int] = {}
    entries: list[str] = []
    for record in records:
        key = _unique_key(_bibtex_key(record), keys)
        fields = [
            ("title", record.title),
            ("author", " and ".join(record.authors)),
            ("year", record.year),
            ("eprint", record.paper_id),
            ("archivePrefix", "arXiv" if record.paper_id else ""),
            ("primaryClass", record.categories[0] if record.categories else ""),
            ("doi", record.doi),
            ("url", record.url),
        ]
        lines = [f"@misc{{{key},"]
        emitted = [(name, value) for name, value in fields if value]
        for index, (name, value) in enumerate(emitted):
            suffix = "," if index < len(emitted) - 1 else ""
            lines.append(f"  {name} = {{{_bibtex_escape(value)}}}{suffix}")
        lines.append("}")
        entries.append("\n".join(lines))
    return "\n\n".join(entries) + ("\n" if entries else "")


def render_ris(records: list[CitationRecord]) -> str:
    records = _require_existing_record_paths(records)
    entries: list[str] = []
    for record in records:
        lines = ["TY  - JOUR", f"T1  - {_ris_line(record.title)}"]
        for author in record.authors:
            lines.append(f"AU  - {_ris_line(author)}")
        if record.year:
            lines.append(f"PY  - {record.year}")
        if record.published_at:
            lines.append(f"Y1  - {_ris_line(record.published_at)}")
        if record.doi:
            lines.append(f"DO  - {_ris_line(record.doi)}")
        if record.url:
            lines.append(f"UR  - {_ris_line(record.url)}")
        if record.paper_id:
            lines.append(f"M3  - arXiv:{_ris_line(record.paper_id)}")
        for category in record.categories:
            lines.append(f"KW  - {_ris_line(category)}")
        if record.abstract:
            lines.append(f"N2  - {_ris_line(record.abstract)}")
        lines.append("ER  - ")
        entries.append("\n".join(lines))
    return "\n\n".join(entries) + ("\n" if entries else "")


def _topic_dirs(config: DistillConfig, topic: str) -> list[tuple[str, Path]]:
    if topic.strip().lower() == "all":
        topics_root = config.topics_dir()
        if not topics_root.exists():
            return []
        return sorted((path.name, path) for path in topics_root.iterdir() if path.is_dir())
    topic_dir = config.topic_dir(topic)
    return [(topic_dir.name, topic_dir)] if topic_dir.exists() else []


def _require_existing_record_paths(records: Iterable[CitationRecord]) -> list[CitationRecord]:
    """Refuse bibliography entries that no longer resolve to local evidence."""
    checked: list[CitationRecord] = []
    missing: list[str] = []
    for record in records:
        if record.path.exists():
            checked.append(record)
        else:
            missing.append(str(record.path))
    if missing:
        preview = ", ".join(missing[:3])
        suffix = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
        raise ValueError(f"citation record path does not exist: {preview}{suffix}")
    return checked


def _citation_from_paper_dir(topic_name: str, paper_dir: Path) -> CitationRecord | None:
    metadata = _load_metadata(paper_dir / "metadata.json")
    paper_path = find_artifact(paper_dir, "paper", identity=paper_dir.name)
    frontmatter = {}
    if paper_path.exists():
        frontmatter = extract_frontmatter(paper_path.read_text(encoding="utf-8"))
    elif not metadata:
        return None

    title = _first_text(frontmatter.get("title"), metadata.get("title"), paper_dir.name)
    paper_id = _first_text(
        frontmatter.get("paper_id"),
        frontmatter.get("source_id"),
        metadata.get("paper_id"),
    )
    published_at = _first_text(frontmatter.get("date"), metadata.get("published_at"))
    updated_at = _first_text(frontmatter.get("updated_at"), metadata.get("updated_at"))
    url = _first_text(frontmatter.get("url"), metadata.get("abs_url"))
    pdf_url = _first_text(frontmatter.get("pdf_url"), metadata.get("pdf_url"))
    doi = _first_text(frontmatter.get("doi"), metadata.get("doi"))
    return CitationRecord(
        topic=topic_name,
        title=title,
        authors=tuple(_list_value(frontmatter.get("authors"), metadata.get("authors"))),
        year=_year_from_date(published_at),
        published_at=published_at,
        updated_at=updated_at,
        paper_id=paper_id,
        doi=doi,
        url=url,
        pdf_url=pdf_url,
        categories=tuple(_list_value(frontmatter.get("categories"), metadata.get("categories"))),
        abstract=_first_text(metadata.get("abstract")),
        path=paper_path if paper_path.exists() else paper_dir / "metadata.json",
    )


def _load_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}


def _first_text(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip().strip('"')
        else:
            text = str(value).strip()
        if text:
            return text
    return ""


def _list_value(*values: object) -> list[str]:
    for value in values:
        if value in (None, "", []):
            continue
        if isinstance(value, list | tuple):
            items = cast("Iterable[object]", value)
            return [str(item).strip() for item in items if str(item).strip()]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return [text]
                if isinstance(parsed, list):
                    items = cast("list[object]", parsed)
                    return [str(item).strip() for item in items if str(item).strip()]
            return [text]
        return [str(value).strip()]
    return []


def _year_from_date(value: str) -> str:
    match = re.search(r"\b(19|20)\d{2}\b", value)
    return match.group(0) if match else ""


def _bibtex_key(record: CitationRecord) -> str:
    author = record.authors[0].split()[-1] if record.authors else "distill"
    raw = f"{author}{record.year}{record.paper_id or record.doi or record.title}"
    key = re.sub(r"[^A-Za-z0-9]+", "", raw)
    return key[:80] or "distill"


def _unique_key(key: str, keys: dict[str, int]) -> str:
    count = keys.get(key, 0)
    keys[key] = count + 1
    return key if count == 0 else f"{key}{count + 1}"


def _bibtex_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _ris_line(value: str) -> str:
    return " ".join(value.split())
