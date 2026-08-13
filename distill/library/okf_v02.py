"""OKF v0.2 contract checks and projection metadata helpers."""

# pyright: strict

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

from distill.library.confined import read_confined_text, validate_confined_path
from distill.library.insights import insight_verification_payload_is_valid
from distill.library.paths import atomic_write_text, dump_frontmatter, split_frontmatter
from distill.library.verify_sidecar import ParsedVerifySidecar, parse_verify_sidecar

IssueSeverity = Literal["error", "warning"]

OKF_VERSION = "0.2"
OKF_STATUSES = frozenset({"draft", "stable", "deprecated"})
RESERVED_NAMES = frozenset({"index.md", "log.md"})
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MAX_OKF_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_VERIFY_SIDECAR_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class OkfIssue:
    """A validation issue found in an OKF bundle."""

    severity: IssueSeverity
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class SupplementalFile:
    """One bounded non-concept receipt copied into an OKF bundle."""

    source_path: Path
    relative_path: Path
    content: str


@dataclass(frozen=True, slots=True)
class VerificationProjection:
    """Truthful OKF projection of one Distill verification sidecar."""

    supplemental: SupplementalFile
    parsed: ParsedVerifySidecar | None
    payload: dict[str, object] | None
    status: str
    verified_at: str | None


def _portable_text(content: str) -> str:
    """Normalize copied textual receipts so Windows newlines are not doubled."""

    return content.replace("\r\n", "\n").replace("\r", "\n")


def _is_iso_datetime(value: object) -> bool:
    if isinstance(value, datetime):
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _is_iso_date(value: object) -> bool:
    if isinstance(value, date) and not isinstance(value, datetime):
        return True
    if not isinstance(value, str) or _DATE_RE.fullmatch(value.strip()) is None:
        return False
    try:
        date.fromisoformat(value.strip())
    except ValueError:
        return False
    return True


def _actor_event_is_valid(value: object, *, require_at: bool) -> bool:
    if not isinstance(value, dict):
        return False
    event = cast("dict[object, object]", value)
    actor = event.get("by")
    if not isinstance(actor, str) or not actor.strip():
        return False
    at = event.get("at")
    return (not require_at and at is None) or _is_iso_datetime(at)


def validate_v02_concept_frontmatter(
    meta: dict[str, Any],
    rel: str,
    errors: list[OkfIssue],
    warnings: list[OkfIssue],
) -> None:
    """Check v0.2 optional families without rejecting unknown extensions."""

    generated = meta.get("generated")
    if generated is not None and not _actor_event_is_valid(generated, require_at=False):
        warnings.append(
            OkfIssue("warning", rel, "generated must contain a non-empty by and optional ISO at")
        )

    verified = meta.get("verified")
    if verified is not None:
        events: list[object] = (
            cast("list[object]", verified) if isinstance(verified, list) else [verified]
        )
        if not events or any(not _actor_event_is_valid(event, require_at=True) for event in events):
            warnings.append(
                OkfIssue(
                    "warning", rel, "verified must contain events with non-empty by and ISO at"
                )
            )

    sources = meta.get("sources")
    if sources is not None:
        source_rows = cast("list[object]", sources) if isinstance(sources, list) else []
        valid_sources = isinstance(sources, list) and all(
            isinstance(item, dict)
            and isinstance(cast("dict[object, object]", item).get("resource"), str)
            and bool(cast("str", cast("dict[object, object]", item)["resource"]).strip())
            for item in source_rows
        )
        if not valid_sources:
            warnings.append(
                OkfIssue("warning", rel, "sources must be a list whose entries contain resource")
            )

    status = meta.get("status")
    if status is not None and status not in OKF_STATUSES:
        warnings.append(
            OkfIssue("warning", rel, "status must be draft, stable, or deprecated when present")
        )
    stale_after = meta.get("stale_after")
    if stale_after is not None and not _is_iso_date(stale_after):
        warnings.append(
            OkfIssue("warning", rel, "stale_after must be an absolute ISO date when present")
        )

    if meta.get("type") == "Attested Computation":
        runtime = meta.get("runtime")
        if not isinstance(runtime, str) or not runtime.strip():
            errors.append(
                OkfIssue("error", rel, "Attested Computation frontmatter must include runtime")
            )


