"""Shared discovery of per-source ``_Insights.md`` files under a topic.

Both the concept playbook layer (``distill.concepts``) and the claim layer
(``distill.claims``) walk a topic directory to find every source insight,
derive a stable ``source_id`` for each, and compute a topic-relative
artifact path for backlinks. That walk lived in ``concepts.pipeline``; it is
lifted here so the two layers share one implementation instead of drifting.

This module is foundational: it imports only ``distill.library.paths`` and
the standard library, so both higher layers can depend on it without an
upward import (enforced by the import-linter foundational-layer contract).
"""

# pyright: strict

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from distill.library.confined import read_confined_text, validate_confined_path
from distill.library.paths import extract_frontmatter, find_artifact, strip_frontmatter

__all__ = [
    "InsightRef",
    "derive_source_id",
    "discover_insights",
    "insight_content_sha256",
    "insight_has_body",
    "insight_verification_binding_is_valid",
    "insight_verification_payload_is_valid",
    "read_discovered_insight",
    "receipt_body_sha256",
    "verify_sidecar_for_insight",
]


# Top-level subdirectories under a topic that hold derived artifacts rather
# than source insights. Any dot-prefixed directory (``.history``, ``.concepts``,
# ``.claims``) is also skipped generically.
_SKIP_TOP_DIRS = {"concepts", "entities"}
_INSIGHT_SUFFIX = "_Insights.md"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class InsightRef:
    """One discovered ``_Insights.md`` ready to extract from.

    Holds enough to populate a downstream record without re-walking the
    filesystem: the on-disk path, the stable ``source_id``, and the
    topic-relative ``artifact_path`` used for wiki-link backlinks.
    """

    path: Path
    source_id: str
    artifact_path: str
    content_sha256: str = ""


def _read_artifact_text(path: Path, root: Path) -> str | None:
    content = read_confined_text(path, root, max_bytes=_MAX_ARTIFACT_BYTES)
    if content is None:
        return None
    return content.replace("\r\n", "\n").replace("\r", "\n")


def insight_has_body(markdown: str) -> bool:
    """Return True when the insight has a non-empty body after frontmatter.

    Write paths use this as a fail-closed gate: analysis that produced only
    YAML, whitespace, or nothing is not a corpus artifact.
    """

    return bool(strip_frontmatter(markdown).strip())


def receipt_body_sha256(content: str) -> str:
    """Return the stable digest used to bind a derived insight to its receipt."""

    body = strip_frontmatter(content).strip()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def insight_content_sha256(content: str) -> str:
    """Hash the complete logical insight text using its UTF-8 representation."""

    logical_content = content.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(logical_content.encode("utf-8")).hexdigest()


def _frontmatter(path: Path, *, root: Path | None = None) -> dict[str, str]:
    content = _read_artifact_text(path, path.parent if root is None else root)
    return extract_frontmatter(content) if content is not None else {}


def _source_id_from_frontmatter(insight_path: Path, frontmatter: dict[str, str]) -> str:
    for key in ("paper_id", "video_id", "page_id", "source_id"):
        if frontmatter.get(key):
            return frontmatter[key]
    return insight_path.parent.name


def derive_source_id(insight_path: Path) -> str:
    """Derive a stable source_id from an insight path.

    Prefers a canonical id from frontmatter (``paper_id`` / ``video_id`` /
    ``page_id`` / ``source_id``); falls back to the slug of the directory
    containing the ``_Insights.md``, which always works without a YAML parse.
    """
    return _source_id_from_frontmatter(insight_path, _frontmatter(insight_path))


def _matches_current_receipt(
    insight_path: Path,
    frontmatter: dict[str, str],
    *,
    root: Path,
) -> bool:
    if frontmatter.get("source") != "github":
        return True
    receipt_name = frontmatter.get("source_receipt")
    expected_digest = frontmatter.get("source_receipt_sha256")
    if receipt_name is not None or expected_digest is not None:
        if not receipt_name or not expected_digest or Path(receipt_name).name != receipt_name:
            return False
        receipt_path = insight_path.parent / receipt_name
        receipt_content = _read_artifact_text(receipt_path, root)
        if receipt_content is None:
            return False
        receipt_frontmatter = extract_frontmatter(receipt_content)
        return (
            receipt_frontmatter.get("receipt_sha256") == expected_digest
            and receipt_body_sha256(receipt_content) == expected_digest
        )

    for receipt_path in insight_path.parent.glob("*_Repo.md"):
        if _frontmatter(receipt_path, root=root).get("receipt_sha256"):
            return False
    return True


