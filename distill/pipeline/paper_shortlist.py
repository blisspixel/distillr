# pyright: strict
"""Persist a previewed paper shortlist and reload that exact set."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.library.paths import atomic_write_text
from distill.parsing import strict_json_loads
from distill.pipeline.ranking import RankedPaper

__all__ = [
    "DEFAULT_SHORTLIST_MAX_AGE_HOURS",
    "PaperShortlist",
    "PaperShortlistError",
    "load_library_last",
    "load_topic_latest",
    "load_topic_shortlist",
    "save_paper_shortlist",
]

DEFAULT_SHORTLIST_MAX_AGE_HOURS = 168.0
_SCHEMA = 1
_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_VERSION_RE = re.compile(r"v(\d+)$")
_MAX_FILE_BYTES = 8_000_000
_MAX_PAPERS = 200


class PaperShortlistError(Exception):
    """A saved paper shortlist is missing, stale, or unreadable."""


@dataclass(frozen=True)
class PaperShortlist:
    """One previewed paper set, in the order the operator saw."""

    id: str
    topic: str
    query: str
    expansion_queries: tuple[str, ...]
    model: str
    created_at: str
    papers: tuple[PaperRecord, ...]
    scores: tuple[float, ...]


def _topic_name(config: DistillConfig, topic: str) -> str:
    return config.topic_dir(topic).name


def _shortlist_dir(config: DistillConfig, topic: str) -> Path:
    return config.topic_dir(topic) / ".distill" / "shortlists"


def _pointer_path(config: DistillConfig) -> Path:
    return config.library_dir / ".distill" / "last-paper-shortlist.json"


def _shortlist_id(topic: str, query: str, paper_ids: list[str]) -> str:
    payload = json.dumps(
        {"topic": topic, "query": query, "papers": paper_ids},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _version_of(paper_id: str) -> str:
    match = _VERSION_RE.search(paper_id)
    return match.group(1) if match else ""


def _max_age() -> timedelta:
    raw = os.environ.get("DISTILL_SHORTLIST_MAX_AGE_HOURS", "").strip()
    try:
        hours = float(raw) if raw else DEFAULT_SHORTLIST_MAX_AGE_HOURS
    except ValueError:
        hours = DEFAULT_SHORTLIST_MAX_AGE_HOURS
    if hours < 0:
        hours = DEFAULT_SHORTLIST_MAX_AGE_HOURS
    return timedelta(hours=hours)


def _allow_stale() -> bool:
    return os.environ.get("DISTILL_SHORTLIST_ALLOW_STALE", "").strip() == "1"


def _parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _string(row: dict[str, object], key: str, default: str = "") -> str:
    value = row.get(key, default)
    if not isinstance(value, str):
        raise PaperShortlistError(f"shortlist field {key} must be a string")
    return value


def _string_list(value: object, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PaperShortlistError(f"shortlist field {field_name} must be a list")
    items = cast(list[object], value)
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise PaperShortlistError(f"shortlist field {field_name} must contain strings")
        result.append(item)
    return result


def _score(row: dict[str, object]) -> float:
    value = row.get("score", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _paper_from_row(row: object) -> tuple[PaperRecord, float]:
    if not isinstance(row, dict):
        raise PaperShortlistError("shortlist paper must be an object")
    typed = cast(dict[str, object], row)
    paper_id = _string(typed, "paper_id")
    title = _string(typed, "title")
    if not paper_id or not title:
        raise PaperShortlistError("shortlist paper is missing an id or title")
    return PaperRecord(
        paper_id=paper_id,
        title=title,
        abstract=_string(typed, "abstract"),
        authors=_string_list(typed.get("authors"), "authors"),
        published_at=_string(typed, "published_at"),
        updated_at=_string(typed, "updated_at"),
        categories=_string_list(typed.get("categories"), "categories"),
        doi=_string(typed, "doi"),
        abs_url=_string(typed, "abs_url"),
        pdf_url=_string(typed, "pdf_url"),
        source=_string(typed, "source") or "arxiv",
    ), _score(typed)


def _paper_row(item: RankedPaper) -> dict[str, object]:
    paper = item.paper
    return {
        "paper_id": paper.paper_id,
        "version": _version_of(paper.paper_id),
        "title": paper.title,
        "abstract": paper.abstract,
        "authors": list(paper.authors),
        "published_at": paper.published_at,
        "updated_at": paper.updated_at,
        "categories": list(paper.categories),
        "doi": paper.doi,
        "abs_url": paper.abs_url,
        "pdf_url": paper.pdf_url,
        "source": paper.source,
        "score": item.final_score,
        "rationale": item.rationale,
        "selected_by": item.selected_by,
    }


def _read_json(path: Path) -> dict[str, object]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PaperShortlistError(f"Could not read shortlist {path.name}") from exc
    if size > _MAX_FILE_BYTES:
        raise PaperShortlistError(f"Shortlist {path.name} is too large")
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PaperShortlistError(f"Shortlist {path.name} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise PaperShortlistError(f"Shortlist {path.name} is not an object")
    return cast(dict[str, object], payload)


def _check_age(created_at: str) -> None:
    if _allow_stale():
        return
    try:
        created = _parse_time(created_at)
    except ValueError as exc:
        raise PaperShortlistError("Shortlist timestamp is invalid") from exc
    age = datetime.now(UTC) - created
    if age > _max_age():
        raise PaperShortlistError(
            "Shortlist is older than DISTILL_SHORTLIST_MAX_AGE_HOURS. "
            "Preview again, or set DISTILL_SHORTLIST_ALLOW_STALE=1 to ingest it anyway."
        )


def _from_payload(payload: dict[str, object], *, expected_id: str) -> PaperShortlist:
    schema = payload.get("schema")
    if schema != _SCHEMA:
        raise PaperShortlistError("Shortlist schema is not supported")
    shortlist_id = _string(payload, "id")
    if not _ID_RE.fullmatch(shortlist_id) or shortlist_id != expected_id:
        raise PaperShortlistError("Shortlist id does not match the file")
    papers_raw = payload.get("papers")
    if not isinstance(papers_raw, list):
        raise PaperShortlistError("Shortlist papers are missing or too long")
    papers_list = cast(list[object], papers_raw)
    if len(papers_list) > _MAX_PAPERS:
        raise PaperShortlistError("Shortlist papers are missing or too long")
    decoded = [_paper_from_row(row) for row in papers_list]
    papers = tuple(paper for paper, _score_value in decoded)
    scores = tuple(score for _paper, score in decoded)
    created_at = _string(payload, "created_at")
    _check_age(created_at)
    return PaperShortlist(
        id=shortlist_id,
        topic=_string(payload, "topic"),
        query=_string(payload, "query"),
        expansion_queries=tuple(
            _string_list(payload.get("expansion_queries"), "expansion_queries")
        ),
        model=_string(payload, "model"),
        created_at=created_at,
        papers=papers,
        scores=scores,
    )


def save_paper_shortlist(
    config: DistillConfig,
    *,
    topic: str,
    query: str,
    expansion_queries: list[str],
    model: str,
    ranked: list[RankedPaper],
) -> PaperShortlist:
    """Write the previewed set and point the topic and library at it."""

    topic_name = _topic_name(config, topic)
    paper_ids = [item.paper.paper_id for item in ranked]
    shortlist_id = _shortlist_id(topic_name, query, paper_ids)
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    payload = {
        "schema": _SCHEMA,
        "id": shortlist_id,
        "topic": topic_name,
        "query": query,
        "expansion_queries": expansion_queries,
        "model": model,
        "created_at": created_at,
        "papers": [_paper_row(item) for item in ranked],
    }
    directory = _shortlist_dir(config, topic_name)
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    atomic_write_text(directory / f"{shortlist_id}.json", text)
    atomic_write_text(directory / "latest", shortlist_id + "\n")
    pointer = _pointer_path(config)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        pointer,
        json.dumps({"id": shortlist_id, "topic": topic_name}, sort_keys=True) + "\n",
    )
    return PaperShortlist(
        id=shortlist_id,
        topic=topic_name,
        query=query,
        expansion_queries=tuple(expansion_queries),
        model=model,
        created_at=created_at,
        papers=tuple(item.paper for item in ranked),
        scores=tuple(item.final_score for item in ranked),
    )


def load_topic_shortlist(config: DistillConfig, topic: str, shortlist_id: str) -> PaperShortlist:
    """Load one topic shortlist by id."""

    if not _ID_RE.fullmatch(shortlist_id):
        raise PaperShortlistError("Shortlist id must be 12 hex characters")
    path = _shortlist_dir(config, topic) / f"{shortlist_id}.json"
    if not path.is_file():
        raise PaperShortlistError(
            f"No shortlist {shortlist_id} for this topic. Pass the topic used at preview time."
        )
    return _from_payload(_read_json(path), expected_id=shortlist_id)


def load_topic_latest(config: DistillConfig, topic: str) -> PaperShortlist:
    """Load the topic's latest preview pointer."""

    pointer = _shortlist_dir(config, topic) / "latest"
    try:
        shortlist_id = pointer.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise PaperShortlistError("This topic has no saved paper preview.") from exc
    return load_topic_shortlist(config, topic, shortlist_id)


def load_library_last(config: DistillConfig) -> PaperShortlist:
    """Load the library-level last paper preview."""

    path = _pointer_path(config)
    if not path.is_file():
        raise PaperShortlistError("No saved paper preview. Pass --topic, or preview a query first.")
    payload = _read_json(path)
    topic = _string(payload, "topic")
    shortlist_id = _string(payload, "id")
    if not topic or not shortlist_id:
        raise PaperShortlistError("The last paper preview pointer is incomplete.")
    return load_topic_shortlist(config, topic, shortlist_id)
