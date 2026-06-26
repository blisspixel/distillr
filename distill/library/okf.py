"""Open Knowledge Format export and validation helpers."""

# pyright: strict

from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import unquote, urlparse

import yaml

from distill.config import DistillConfig
from distill.library.paths import (
    atomic_write_text,
    dump_frontmatter,
    extract_frontmatter,
    sanitize_topic,
    split_frontmatter,
    strip_frontmatter,
)
from distill.library.wikilinks import WIKI_LINK_PATTERN

IssueSeverity = Literal["error", "warning"]

_RESERVED_NAMES = {"index.md", "log.md"}
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+(?:\s[^)]*)?)\)")
_URL_KEYS = ("url", "source_url", "resource", "video_url", "paper_url", "page_url", "repo_url")
_TITLE_KEYS = ("title", "video_title", "paper_title", "page_title", "repo_name", "channel")
_TAG_KEYS = ("tags", "source", "source_type", "topic")
_INDEX_TYPE_ORDER: tuple[str, ...] = (
    "Agent Orientation",
    "Source Insight",
    "Source Receipt",
    "Synthesis",
    "Concept Playbook",
    "Entity Playbook",
    "Derived Answer",
    "Audit Report",
    "Report",
    "Brief",
    "Distill Artifact",
)
_MAX_LOG_HISTORY = 20


@dataclass(frozen=True, slots=True)
class OkfIssue:
    """A validation issue found in an OKF bundle."""

    severity: IssueSeverity
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class OkfValidationResult:
    """Validation result for an OKF bundle."""

    root: Path
    files_checked: int
    errors: tuple[OkfIssue, ...]
    warnings: tuple[OkfIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "files_checked": self.files_checked,
            "ok": self.ok,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class OkfExportResult:
    """Result of writing an OKF bundle."""

    output_dir: Path
    source_root: Path
    topic: str
    files_written: int
    validation: OkfValidationResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "source_root": str(self.source_root),
            "topic": self.topic,
            "files_written": self.files_written,
            "validation": self.validation.to_dict(),
        }


