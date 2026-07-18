"""Open Knowledge Format export and validation helpers."""

# pyright: strict

from __future__ import annotations

import math
import os
import re
import secrets
import shutil
import stat
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import unquote, urlparse

import yaml

from distill.config import DistillConfig
from distill.library.confined import read_confined_text, validate_confined_path
from distill.library.paths import (
    atomic_write_text,
    dump_frontmatter,
    extract_frontmatter,
    sanitize_topic,
    split_frontmatter,
    strip_frontmatter,
)
from distill.library.wikilinks import WIKI_LINK_PATTERN
from distill.parsing import read_bounded_json_object, read_bounded_jsonl_objects

IssueSeverity = Literal["error", "warning"]

_MAX_OKF_SOURCE_BYTES = 16 * 1024 * 1024
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
_MAX_PROFILE_STATE_BYTES = 10 * 1024 * 1024
_MAX_COST_LOG_BYTES = 8 * 1024 * 1024
_MAX_COST_LOG_ROWS = 10_000


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_positive_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


@dataclass(frozen=True, slots=True)
class OkfValidationLimits:
    """Deterministic work ceilings for one OKF tree validation."""

    max_entries: int = 50_000
    max_files: int = 10_000
    max_file_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_tree_depth: int = 64
    max_yaml_depth: int = 64
    max_links_per_file: int = 4_096
    max_issues: int = 2_000
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        integer_limits: tuple[object, ...] = (
            self.max_entries,
            self.max_files,
            self.max_file_bytes,
            self.max_total_bytes,
            self.max_tree_depth,
            self.max_yaml_depth,
            self.max_links_per_file,
            self.max_issues,
        )
        if any(not _is_positive_integer(value) for value in integer_limits):
            raise ValueError("OKF validation integer limits must be positive integers")
        if not _is_positive_finite_number(self.timeout_seconds):
            raise ValueError("OKF validation timeout must be finite and positive")


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


