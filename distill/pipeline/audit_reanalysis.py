"""Safe, structured reanalysis guidance for stale audit artifacts."""

# pyright: strict

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import SplitResult, urlsplit

from distill.library.confined import read_confined_text
from distill.pipeline.audit_records import StalePromptRecord

_MAX_STALE_ARTIFACT_BYTES = 2 * 1024 * 1024
_INGESTABLE_HOSTS = frozenset(
    {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "github.com", "www.github.com"}
)
_ARXIV_HOSTS = frozenset({"arxiv.org", "www.arxiv.org"})


class ReanalysisGuidance(TypedDict, total=False):
    kind: Literal["argv", "manual_review"]
    argv: list[str]
    artifact: str
    recorded_prompt: str
    message: str


def frontmatter_field(text: str, name: str) -> str:
    """Pull one scalar field out of an artifact's frontmatter block, or empty."""

    if not text.startswith("---"):
        return ""
    end = text.find("---", 3)
    if end == -1:
        return ""
    match = re.search(
        rf'^{re.escape(name)}:\s*"?([^"\r\n]+?)"?\s*$',
        text[:end],
        re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def _read_stale_artifact(library_dir: Path, relative_path: str) -> str:
    return (
        read_confined_text(
            library_dir / relative_path,
            library_dir,
            max_bytes=_MAX_STALE_ARTIFACT_BYTES,
        )
        or ""
    )


def _parsed_http_url(url: str) -> SplitResult | None:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return parsed


def _reanalysis_argv(topic: str, source: str, url: str) -> list[str] | None:
    parsed = _parsed_http_url(url)
    if parsed is None:
        return None
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if source == "arxiv" and hostname in _ARXIV_HOSTS:
        path = parsed.path.rstrip("/")
        if path.startswith("/abs/"):
            arxiv_id = path.removeprefix("/abs/")
            if arxiv_id and not any(char.isspace() for char in arxiv_id):
                return ["distill", "papers", arxiv_id, "--topic", topic, "--limit", "1"]
        return None
    is_feed = parsed.path.lower().endswith((".rss", ".xml"))
    if hostname in _INGESTABLE_HOSTS or is_feed:
        return ["distill", "ingest", url, "--topic", topic]
    return None


def reanalysis_guidance(
    library_dir: Path,
    topic: str,
    stale: list[StalePromptRecord],
) -> list[ReanalysisGuidance]:
    """Return inert argument records or explicit manual-review guidance."""

    records: list[ReanalysisGuidance] = []
    for item in stale:
        relative_path = str(item.get("insight", ""))
        text = _read_stale_artifact(library_dir, relative_path)
        argv = _reanalysis_argv(
            topic,
            frontmatter_field(text, "source"),
            frontmatter_field(text, "url"),
        )
        recorded = str(item.get("recorded", "?"))
        if argv is not None:
            records.append({"kind": "argv", "argv": argv, "recorded_prompt": recorded})
        else:
            records.append(
                {
                    "kind": "manual_review",
                    "artifact": relative_path,
                    "recorded_prompt": recorded,
                    "message": "Re-run the artifact's original ingest verb.",
                }
            )
    return records


def reanalysis_argvs(
    library_dir: Path,
    topic: str,
    stale: list[StalePromptRecord],
) -> list[list[str]]:
    """Return executable argument arrays without constructing shell text."""

    return [
        record["argv"]
        for record in reanalysis_guidance(library_dir, topic, stale)
        if record.get("kind") == "argv" and "argv" in record
    ]


def reanalysis_commands(
    library_dir: Path,
    topic: str,
    stale: list[StalePromptRecord],
) -> list[str]:
    """Return deterministic JSON records safe to display as inert guidance."""

    return [
        json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
        for record in reanalysis_guidance(library_dir, topic, stale)
    ]