def verify_sidecar_for_insight(insight_path: Path) -> Path:
    """Return the canonical or compatible verification sidecar for an insight."""

    identity = insight_path.name.removesuffix(_INSIGHT_SUFFIX)
    return find_artifact(insight_path.parent, "verify", identity=identity, extension="json")


def _insight_content_and_requirement(
    insight_path: Path,
    *,
    root: Path | None = None,
) -> tuple[str, bool] | None:
    content = _read_artifact_text(
        insight_path,
        insight_path.parent if root is None else root,
    )
    if content is None:
        return None
    metadata = extract_frontmatter(content)
    required = metadata.get("verification_required", "").casefold() == "true"
    return content, required


def _verification_payload_matches(
    insight_path: Path,
    content: str,
    required: bool,
    payload: object,
) -> bool:
    if not isinstance(payload, dict):
        return not required
    data = cast("dict[object, object]", payload)
    digest = data.get("insight_sha256")
    if digest is None:
        return not required
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        return False
    return data.get("insight") == insight_path.name and insight_content_sha256(content) == digest


def insight_verification_payload_is_valid(insight_path: Path, payload: object) -> bool:
    """Validate one already-read sidecar payload against exact insight text."""

    insight = _insight_content_and_requirement(insight_path)
    if insight is None:
        return False
    content, required = insight
    return _verification_payload_matches(insight_path, content, required, payload)


def insight_verification_binding_is_valid(
    insight_path: Path,
    *,
    root: Path | None = None,
    require_binding: bool = False,
) -> bool:
    """Fail closed when a required or present content binding does not match."""

    confinement_root = insight_path.parent if root is None else root
    insight = _insight_content_and_requirement(insight_path, root=confinement_root)
    if insight is None:
        return False
    content, required = insight
    return _verification_binding_is_valid_for_content(
        insight_path,
        content,
        required=required or require_binding,
        root=confinement_root,
    )


def _verification_binding_is_valid_for_content(
    insight_path: Path,
    content: str,
    *,
    required: bool,
    root: Path,
) -> bool:
    """Validate a sidecar against the exact content snapshot a caller will use."""

    sidecar = verify_sidecar_for_insight(insight_path)
    if not sidecar.exists():
        return not required
    sidecar_content = _read_artifact_text(sidecar, root)
    if sidecar_content is None:
        return False
    try:
        payload = json.loads(sidecar_content)
    except (json.JSONDecodeError, RecursionError):
        return not required
    return _verification_payload_matches(insight_path, content, required, payload)


def read_discovered_insight(ref: InsightRef, confinement_root: Path) -> str | None:
    """Reread a discovered insight only while its verified content is unchanged."""

    content = _read_artifact_text(ref.path, confinement_root)
    if content is None or insight_content_sha256(content) != ref.content_sha256:
        return None
    return content


def discover_insights(
    topic_dir: Path,
    *,
    validate_verification: bool = True,
    confinement_root: Path | None = None,
) -> list[InsightRef]:
    """Find every ``_Insights.md`` under a topic dir, sorted for determinism.

    Sort order is the topic-relative path. Sorting matters because the order
    insights are processed influences the order of append-only log entries,
    which influences git diffs; determinism keeps those stable across runs.

    Derived-artifact subtrees (``concepts/``, ``entities/``) and any
    dot-prefixed directory (``.history``, ``.concepts``, ``.claims``) are
    skipped so only true source insights are returned.
    """
    if not topic_dir.exists():
        return []
    trusted_root = topic_dir.parent.parent if confinement_root is None else confinement_root
    if validate_confined_path(topic_dir, trusted_root, expect_directory=True) is None:
        return []
    refs: list[InsightRef] = []
    for path in sorted(topic_dir.rglob("*_Insights.md")):
        rel = path.relative_to(topic_dir)
        top = rel.parts[0]
        if top in _SKIP_TOP_DIRS or top.startswith("."):
            continue
        content = _read_artifact_text(path, trusted_root)
        if content is None:
            continue
        frontmatter = extract_frontmatter(content)
        if not _matches_current_receipt(path, frontmatter, root=trusted_root):
            continue
        if validate_verification and not _verification_binding_is_valid_for_content(
            path,
            content,
            required=(
                frontmatter.get("verification_required", "").casefold() == "true"
                or top.casefold() == "answers"
            ),
            root=trusted_root,
        ):
            continue
        refs.append(
            InsightRef(
                path=path,
                source_id=_source_id_from_frontmatter(path, frontmatter),
                artifact_path=str(rel).replace("\\", "/"),
                content_sha256=insight_content_sha256(content),
            )
        )
    return refs
