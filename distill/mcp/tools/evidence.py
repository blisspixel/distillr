# pyright: strict
"""Snapshot-bound evidence for MCP search and read handoffs.

The digest covers normalized Markdown text. It is not a hash of an original
PDF, media file, or remote response. Missing fields stay unknown. Nothing
here is a verified or current badge.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, cast

from distill.config import DistillConfig
from distill.library.confined import read_confined_text
from distill.library.freshness import CLAIMS_DERIVED_DIRTY, collect_synthesis_freshness
from distill.library.insights import (
    insight_content_sha256,
    receipt_body_sha256,
    verify_sidecar_for_insight,
)
from distill.library.paths import (
    artifact_filename,
    extract_frontmatter,
    legacy_artifact_path,
)
from distill.library.verify_sidecar import parse_verify_sidecar
from distill.pipeline.search import classify_artifact

LOGICAL_DIGEST_MEANING = (
    "SHA-256 of the complete logical Markdown after CR and CRLF are normalized "
    "to LF. This is not a hash of the original PDF, media, or remote bytes."
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION_SUFFIX = re.compile(r"v[1-9][0-9]*$")
_RECEIPT_BYTES = 1 * 1024 * 1024
_SYNTHESIS_KINDS = (
    "topic_synthesis",
    "site_synthesis",
    "corpus_synthesis",
    "paper_synthesis",
)
_IDENTITY_FIELDS = (
    "type",
    "title",
    "source",
    "source_id",
    "paper_id",
    "video_id",
    "page_id",
    "url",
)
_PRODUCER_FIELDS = ("model", "model_version", "prompt_id", "temperature")
_DATE_FIELDS = ("date", "generated_at", "updated_at")
_DATE_MEANINGS = {
    "date": "Date recorded on the artifact. It is not proof of upstream currency.",
    "generated_at": "Stamp written when this artifact was generated.",
    "updated_at": "Revision time recorded on the artifact, when present.",
}


def expected_digest_is_valid(value: str) -> bool:
    """Return whether a caller-supplied digest is 64 lowercase hex characters."""

    return _SHA256.fullmatch(value) is not None


def evidence_for_snapshot(
    config: DistillConfig,
    relative_path: str,
    full_path: Path,
    raw: str,
) -> dict[str, object]:
    """Describe one already-read artifact without copying its body or frontmatter."""

    frontmatter = extract_frontmatter(raw)
    library_root = config.library_dir
    relative = full_path.relative_to(library_root)
    artifact_type, origin = classify_artifact(full_path, relative, frontmatter)
    digest = insight_content_sha256(raw)
    return {
        "content_sha256": digest,
        "content_sha256_meaning": LOGICAL_DIGEST_MEANING,
        "artifact_type": artifact_type,
        "origin": origin,
        "identity": _selected(frontmatter, _IDENTITY_FIELDS),
        "producer": _producer(frontmatter),
        "dates": _dates(frontmatter),
        "receipt": _receipt(config, full_path, frontmatter),
        "verification": _verification(config, full_path, digest),
        "freshness": _freshness(config, full_path, frontmatter),
        "paper_revision": _paper_revision(frontmatter),
        "snapshot_path": relative_path,
    }


def _selected(frontmatter: dict[str, str], fields: tuple[str, ...]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for field in fields:
        value = frontmatter.get(field, "").strip()
        selected[field] = value if value else "unknown"
    return selected


def _producer(frontmatter: dict[str, str]) -> dict[str, str]:
    producer = _selected(frontmatter, _PRODUCER_FIELDS)
    producer["meaning"] = (
        "Producer fields are copied only when this artifact records them. "
        "Unknown does not mean that no model was used."
    )
    return producer


def _dates(frontmatter: dict[str, str]) -> dict[str, object]:
    recorded: dict[str, object] = {}
    for field in _DATE_FIELDS:
        value = frontmatter.get(field, "").strip()
        recorded[field] = value if value else "unknown"
        recorded[f"{field}_meaning"] = _DATE_MEANINGS[field]
    return recorded


def _sibling_receipt_name(name: str) -> str | None:
    if not name or Path(name).name != name or name in {".", ".."}:
        return None
    return name


def _receipt(
    config: DistillConfig,
    full_path: Path,
    frontmatter: dict[str, str],
) -> dict[str, object]:
    meaning = (
        "A sibling receipt named by frontmatter. Binding compares recorded "
        "digests only. A missing or unbound receipt is not evidence that no "
        "source exists."
    )
    name = frontmatter.get("source_receipt", "").strip()
    expected = frontmatter.get("source_receipt_sha256", "").strip()
    if not name and not expected:
        return {"relationship": "not_recorded", "path": None, "meaning": meaning}
    sibling = _sibling_receipt_name(name)
    if sibling is None:
        return {"relationship": "unbound", "path": None, "meaning": meaning}
    receipt_path = full_path.parent / sibling
    text = read_confined_text(receipt_path, config.library_dir, max_bytes=_RECEIPT_BYTES)
    relative = receipt_path.relative_to(config.library_dir).as_posix()
    if text is None:
        relationship: Literal["missing", "unreadable"] = (
            "missing" if not receipt_path.is_file() else "unreadable"
        )
        return {"relationship": relationship, "path": relative, "meaning": meaning}
    return {
        "relationship": _receipt_relationship(frontmatter, text, expected),
        "path": relative,
        "meaning": meaning,
    }


def _receipt_relationship(frontmatter: dict[str, str], text: str, expected: str) -> str:
    if not expected:
        return "present_unbound"
    source = frontmatter.get("source", "")
    if source == "github":
        receipt_digest = extract_frontmatter(text).get("receipt_sha256", "")
        bound = receipt_digest == expected and receipt_body_sha256(text) == expected
    else:
        bound = insight_content_sha256(text) == expected
    return "bound" if bound else "mismatched"


def _verification(config: DistillConfig, full_path: Path, digest: str) -> dict[str, object]:
    limitation = (
        "A matched binding means the sidecar names this logical snapshot. "
        "It is not semantic verification of the prose and it is not freshness."
    )
    sidecar = verify_sidecar_for_insight(full_path)
    if not sidecar.is_file():
        return _verification_result("absent", None, limitation)
    text = read_confined_text(sidecar, config.library_dir, max_bytes=_RECEIPT_BYTES)
    parsed = _parse_sidecar(text)
    if parsed is None:
        return _verification_result("unreadable", None, limitation)
    recorded, insight_name, checked, status, usable = parsed
    if recorded is None:
        binding = "unbound"
    elif recorded == digest and insight_name == full_path.name:
        binding = "matched"
    else:
        binding = "mismatched"
    return _verification_result(binding, (checked, status, usable), limitation)


def _parse_sidecar(
    text: str | None,
) -> tuple[str | None, str | None, int, str | None, bool] | None:
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return None
    parsed = parse_verify_sidecar(payload)
    if parsed is None or not isinstance(payload, dict):
        return None
    data = cast("dict[object, object]", payload)
    insight_name = data.get("insight")
    return (
        parsed.insight_sha256,
        insight_name if isinstance(insight_name, str) else None,
        parsed.checked,
        parsed.entailment_status,
        parsed.has_usable_coverage,
    )


def _verification_result(
    binding: str,
    coverage: tuple[int, str | None, bool] | None,
    limitation: str,
) -> dict[str, object]:
    if coverage is None:
        checked: int | None = None
        status: str | None = None
        usable = False
    else:
        checked, status, usable = coverage
    return {
        "binding": binding,
        "checked": checked,
        "entailment_status": status if status is not None else "unknown",
        "usable_coverage": usable,
        "limitation": limitation,
    }


def _freshness(
    config: DistillConfig,
    full_path: Path,
    frontmatter: dict[str, str],
) -> dict[str, object]:
    limitation = (
        "Source-relative comparison of recorded synthesis and insight times. "
        "not_stale does not revalidate the upstream and does not choose an interpretation."
    )
    topic = _topic_name(config, full_path)
    if topic is None or full_path.name not in _synthesis_names(config, topic):
        return {
            "status": "not_applicable",
            "basis": "artifact_kind",
            "generated_at_recorded": bool(frontmatter.get("generated_at", "").strip()),
            "limitation": limitation,
        }
    topic_dir = config.topic_dir(topic)
    report = collect_synthesis_freshness(topic_dir, topic)
    name = full_path.name
    stale = next((row for row in report.stale if row.get("synthesis") == name), None)
    if stale is not None:
        behind = stale.get("behind")
        gap_days = stale.get("gap_days")
        return {
            "status": "stale",
            "basis": "source_relative",
            "behind": behind if isinstance(behind, int) else "unknown",
            "gap_days": gap_days if isinstance(gap_days, int) else "unknown",
            "claims_derived_dirty": (topic_dir / CLAIMS_DERIVED_DIRTY).is_file(),
            "limitation": limitation,
        }
    if name in report.unknown:
        return {
            "status": "unknown",
            "basis": "source_relative",
            "claims_derived_dirty": (topic_dir / CLAIMS_DERIVED_DIRTY).is_file(),
            "limitation": limitation,
        }
    return {
        "status": "not_stale",
        "basis": "source_relative",
        "claims_derived_dirty": False,
        "limitation": limitation,
    }


def _topic_name(config: DistillConfig, full_path: Path) -> str | None:
    relative = full_path.relative_to(config.library_dir)
    if len(relative.parts) < 2 or relative.parts[0] != "topics":
        return None
    return relative.parts[1]


def _synthesis_names(config: DistillConfig, topic: str) -> set[str]:
    topic_dir = config.topic_dir(topic)
    names: set[str] = set()
    for kind in _SYNTHESIS_KINDS:
        names.add(artifact_filename(topic, kind))
        names.add(legacy_artifact_path(topic_dir, kind).name)
    return names


def _paper_revision(frontmatter: dict[str, str]) -> dict[str, str]:
    paper_id = frontmatter.get("paper_id", "").strip()
    if not paper_id:
        return {
            "status": "not_recorded",
            "paper_id": "unknown",
            "meaning": "No paper identifier was recorded on this artifact.",
        }
    if _REVISION_SUFFIX.search(paper_id) is None:
        status = "unversioned"
        meaning = (
            "The recorded paper identifier has no revision suffix. "
            "This read does not query the upstream and does not establish "
            "which version is newest."
        )
    else:
        status = "recorded_suffix"
        meaning = (
            "The recorded paper identifier includes a revision suffix. "
            "This read does not query the upstream and does not establish "
            "which version is newest."
        )
    return {"status": status, "paper_id": paper_id, "meaning": meaning}