def validate_okf_bundle(  # noqa: C901 - validation keeps every budget stop explicit
    root: Path,
    *,
    limits: OkfValidationLimits | None = None,
) -> OkfValidationResult:
    """Validate an OKF bundle directory.

    The validator enforces the structural OKF v0.1 requirements Distill relies
    on: every non-reserved Markdown file has parseable YAML frontmatter and a
    non-empty ``type`` field. Broken Markdown links are warnings so consumers can
    accept partially built bundles while still surfacing cleanup work.
    """

    limits = limits or OkfValidationLimits()
    errors: list[OkfIssue] = []
    warnings: list[OkfIssue] = []
    root = Path(root)
    deadline = time.monotonic() + limits.timeout_seconds

    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        errors.append(OkfIssue("error", str(root), "Bundle path does not exist"))
        return OkfValidationResult(root=root, files_checked=0, errors=tuple(errors), warnings=())
    except OSError:
        errors.append(OkfIssue("error", str(root), "Bundle path is unreadable"))
        return OkfValidationResult(root=root, files_checked=0, errors=tuple(errors), warnings=())
    if stat.S_ISLNK(root_stat.st_mode) or (hasattr(root, "is_junction") and root.is_junction()):
        errors.append(OkfIssue("error", str(root), "Bundle path must not be a symbolic link"))
        return OkfValidationResult(root=root, files_checked=0, errors=tuple(errors), warnings=())
    if not stat.S_ISDIR(root_stat.st_mode):
        errors.append(OkfIssue("error", str(root), "Bundle path is not a directory"))
        return OkfValidationResult(root=root, files_checked=0, errors=tuple(errors), warnings=())

    root_index = root / "index.md"
    root_log = root / "log.md"
    try:
        root_index.lstat()
    except OSError:
        warnings.append(OkfIssue("warning", "index.md", "Root index.md is missing"))
    try:
        root_log.lstat()
    except OSError:
        warnings.append(OkfIssue("warning", "log.md", "Root log.md is missing"))

    md_files, traversal_error = _bounded_okf_markdown_files(root, limits, deadline)
    if traversal_error is not None:
        errors.append(OkfIssue("error", str(root), traversal_error))
        return OkfValidationResult(
            root=root, files_checked=0, errors=tuple(errors), warnings=tuple(warnings)
        )

    files_checked = 0
    for md_file in md_files:
        if time.monotonic() > deadline:
            errors.append(OkfIssue("error", str(root), "OKF validation deadline exceeded"))
            break
        rel = _display_path(root, md_file)
        if md_file.is_symlink() or (hasattr(md_file, "is_junction") and md_file.is_junction()):
            errors.append(OkfIssue("error", rel, "Markdown file is a symbolic link"))
            continue
        text = read_confined_text(md_file, root, max_bytes=limits.max_file_bytes)
        if text is None:
            errors.append(OkfIssue("error", rel, "Markdown file is unsafe or unreadable"))
            continue
        files_checked += 1
        meta = _parse_frontmatter(
            text,
            rel,
            errors,
            require_frontmatter=md_file.name not in _RESERVED_NAMES,
            max_yaml_depth=limits.max_yaml_depth,
        )

        if md_file.name not in _RESERVED_NAMES and meta is not None:
            concept_type = meta.get("type")
            if not isinstance(concept_type, str) or not concept_type.strip():
                errors.append(OkfIssue("error", rel, "Frontmatter must include a non-empty type"))

        if md_file.name in _RESERVED_NAMES and meta is None and text.startswith("---"):
            errors.append(OkfIssue("error", rel, "Reserved file frontmatter is not parseable"))

        link_error = _collect_link_warnings(
            root,
            md_file,
            text,
            warnings,
            max_links=limits.max_links_per_file,
            max_issues=limits.max_issues,
            deadline=deadline,
        )
        if link_error is not None:
            errors.append(OkfIssue("error", rel, link_error))
            break
        if len(errors) + len(warnings) >= limits.max_issues:
            errors.append(OkfIssue("error", str(root), "OKF validation issue limit exceeded"))
            break

    return OkfValidationResult(
        root=root,
        files_checked=files_checked,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _bounded_okf_markdown_files(  # noqa: C901 - one bounded no-follow tree walk
    root: Path,
    limits: OkfValidationLimits,
    deadline: float,
) -> tuple[list[Path], str | None]:
    files: list[Path] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    entries_seen = 0
    total_bytes = 0

    while stack:
        if time.monotonic() > deadline:
            return files, "OKF validation deadline exceeded"
        directory, depth = stack.pop()
        entries: list[os.DirEntry[str]] = []
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    entries_seen += 1
                    if entries_seen > limits.max_entries:
                        return files, f"OKF validation entry limit exceeded ({limits.max_entries})"
                    entries.append(entry)
        except OSError:
            return files, f"Cannot scan bundle directory: {_display_path(root, directory)}"
        for entry in sorted(entries, key=lambda item: item.name.casefold(), reverse=True):
            if time.monotonic() > deadline:
                return files, "OKF validation deadline exceeded"
            path = directory / entry.name
            try:
                if entry.is_symlink():
                    if entry.name.casefold().endswith(".md"):
                        if len(files) >= limits.max_files:
                            return files, f"OKF validation file limit exceeded ({limits.max_files})"
                        files.append(path)
                    else:
                        return files, f"Symbolic link encountered: {_display_path(root, path)}"
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > limits.max_tree_depth:
                        return files, f"OKF validation tree depth exceeds {limits.max_tree_depth}"
                    if validate_confined_path(path, root, expect_directory=True) is None:
                        return files, f"Unsafe bundle directory: {_display_path(root, path)}"
                    stack.append((path, depth + 1))
                    continue
                if not entry.name.casefold().endswith(".md"):
                    continue
                file_stat = entry.stat(follow_symlinks=False)
            except OSError:
                return files, f"Cannot inspect bundle entry: {_display_path(root, path)}"
            if not stat.S_ISREG(file_stat.st_mode):
                return files, f"Markdown path is not a regular file: {_display_path(root, path)}"
            if len(files) >= limits.max_files:
                return files, f"OKF validation file limit exceeded ({limits.max_files})"
            if file_stat.st_size > limits.max_file_bytes:
                return (
                    files,
                    f"OKF validation per-file byte limit exceeded ({limits.max_file_bytes})",
                )
            total_bytes += file_stat.st_size
            if total_bytes > limits.max_total_bytes:
                return (
                    files,
                    f"OKF validation aggregate byte limit exceeded ({limits.max_total_bytes})",
                )
            files.append(path)

    files.sort(key=lambda path: path.relative_to(root).as_posix().casefold())
    return files, None


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
    if validate_confined_path(source_root, config.library_dir, expect_directory=True) is None:
        msg = f"Source topic path is unsafe: {source_root}"
        raise ValueError(msg)

    output_root = _okf_output_root(config, output_name)
    staging_root = output_root.with_name(f".{output_root.name}.staging-{secrets.token_hex(8)}")
    source_files = _collect_markdown_sources(source_root)
    stem_index = _build_stem_index(source_root, source_files)
    _replace_output_dir(config, staging_root)
    try:
        generated_at = utc_now_iso()
        index_entries: list[tuple[str, str, str]] = []
        written_docs: list[Path] = []
        for source_file in source_files:
            rel_path = source_file.relative_to(source_root)
            target = staging_root / rel_path
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
        _write_index(staging_root, topic_label, source_root, index_entries, generated_at)
        _write_log(
            staging_root,
            topic_label,
            source_root,
            len(written_docs),
            generated_at,
            history=history,
        )
        _write_llms_txt(staging_root, topic_label, len(written_docs))

        staged_validation = validate_okf_bundle(staging_root)
        if not staged_validation.ok:
            details = "; ".join(issue.message for issue in staged_validation.errors[:3])
            raise ValueError(f"Generated OKF bundle failed validation: {details}")
        _publish_staged_output(config, staging_root, output_root)
    except BaseException:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
        raise

    validation = OkfValidationResult(
        root=output_root,
        files_checked=staged_validation.files_checked,
        errors=staged_validation.errors,
        warnings=staged_validation.warnings,
    )
    return OkfExportResult(
        output_dir=output_root,
        source_root=source_root,
        topic=topic_label,
        files_written=len(written_docs) + 3,
        validation=validation,
    )


class _DepthLimitedSafeLoader(yaml.SafeLoader):
    """PyYAML safe loader with a hard compose-depth ceiling."""

    def __init__(self, stream: str, *, max_depth: int) -> None:
        super().__init__(stream)
        self._max_depth = max_depth
        self._compose_depth = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        self._compose_depth += 1
        try:
            if self._compose_depth > self._max_depth:
                raise yaml.YAMLError(f"YAML nesting exceeds {self._max_depth}")
            return super().compose_node(parent, index)
        finally:
            self._compose_depth -= 1


def _load_bounded_yaml(block: str, *, max_depth: int) -> object:
    loader = _DepthLimitedSafeLoader(block, max_depth=max_depth)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()  # pyright: ignore[reportUnknownMemberType] - PyYAML stubs omit return type


def _parse_frontmatter(
    text: str,
    rel_path: str,
    errors: list[OkfIssue],
    *,
    require_frontmatter: bool,
    max_yaml_depth: int,
) -> dict[str, Any] | None:
    block, _ = split_frontmatter(text)
    if block is None:
        if require_frontmatter:
            errors.append(OkfIssue("error", rel_path, "Missing YAML frontmatter"))
        return None
    try:
        data: object = _load_bounded_yaml(block, max_depth=max_yaml_depth) or {}
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
    *,
    max_links: int,
    max_issues: int,
    deadline: float,
) -> str | None:
    for index, match in enumerate(_MARKDOWN_LINK_RE.finditer(text), start=1):
        if index > max_links:
            return f"Markdown link limit exceeded ({max_links})"
        if time.monotonic() > deadline:
            return "OKF validation deadline exceeded"
        raw_target = match.group(1)
        candidate = _resolve_markdown_link(root, source_file, raw_target)
        if candidate is None:
            continue
        rel = _display_path(root, source_file)
        if candidate == "escape":
            warnings.append(OkfIssue("warning", rel, f"Markdown link escapes bundle: {raw_target}"))
        elif (
            isinstance(candidate, Path)
            and validate_confined_path(candidate, root, expect_directory=False) is None
        ):
            warnings.append(OkfIssue("warning", rel, f"Broken Markdown link: {raw_target}"))
        if len(warnings) >= max_issues:
            return "OKF validation issue limit exceeded"
    return None