def validate_reserved_file(
    root: Path,
    path: Path,
    text: str,
    meta: dict[str, Any] | None,
    rel: str,
    errors: list[OkfIssue],
    warnings: list[OkfIssue],
) -> None:
    """Validate the v0.2 index.md and log.md reserved-file conventions."""

    _block, body = split_frontmatter(text)
    if path.name == "index.md":
        if meta is not None and path != root / "index.md":
            warnings.append(
                OkfIssue("warning", rel, "Only the bundle-root index.md should have frontmatter")
            )
        if path == root / "index.md" and meta is not None:
            declared = meta.get("okf_version")
            if declared is not None and str(declared) != OKF_VERSION:
                warnings.append(
                    OkfIssue(
                        "warning",
                        rel,
                        f"Bundle declares OKF {declared}; validator targets {OKF_VERSION}",
                    )
                )
        return

    if meta is not None:
        warnings.append(OkfIssue("warning", rel, "OKF v0.2 log.md should not have frontmatter"))
    date_headings = re.findall(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE)
    for heading in date_headings:
        if not _is_iso_date(heading):
            errors.append(OkfIssue("error", rel, f"log.md has a non-date section: {heading}"))
    if re.search(r"^\s*[-*]\s+", body, flags=re.MULTILINE) and not date_headings:
        errors.append(
            OkfIssue("error", rel, "log.md entries must be grouped under ISO date headings")
        )


def merge_supplemental_files(
    collected: dict[Path, str],
    supplemental: tuple[SupplementalFile, ...],
) -> None:
    for item in supplemental:
        prior = collected.get(item.relative_path)
        if prior is not None and prior != item.content:
            raise ValueError(f"Conflicting OKF supplemental file: {item.relative_path.as_posix()}")
        collected[item.relative_path] = item.content


def project_verification(
    source_root: Path,
    source_file: Path,
    verify_sidecar: Path | None,
) -> VerificationProjection | None:
    if verify_sidecar is None:
        return None
    if validate_confined_path(verify_sidecar, source_root, expect_directory=False) is None:
        raise ValueError(f"Refusing unsafe OKF verification sidecar: {verify_sidecar}")
    content = read_confined_text(
        verify_sidecar,
        source_root,
        max_bytes=_MAX_VERIFY_SIDECAR_BYTES,
    )
    if content is None:
        raise ValueError(f"Refusing unreadable OKF verification sidecar: {verify_sidecar}")
    supplemental = SupplementalFile(
        source_path=verify_sidecar,
        relative_path=verify_sidecar.relative_to(source_root),
        content=_portable_text(content),
    )

    payload, parsed = _parse_verification_payload(content)
    if payload is None:
        return VerificationProjection(supplemental, None, None, "invalid", None)
    if parsed is None:
        return VerificationProjection(supplemental, None, payload, "invalid", None)
    status, verified_at = _verified_status(source_file, payload, parsed)
    return VerificationProjection(supplemental, parsed, payload, status, verified_at)


def _parse_verification_payload(
    content: str,
) -> tuple[dict[str, object] | None, ParsedVerifySidecar | None]:
    try:
        raw_payload: object = json.loads(content)
    except (json.JSONDecodeError, RecursionError):
        return None, None
    if not isinstance(raw_payload, dict) or not all(
        isinstance(key, str) for key in cast("dict[object, object]", raw_payload)
    ):
        return None, None
    payload = cast("dict[str, object]", raw_payload)
    return payload, parse_verify_sidecar(payload)