def utc_now_iso() -> str:
    """Return a compact UTC timestamp suitable for OKF frontmatter."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_okf_bundle(root: Path) -> OkfValidationResult:
    """Validate an OKF bundle directory.

    The validator enforces the structural OKF v0.1 requirements Distill relies
    on: every non-reserved Markdown file has parseable YAML frontmatter and a
    non-empty ``type`` field. Broken Markdown links are warnings so consumers can
    accept partially built bundles while still surfacing cleanup work.
    """

    errors: list[OkfIssue] = []
    warnings: list[OkfIssue] = []
    root = Path(root)

    if not root.exists():
        errors.append(OkfIssue("error", str(root), "Bundle path does not exist"))
        return OkfValidationResult(root=root, files_checked=0, errors=tuple(errors), warnings=())
    if not root.is_dir():
        errors.append(OkfIssue("error", str(root), "Bundle path is not a directory"))
        return OkfValidationResult(root=root, files_checked=0, errors=tuple(errors), warnings=())

    root_index = root / "index.md"
    root_log = root / "log.md"
    if not root_index.exists():
        warnings.append(OkfIssue("warning", "index.md", "Root index.md is missing"))
    if not root_log.exists():
        warnings.append(OkfIssue("warning", "log.md", "Root log.md is missing"))

    md_files = sorted(path for path in root.rglob("*.md") if path.is_file())
    for md_file in md_files:
        rel = _display_path(root, md_file)
        text = md_file.read_text(encoding="utf-8")
        meta = _parse_frontmatter(
            text, rel, errors, require_frontmatter=md_file.name not in _RESERVED_NAMES
        )

        if md_file.name not in _RESERVED_NAMES and meta is not None:
            concept_type = meta.get("type")
            if not isinstance(concept_type, str) or not concept_type.strip():
                errors.append(OkfIssue("error", rel, "Frontmatter must include a non-empty type"))

        if md_file.name in _RESERVED_NAMES and meta is None and text.startswith("---"):
            errors.append(OkfIssue("error", rel, "Reserved file frontmatter is not parseable"))

        _collect_link_warnings(root, md_file, text, warnings)

    return OkfValidationResult(
        root=root,
        files_checked=len(md_files),
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def export_okf_bundle(config: DistillConfig, topic: str) -> OkfExportResult:
    """Write a read-only OKF projection for one topic or the whole library."""

    normalized_topic = topic.strip() if topic else "all"
    if normalized_topic.lower() == "all":
        source_root = config.topics_dir()
        output_name = "okf-all"
        topic_label = "all"
    else:
        topic_label = normalized_topic
        source_root = config.topic_dir(topic_label)
        output_name = f"okf-{sanitize_topic(topic_label)}"

    if not source_root.exists():
        msg = f"Source topic path does not exist: {source_root}"
        raise FileNotFoundError(msg)

    output_root = _okf_output_root(config, output_name)
    _replace_output_dir(config, output_root)

    generated_at = utc_now_iso()
    source_files = _collect_markdown_sources(source_root)
    stem_index = _build_stem_index(source_root, source_files)
    index_entries: list[tuple[str, str, str]] = []
    written_docs: list[Path] = []
    for source_file in source_files:
        rel_path = source_file.relative_to(source_root)
        target = output_root / rel_path
        okf_doc, concept_type, title = _render_okf_document(
            source_root=source_root,
            source_file=source_file,
            rel_path=rel_path,
            topic=topic_label,
            generated_at=generated_at,
            stem_index=stem_index,
        )
        atomic_write_text(target, okf_doc)
        written_docs.append(target)
        index_entries.append((rel_path.as_posix(), concept_type, title))

    history = _collect_log_history(config, topic_label)
    _write_index(output_root, topic_label, source_root, index_entries, generated_at)
    _write_log(
        output_root,
        topic_label,
        source_root,
        len(written_docs),
        generated_at,
        history=history,
    )
    _write_llms_txt(output_root, topic_label, len(written_docs))

    validation = validate_okf_bundle(output_root)
    return OkfExportResult(
        output_dir=output_root,
        source_root=source_root,
        topic=topic_label,
        files_written=len(written_docs) + 3,
        validation=validation,
    )


def _parse_frontmatter(
    text: str,
    rel_path: str,
    errors: list[OkfIssue],
    *,
    require_frontmatter: bool,
) -> dict[str, Any] | None:
    block, _ = split_frontmatter(text)
    if block is None:
        if require_frontmatter:
            errors.append(OkfIssue("error", rel_path, "Missing YAML frontmatter"))
        return None
    try:
        data: object = yaml.safe_load(block) or {}
    except yaml.YAMLError as exc:
        errors.append(OkfIssue("error", rel_path, f"Invalid YAML frontmatter: {exc}"))
        return None
    if not isinstance(data, dict):
        errors.append(OkfIssue("error", rel_path, "Frontmatter must be a YAML mapping"))
        return None
    return cast("dict[str, Any]", data)


def _collect_link_warnings(
    root: Path,
    source_file: Path,
    text: str,
    warnings: list[OkfIssue],
) -> None:
    for raw_target in _MARKDOWN_LINK_RE.findall(text):
        candidate = _resolve_markdown_link(root, source_file, raw_target)
        if candidate is None:
            continue
        rel = _display_path(root, source_file)
        if candidate == "escape":
            warnings.append(OkfIssue("warning", rel, f"Markdown link escapes bundle: {raw_target}"))
        elif isinstance(candidate, Path) and not candidate.exists():
            warnings.append(OkfIssue("warning", rel, f"Broken Markdown link: {raw_target}"))


def _resolve_markdown_link(root: Path, source_file: Path, raw_target: str) -> Path | str | None:
    target = raw_target.strip()
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or target.startswith("#"):
        return None
    clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not clean.lower().endswith(".md"):
        return None

    if clean.startswith("/"):
        candidate = root / clean.lstrip("/")
    else:
        candidate = source_file.parent / clean

    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return "escape"
    return candidate


def _collect_markdown_sources(source_root: Path) -> list[Path]:
    ignored_names = {"index.md", "log.md"}
    files: list[Path] = []
    for path in source_root.rglob("*.md"):
        if not path.is_file():
            continue
        if path.name in ignored_names:
            continue
        if any(part.startswith(".") for part in path.relative_to(source_root).parts):
            continue
        files.append(path)
    files.sort()
    return files


def _build_stem_index(source_root: Path, source_files: list[Path]) -> dict[str, str]:
    """Map artifact stems to bundle-relative paths for wikilink rewriting."""
    index: dict[str, str] = {}
    for source_file in source_files:
        rel = source_file.relative_to(source_root).as_posix()
        index[source_file.stem] = rel
    return index


def _rewrite_wikilinks(body: str, stem_index: dict[str, str]) -> str:
    """Convert Obsidian wiki-links into bundle-relative Markdown links when possible."""

    def _replace(match: re.Match[str]) -> str:
        slug_portion = match.group(1).strip()
        display = match.group(2)
        display_title = display.strip() if display else slug_portion.replace("_", " ")
        target = stem_index.get(slug_portion)
        if target:
            return f"[{display_title}]({target})"
        return display_title

    return WIKI_LINK_PATTERN.sub(_replace, body)


def _render_okf_document(
    *,
    source_root: Path,
    source_file: Path,
    rel_path: Path,
    topic: str,
    generated_at: str,
    stem_index: dict[str, str],
) -> tuple[str, str, str]:
    source_text = source_file.read_text(encoding="utf-8")
    native_meta = extract_frontmatter(source_text)
    raw_body = strip_frontmatter(source_text).strip()
    title = _title_for(source_file, native_meta)
    concept_type = _type_for(source_file, native_meta, rel_path=rel_path)
    body = _rewrite_wikilinks(raw_body, stem_index) if raw_body else ""
    source_url = _first_value(native_meta, _URL_KEYS)
    verify_sidecar = _verify_sidecar_for(source_file)
    rel_source = rel_path.as_posix()

    frontmatter: dict[str, Any] = {
        "type": concept_type,
        "title": title,
        "description": f"Distill projection of {rel_source}",
        "tags": _tags_for(topic, native_meta, concept_type),
        "timestamp": generated_at,
        "source_path": rel_source,
    }
    if source_url:
        frontmatter["resource"] = source_url
    if native_type := native_meta.get("type"):
        frontmatter["native_type"] = native_type
    if verify_sidecar and verify_sidecar.exists():
        frontmatter["verify_sidecar"] = verify_sidecar.relative_to(source_root).as_posix()

    sections = [dump_frontmatter(frontmatter), "", body or f"# {title}", "", "# Citations", ""]
    sections.append(f"- Distill source artifact: `{rel_source}`")
    if source_url:
        sections.append(f"- Source URL: {source_url}")
    if verify_sidecar and verify_sidecar.exists():
        sections.append(f"- Verify sidecar: `{verify_sidecar.relative_to(source_root).as_posix()}`")
    sections.append("")
    return "\n".join(sections).rstrip() + "\n", concept_type, title


def _write_index(
    output_root: Path,
    topic: str,
    source_root: Path,
    entries: list[tuple[str, str, str]],
    generated_at: str,
) -> None:
    frontmatter = {
        "okf_version": "0.1",
        "title": f"Distill OKF bundle: {topic}",
        "timestamp": generated_at,
        "source_root": str(source_root),
    }
    lines = [
        dump_frontmatter(frontmatter),
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

    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for rel_path, concept_type, title in entries:
        grouped[concept_type].append((rel_path, title))

    ordered_types = [ctype for ctype in _INDEX_TYPE_ORDER if ctype in grouped]
    for concept_type in sorted(grouped):
        if concept_type not in ordered_types:
            ordered_types.append(concept_type)

    for concept_type in ordered_types:
        lines.extend([f"## {concept_type}", ""])
        for rel_path, title in sorted(grouped[concept_type], key=lambda item: item[0]):
            lines.append(f"- [{title}]({rel_path})")
        lines.append("")

    atomic_write_text(output_root / "index.md", "\n".join(lines))


def _collect_log_history(config: DistillConfig, topic: str) -> list[str]:
    """Gather recent profile-run events for OKF log.md chronological history."""
    if topic.lower() == "all":
        return []

    entries = _profile_log_entries(config.library_dir, topic)
    entries.extend(_cost_log_entries(config.library_dir, topic))
    entries.sort(key=lambda item: item[0])
    return [message for _, message in entries[-_MAX_LOG_HISTORY:]]


def _profile_log_entries(library_dir: Path, topic: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    profiles_dir = library_dir / ".distill" / "profiles"
    if not profiles_dir.is_dir():
        return entries

    for state_path in sorted(profiles_dir.glob("*/run_state.json")):
        state = _read_json_object(state_path)
        if state is None or state.get("topic") != topic:
            continue
        profile_name = str(state.get("profile", state_path.parent.name))
        for raw_attempt in state.get("attempts", [])[-_MAX_LOG_HISTORY:]:
            if not isinstance(raw_attempt, dict):
                continue
            attempt = cast("dict[str, Any]", raw_attempt)
            when = str(attempt.get("attempted_at", "")).strip()
            if not when:
                continue
            status = str(attempt.get("status", "unknown")).strip()
            title = str(attempt.get("title", "")).strip() or str(attempt.get("key", ""))
            entries.append((when, f"Profile `{profile_name}`: {status} `{title}`"))
    return entries


def _cost_log_entries(library_dir: Path, topic: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    cost_log = library_dir / ".distill" / "cost_log.jsonl"
    if not cost_log.is_file():
        return entries

    try:
        lines = cost_log.read_text(encoding="utf-8").splitlines()[-_MAX_LOG_HISTORY:]
    except OSError:
        return entries

    for line in lines:
        row = _parse_json_line(line)
        if row is None:
            continue
        command = str(row.get("command", ""))
        if topic not in command and row.get("topic") != topic:
            continue
        when = str(row.get("timestamp", row.get("started_at", ""))).strip()
        if when:
            entries.append((when, f"Cost log: {command}"))
    return entries


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return cast("dict[str, Any]", data) if isinstance(data, dict) else None


def _parse_json_line(line: str) -> dict[str, Any] | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return cast("dict[str, Any]", data) if isinstance(data, dict) else None


def _write_llms_txt(output_root: Path, topic: str, concept_count: int) -> None:
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


def _write_log(
    output_root: Path,
    topic: str,
    source_root: Path,
    concept_count: int,
    generated_at: str,
    *,
    history: list[str],
) -> None:
    frontmatter = {
        "okf_version": "0.1",
        "title": f"Distill OKF log: {topic}",
        "timestamp": generated_at,
    }
    lines = [
        dump_frontmatter(frontmatter),
        "",
        "# Log",
        "",
        f"- {generated_at}: Exported {concept_count} concept documents from `{source_root}`.",
    ]
    for entry in history:
        lines.append(f"- {entry}")
    lines.append("")
    atomic_write_text(output_root / "log.md", "\n".join(lines))


def _okf_output_root(config: DistillConfig, output_name: str) -> Path:
    output_dir = config.library_dir.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / output_name


def _replace_output_dir(config: DistillConfig, output_root: Path) -> None:
    output_parent = (config.library_dir.parent / "output").resolve()
    resolved_output = output_root.resolve()
    if output_root.exists():
        try:
            resolved_output.relative_to(output_parent)
        except ValueError as exc:
            msg = f"Refusing to replace output outside {output_parent}: {resolved_output}"
            raise ValueError(msg) from exc
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def _title_for(source_file: Path, native_meta: dict[str, str]) -> str:
    if title := _first_value(native_meta, _TITLE_KEYS):
        return title
    stem = source_file.stem.replace("_", " ").replace("-", " ").strip()
    return " ".join(part for part in stem.split()) or "Untitled"


def _type_for(
    source_file: Path,
    native_meta: dict[str, str],
    *,
    rel_path: Path | None = None,
) -> str:
    if concept_type := native_meta.get("okf_type"):
        return concept_type
    if source_file.name.upper() in {"AGENTS.MD", "CLAUDE.MD"}:
        return "Agent Orientation"
    if rel_path is not None:
        parts = {part.lower() for part in rel_path.parts}
        if "concepts" in parts:
            return "Concept Playbook"
        if "entities" in parts:
            return "Entity Playbook"
    if native_type := native_meta.get("type"):
        return native_type

    stem = source_file.stem.lower()
    for marker, concept_type in (
        ("audit", "Audit Report"),
        ("synthesis", "Synthesis"),
        ("report", "Report"),
        ("brief", "Brief"),
        ("insights", "Source Insight"),
        ("paper", "Source Receipt"),
        ("content", "Source Receipt"),
        ("transcript", "Source Receipt"),
    ):
        if marker in stem:
            return concept_type
    return "Distill Artifact"


def _tags_for(topic: str, native_meta: dict[str, str], concept_type: str) -> list[str]:
    tags = ["distill", concept_type.lower().replace(" ", "-")]
    if topic and topic != "all":
        tags.append(f"topic:{topic}")
    for key in _TAG_KEYS:
        value = native_meta.get(key, "").strip()
        if not value:
            continue
        if value.startswith("[") and value.endswith("]"):
            for item in value.strip("[]").split(","):
                cleaned = item.strip().strip("\"'")
                if cleaned:
                    tags.append(cleaned)
        else:
            tags.append(value)
    return list(dict.fromkeys(tags))


def _first_value(source: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = source.get(key, "").strip()
        if value:
            return value
    return ""


def _verify_sidecar_for(source_file: Path) -> Path | None:
    stem = source_file.stem
    candidates = [
        source_file.with_name(f"{stem}_Verify.json"),
        source_file.with_name(f"{stem}_verify.json"),
        source_file.with_name("verify.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


@dataclass(frozen=True, slots=True)
class OkfExportStaleness:
    """Structural staleness: native corpus newer than the exported OKF bundle."""

    bundle_dir: Path
    native_mtime: float
    bundle_mtime: float


def okf_bundle_output_dir(library_dir: Path, topic: str) -> Path:
    """Return the default OKF export directory for one topic."""
    return library_dir.parent / "output" / f"okf-{sanitize_topic(topic)}"


def detect_okf_export_staleness(library_dir: Path, topic: str) -> OkfExportStaleness | None:
    """Return staleness when an OKF bundle exists but predates the native corpus."""
    topic_dir = library_dir / "topics" / topic
    if not topic_dir.is_dir():
        return None

    bundle_dir = okf_bundle_output_dir(library_dir, topic)
    if not bundle_dir.is_dir():
        return None

    native_mtime = _newest_markdown_mtime(topic_dir)
    bundle_mtime = _bundle_anchor_mtime(bundle_dir)
    if native_mtime is None or bundle_mtime is None:
        return None
    if native_mtime <= bundle_mtime:
        return None
    return OkfExportStaleness(
        bundle_dir=bundle_dir,
        native_mtime=native_mtime,
        bundle_mtime=bundle_mtime,
    )


def _newest_markdown_mtime(root: Path) -> float | None:
    latest: float | None = None
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        mtime = path.stat().st_mtime
        if latest is None or mtime > latest:
            latest = mtime
    return latest


def _bundle_anchor_mtime(bundle_dir: Path) -> float | None:
    anchors = (bundle_dir / "index.md", bundle_dir / "log.md")
    times = [path.stat().st_mtime for path in anchors if path.is_file()]
    return max(times) if times else None
