"""Open Knowledge Format export and validation helpers."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import yaml

from distill.config import DistillConfig
from distill.library.paths import (
    _split_frontmatter,
    atomic_write_text,
    dump_frontmatter,
    extract_frontmatter,
    sanitize_topic,
    strip_frontmatter,
)

IssueSeverity = Literal["error", "warning"]

_RESERVED_NAMES = {"index.md", "log.md"}
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+(?:\s[^)]*)?)\)")
_URL_KEYS = ("url", "source_url", "resource", "video_url", "paper_url", "page_url", "repo_url")
_TITLE_KEYS = ("title", "video_title", "paper_title", "page_title", "repo_name", "channel")
_TAG_KEYS = ("tags", "source", "source_type", "topic")


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
    written_docs: list[Path] = []
    for source_file in source_files:
        rel_path = source_file.relative_to(source_root)
        target = output_root / rel_path
        okf_doc = _render_okf_document(
            source_root=source_root,
            source_file=source_file,
            rel_path=rel_path,
            topic=topic_label,
            generated_at=generated_at,
        )
        atomic_write_text(target, okf_doc)
        written_docs.append(target)

    _write_index(output_root, topic_label, source_root, written_docs, generated_at)
    _write_log(output_root, topic_label, source_root, len(written_docs), generated_at)

    validation = validate_okf_bundle(output_root)
    return OkfExportResult(
        output_dir=output_root,
        source_root=source_root,
        topic=topic_label,
        files_written=len(written_docs) + 2,
        validation=validation,
    )


def _parse_frontmatter(
    text: str,
    rel_path: str,
    errors: list[OkfIssue],
    *,
    require_frontmatter: bool,
) -> dict[str, Any] | None:
    block, _ = _split_frontmatter(text)
    if block is None:
        if require_frontmatter:
            errors.append(OkfIssue("error", rel_path, "Missing YAML frontmatter"))
        return None
    try:
        data = yaml.safe_load(block) or {}
    except yaml.YAMLError as exc:
        errors.append(OkfIssue("error", rel_path, f"Invalid YAML frontmatter: {exc}"))
        return None
    if not isinstance(data, dict):
        errors.append(OkfIssue("error", rel_path, "Frontmatter must be a YAML mapping"))
        return None
    return data


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


def _render_okf_document(
    *,
    source_root: Path,
    source_file: Path,
    rel_path: Path,
    topic: str,
    generated_at: str,
) -> str:
    source_text = source_file.read_text(encoding="utf-8")
    native_meta = extract_frontmatter(source_text)
    body = strip_frontmatter(source_text).strip()
    title = _title_for(source_file, native_meta)
    concept_type = _type_for(source_file, native_meta)
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
    return "\n".join(sections).rstrip() + "\n"


def _write_index(
    output_root: Path,
    topic: str,
    source_root: Path,
    written_docs: list[Path],
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
        "## Concepts",
        "",
    ]
    if not written_docs:
        lines.append("- No Markdown concepts were available in the source corpus.")
    for doc in sorted(written_docs):
        rel = doc.relative_to(output_root).as_posix()
        lines.append(f"- [{doc.stem.replace('_', ' ')}]({rel})")
    lines.append("")
    atomic_write_text(output_root / "index.md", "\n".join(lines))


def _write_log(
    output_root: Path,
    topic: str,
    source_root: Path,
    concept_count: int,
    generated_at: str,
) -> None:
    frontmatter = {
        "okf_version": "0.1",
        "title": f"Distill OKF log: {topic}",
        "timestamp": generated_at,
    }
    content = "\n".join(
        [
            dump_frontmatter(frontmatter),
            "",
            "# Log",
            "",
            f"- {generated_at}: Exported {concept_count} concept documents from `{source_root}`.",
            "",
        ]
    )
    atomic_write_text(output_root / "log.md", content)


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


def _type_for(source_file: Path, native_meta: dict[str, str]) -> str:
    if concept_type := native_meta.get("okf_type"):
        return concept_type
    if source_file.name.upper() in {"AGENTS.MD", "CLAUDE.MD"}:
        return "Agent Orientation"
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