def _resolve_markdown_link(root: Path, source_file: Path, raw_target: str) -> Path | str | None:
    target = raw_target.strip()
    if target.startswith("#"):
        return None
    clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if "\x00" in clean or "\\" in clean:
        return "escape"
    if re.match(r"^[A-Za-z]:", clean):
        return "escape"
    parsed = urlparse(clean)
    if parsed.scheme or parsed.netloc:
        return None
    if not clean.lower().endswith(".md"):
        return None
    parts = tuple(part for part in PurePosixPath(clean).parts if part != "/")
    if not parts or any(part in {"", ".", ".."} or ":" in part for part in parts):
        return "escape"
    base = root if clean.startswith("/") else source_file.parent
    candidate = base.joinpath(*parts)
    try:
        candidate.relative_to(root)
    except ValueError:
        return "escape"
    return candidate


def _collect_markdown_sources(source_root: Path) -> list[Path]:
    ignored_names = {"index.md", "log.md"}
    files: list[Path] = []
    for path in source_root.rglob("*.md"):
        if path.name in ignored_names:
            continue
        if any(part.startswith(".") for part in path.relative_to(source_root).parts):
            continue
        if validate_confined_path(path, source_root, expect_directory=False) is None:
            msg = f"Refusing unsafe OKF source path: {path.relative_to(source_root)}"
            raise ValueError(msg)
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
    source_text = read_confined_text(source_file, source_root, max_bytes=_MAX_OKF_SOURCE_BYTES)
    if source_text is None:
        msg = f"Refusing unsafe or unreadable OKF source: {rel_path}"
        raise ValueError(msg)
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
    rows = read_bounded_jsonl_objects(
        cost_log,
        max_bytes=_MAX_COST_LOG_BYTES,
        max_rows=_MAX_COST_LOG_ROWS,
    )
    for row in rows:
        command = str(row.get("command", ""))
        metadata = row.get("metadata")
        metadata_topic = (
            cast("dict[str, object]", metadata).get("topic") if isinstance(metadata, dict) else None
        )
        if topic not in command.split() and row.get("topic") != topic and metadata_topic != topic:
            continue
        when = str(row.get("timestamp", row.get("started_at", ""))).strip()
        if when:
            entries.append((when, f"Cost log: {command}"))
    return entries[-_MAX_LOG_HISTORY:]