def _verified_status(
    source_file: Path,
    payload: dict[str, object],
    parsed: ParsedVerifySidecar,
) -> tuple[str, str | None]:
    if not parsed.has_usable_coverage:
        return "incomplete", None
    if parsed.flags:
        return "flagged", None
    if parsed.insight_sha256 is None or not insight_verification_payload_is_valid(
        source_file, payload
    ):
        return "unbound", None
    verified_at = payload.get("generated_at")
    if not _is_iso_datetime(verified_at):
        return "invalid", None
    return "passed", cast("str", verified_at)


def receipt_candidate(
    source_root: Path,
    source_file: Path,
    raw_name: object,
) -> Path | None:
    if not isinstance(raw_name, str):
        return None
    name = raw_name.strip()
    if (
        not name
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or name.startswith(".")
        or name.casefold() in {*RESERVED_NAMES, "llms.txt"}
    ):
        return None
    candidate = source_file.parent / name
    if (
        candidate == source_file
        or validate_confined_path(candidate, source_root, expect_directory=False) is None
    ):
        return None
    return candidate


def collect_okf_sources(
    *,
    source_root: Path,
    source_file: Path,
    source_files: frozenset[Path],
    native_meta: dict[str, str],
    source_url: str,
    title: str,
    verification: VerificationProjection | None,
) -> tuple[list[dict[str, object]], tuple[SupplementalFile, ...]]:
    sources: list[dict[str, object]] = []
    supplemental: list[SupplementalFile] = []
    seen_resources: set[str] = set()
    if source_url:
        sources.append({"id": "source-url", "resource": source_url, "title": title})
        seen_resources.add(source_url)

    receipt_names: list[object] = [native_meta.get("source_receipt")]
    if verification is not None and verification.payload is not None:
        receipt_names.append(verification.payload.get("source"))
    for raw_name in receipt_names:
        candidate = receipt_candidate(source_root, source_file, raw_name)
        if candidate is None:
            continue
        rel_path = candidate.relative_to(source_root)
        resource = f"/{rel_path.as_posix()}"
        if resource in seen_resources:
            continue
        try:
            modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC).date().isoformat()
        except OSError:
            modified = ""
        entry: dict[str, object] = {
            "id": "source-receipt",
            "resource": resource,
            "title": candidate.name,
        }
        if modified:
            entry["last_modified"] = modified
        sources.append(entry)
        seen_resources.add(resource)
        if candidate not in source_files:
            content = read_confined_text(candidate, source_root, max_bytes=_MAX_OKF_SOURCE_BYTES)
            if content is None:
                raise ValueError(f"Refusing unreadable OKF source receipt: {candidate}")
            supplemental.append(
                SupplementalFile(
                    source_path=candidate,
                    relative_path=rel_path,
                    content=_portable_text(content),
                )
            )
    return sources, tuple(supplemental)


def _verification_frontmatter(
    verification: VerificationProjection,
) -> dict[str, object]:
    receipt_resource = f"/{verification.supplemental.relative_path.as_posix()}"
    metadata: dict[str, object] = {
        "status": verification.status,
        "scope": "recorded-claims",
        "receipt": receipt_resource,
    }
    if verification.parsed is not None:
        metadata["checked"] = verification.parsed.checked
        metadata["flagged"] = len(verification.parsed.flags)
    return metadata


def build_okf_frontmatter(
    *,
    concept_type: str,
    title: str,
    description: str,
    tags: list[str],
    rel_source: str,
    generated_by: str,
    generated_at: str,
    native_meta: dict[str, str],
    native_model: str,
    source_url: str,
    sources: list[dict[str, object]],
    verification: VerificationProjection | None,
) -> dict[str, Any]:
    frontmatter: dict[str, Any] = {
        "type": concept_type,
        "title": title,
        "description": description,
        "tags": tags,
        "generated": {"by": generated_by, "at": generated_at},
        "source_path": rel_source,
    }
    if source_url:
        frontmatter["resource"] = source_url
    if sources:
        frontmatter["sources"] = sources
    if native_type := native_meta.get("type"):
        frontmatter["native_type"] = native_type
    if native_generated_at := native_meta.get("generated_at"):
        frontmatter["native_generated_at"] = native_generated_at
    if native_model:
        frontmatter["native_model"] = native_model
    if (native_status := native_meta.get("status")) and native_status in OKF_STATUSES:
        frontmatter["status"] = native_status
    if (stale_after := native_meta.get("stale_after")) and _is_iso_date(stale_after):
        frontmatter["stale_after"] = stale_after
    if verification is not None:
        frontmatter["distill_verification"] = _verification_frontmatter(verification)
        if verification.verified_at is not None:
            frontmatter["verified"] = [
                {"by": "process:distill-verify", "at": verification.verified_at}
            ]
    return frontmatter


