# pyright: strict
"""Reuse and history for local source receipt and analysis pairs."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

from distill.library.confined import read_confined_bytes, read_confined_text
from distill.library.confined_state import (
    atomic_write_confined_bytes,
    atomic_write_confined_text,
    ensure_confined_parent,
)
from distill.library.insights import insight_content_sha256, insight_verification_binding_is_valid
from distill.library.locking import exclusive_path_lock
from distill.library.paths import artifact_path, extract_frontmatter
from distill.library.verify_sidecar import ParsedVerifySidecar, parse_verify_sidecar

_MAX_BYTES = 4 * 1024 * 1024


@contextlib.contextmanager
def local_artifact_transaction(directory: Path, root: Path) -> Generator[None]:
    root.mkdir(parents=True, exist_ok=True)
    ensure_confined_parent(directory / ".distill-local-ingest.lock", root, create=True)
    with exclusive_path_lock(
        directory / ".distill-local-ingest.lock",
        timeout_seconds=610,
        timeout_message="Local source ingest is busy",
    ):
        yield


@dataclass(frozen=True)
class LocalReuse:
    path: Path
    coverage: str


def _verification_record(directory: Path, identity: str) -> ParsedVerifySidecar | None:
    sidecar = artifact_path(directory, "verify", identity=identity, extension="json")
    text = read_confined_text(sidecar, directory, max_bytes=_MAX_BYTES)
    try:
        return parse_verify_sidecar(json.loads(text)) if text is not None else None
    except (ValueError, RecursionError):
        return None


def local_verification_scope(directory: Path, identity: str, *, mode: str) -> str:
    if mode == "off":
        return "off; claims not checked"
    parsed = _verification_record(directory, identity)
    if parsed is None:
        return "unknown; verification receipt unavailable"
    if parsed.entailment_status in {"passed", "flagged"}:
        return f"numeric + prose; {len(parsed.flags)} recorded unsupported claim(s)"
    return f"numeric-only; prose not checked; {len(parsed.flags)} recorded unsupported claim(s)"


def reusable_local_insight(
    directory: Path, identity: str, source_text: str, fingerprint: str, *, verify_mode: str
) -> LocalReuse | None:
    insight = artifact_path(directory, "insights", identity=identity)
    receipt = artifact_path(directory, "content", identity=identity)
    content = read_confined_text(insight, directory, max_bytes=_MAX_BYTES)
    source = read_confined_text(receipt, directory, max_bytes=_MAX_BYTES)
    if (
        content is None
        or source is None
        or insight_content_sha256(source) != insight_content_sha256(source_text)
    ):
        return None
    metadata = extract_frontmatter(content)
    if metadata.get("analysis_fingerprint") != fingerprint or metadata.get(
        "source_receipt_sha256"
    ) != insight_content_sha256(source_text):
        return None
    if verify_mode == "off":
        return LocalReuse(insight, "off; claims not checked")
    if not insight_verification_binding_is_valid(insight, root=directory, require_binding=True):
        return None
    parsed = _verification_record(directory, identity)
    if parsed is None or parsed.entailment_status in {"unavailable", "error", "incomplete"}:
        return None
    scope = (
        "numeric + prose"
        if parsed.entailment_status in {"passed", "flagged"}
        else "numeric-only; prose not checked"
    )
    return LocalReuse(insight, f"{scope}; {len(parsed.flags)} recorded unsupported claim(s)")


def archive_local_artifacts(directory: Path, identity: str) -> None:
    files = (
        artifact_path(directory, "content", identity=identity),
        artifact_path(directory, "insights", identity=identity),
        artifact_path(directory, "verify", identity=identity, extension="json"),
    )
    snapshots: dict[str, bytes] = {}
    for path in files:
        if not path.exists():
            continue
        content = read_confined_bytes(path, directory, max_bytes=_MAX_BYTES)
        if content is None:
            raise ValueError("Cannot preserve an unsafe or oversized previous local artifact")
        snapshots[path.name] = content
    if not snapshots:
        return
    manifest = {name: hashlib.sha256(content).hexdigest() for name, content in snapshots.items()}
    encoded = json.dumps(manifest, sort_keys=True)
    generation = hashlib.sha256(encoded.encode()).hexdigest()
    history = directory / ".history" / generation
    for name, content in snapshots.items():
        destination = history / name
        existing = read_confined_bytes(destination, directory, max_bytes=_MAX_BYTES)
        if existing is not None:
            if existing != content:
                raise ValueError("Local history artifact conflicts with its digest")
            continue
        atomic_write_confined_bytes(destination, content, directory, exclusive=True)
    atomic_write_confined_text(history / "manifest.json", encoded, directory)