def _read_json_object(path: Path) -> dict[str, Any] | None:
    data = read_bounded_json_object(path, max_bytes=_MAX_PROFILE_STATE_BYTES)
    return cast("dict[str, Any]", data) if data else None


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
    output_parent, resolved_output = _validated_output_root(config, output_root)
    if output_root.exists():
        if validate_confined_path(resolved_output, output_parent, expect_directory=True) is None:
            raise ValueError(f"Refusing unsafe output directory: {resolved_output}")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def _validated_output_root(config: DistillConfig, candidate: Path) -> tuple[Path, Path]:
    output_parent = (config.library_dir.parent / "output").resolve()
    resolved = candidate.resolve()
    if resolved.parent != output_parent:
        raise ValueError(f"Refusing output outside {output_parent}: {resolved}")
    return output_parent, resolved


def _publish_staged_output(
    config: DistillConfig,
    staging_root: Path,
    output_root: Path,
) -> None:
    """Publish a validated staging bundle while retaining a recoverable prior copy."""

    output_parent, resolved_staging = _validated_output_root(config, staging_root)
    _, resolved_output = _validated_output_root(config, output_root)
    if validate_confined_path(resolved_staging, output_parent, expect_directory=True) is None:
        raise ValueError(f"Refusing unsafe staging directory: {resolved_staging}")
    backup_root = output_root.with_name(f".{output_root.name}.previous")
    _, resolved_backup = _validated_output_root(config, backup_root)
    if backup_root.exists():
        if validate_confined_path(resolved_backup, output_parent, expect_directory=True) is None:
            raise ValueError(f"Refusing unsafe backup directory: {resolved_backup}")
        if output_root.exists():
            shutil.rmtree(backup_root)
        else:
            backup_root.rename(output_root)
    if output_root.exists():
        if validate_confined_path(resolved_output, output_parent, expect_directory=True) is None:
            raise ValueError(f"Refusing unsafe output directory: {resolved_output}")
        output_root.rename(backup_root)
    try:
        staging_root.rename(output_root)
    except OSError:
        if backup_root.exists() and not output_root.exists():
            backup_root.rename(output_root)
        raise
    if backup_root.exists():
        shutil.rmtree(backup_root, ignore_errors=True)


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