def build_provenance_lines(
    *,
    rel_source: str,
    source_url: str,
    sources: list[dict[str, object]],
    verification: VerificationProjection | None,
) -> list[str]:
    lines = ["# Provenance", "", f"- Native Distill artifact: `{rel_source}`"]
    if source_url:
        lines.append(f"- Source URL: {source_url}")
    for source in sources:
        resource = str(source["resource"])
        if resource.startswith("/"):
            lines.append(f"- Source receipt: [{source['title']}]({resource})")
    if verification is not None:
        resource = f"/{verification.supplemental.relative_path.as_posix()}"
        lines.append(f"- Verification receipt: [JSON sidecar]({resource})")
    return lines


def write_okf_index(
    output_root: Path,
    topic: str,
    entries: list[tuple[str, str, str, str]],
    type_order: tuple[str, ...],
) -> None:
    lines = [
        dump_frontmatter({"okf_version": OKF_VERSION}),
        "",
        f"# Distill OKF Bundle: {topic}",
        "",
        "Progressive disclosure by concept type. Each entry links to one OKF concept document.",
        "",
    ]
    if not entries:
        lines.extend(
            ["## Concepts", "", "- No Markdown concepts were available in the source corpus.", ""]
        )
        atomic_write_text(output_root / "index.md", "\n".join(lines))
        return

    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for rel_path, concept_type, title, description in entries:
        grouped[concept_type].append((rel_path, title, description))
    ordered_types = [concept_type for concept_type in type_order if concept_type in grouped]
    ordered_types.extend(
        sorted(concept_type for concept_type in grouped if concept_type not in ordered_types)
    )
    for concept_type in ordered_types:
        lines.extend([f"## {concept_type}", ""])
        for rel_path, title, description in sorted(grouped[concept_type], key=lambda item: item[0]):
            lines.append(f"- [{title}]({rel_path}) - {description}")
        lines.append("")
    atomic_write_text(output_root / "index.md", "\n".join(lines))


def write_llms_txt(output_root: Path, topic: str, concept_count: int) -> None:
    """Write a thin llms.txt pointer for tools that look for it at bundle root."""

    lines = [
        f"# Distill OKF Bundle: {topic}",
        "> Verified research corpus exported from Distill. Start at index.md.",
        "",
        "## Primary",
        "- [index.md](index.md): typed concept index and bundle navigation",
        "- [log.md](log.md): export and stewardship history",
        "",
        f"Concept documents: {concept_count}",
        "",
    ]
    atomic_write_text(output_root / "llms.txt", "\n".join(lines))


def write_okf_log(
    output_root: Path,
    concept_count: int,
    generated_at: str,
    *,
    history: list[tuple[str, str]],
) -> None:
    events = [
        (
            generated_at,
            f"**Export**: Projected {concept_count} concept documents from the native Distill corpus.",
        ),
        *history,
    ]
    grouped: dict[str, list[str]] = defaultdict(list)
    for timestamp, message in sorted(events, key=lambda item: item[0], reverse=True):
        event_date = timestamp.strip()[:10]
        if _is_iso_date(event_date):
            grouped[event_date].append(message)

    lines = ["# Directory Update Log", ""]
    for event_date in sorted(grouped, reverse=True):
        lines.extend([f"## {event_date}", ""])
        for message in grouped[event_date]:
            lines.append(f"* {message}")
        lines.append("")
    atomic_write_text(output_root / "log.md", "\n".join(lines))
