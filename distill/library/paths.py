"""Artifact filename and frontmatter helpers.

Distill keeps source artifacts in nested directories for pipeline ergonomics,
but Markdown filenames need globally descriptive names so Obsidian-style vaults
do not collapse into hundreds of indistinguishable ``insights.md`` notes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "ARTIFACT_SUFFIXES",
    "ProvenanceFields",
    "apply_frontmatter",
    "artifact_exists",
    "artifact_filename",
    "artifact_identity",
    "artifact_path",
    "base_frontmatter",
    "dump_frontmatter",
    "extract_frontmatter",
    "find_artifact",
    "legacy_artifact_path",
    "provenance_frontmatter",
    "read_artifact",
    "resolve_slug_collision",
    "sanitize_path_component",
    "sanitize_topic",
    "site_name_from_url",
    "slugify_title",
    "strip_frontmatter",
    "tags_for",
    "write_markdown_artifact",
    "write_text_artifact",
]

_ARTIFACT_SUFFIXES = {
    "brief": "Brief",
    "content": "Content",
    "corpus_synthesis": "Corpus_Synthesis",
    "insights": "Insights",
    "latest_changes": "Latest_Changes",
    "paper": "Paper",
    "paper_synthesis": "Paper_Synthesis",
    "report": "Report",
    "research": "Research",
    "site_synthesis": "Site_Synthesis",
    "site_update": "Site_Update",
    "synthesis": "Synthesis",
    "topic_synthesis": "Topic_Synthesis",
    "topic_diff": "Topic_Diff",
    "topic_trends": "Topic_Trends",
    "transcript": "Transcript",
    "watch_alerts": "Watch_Alerts",
    "watch_update": "Watch_Update",
}

_LEGACY_NAMES = {
    "brief": "brief.md",
    "content": "content.md",
    "corpus_synthesis": "corpus_synthesis.md",
    "insights": "insights.md",
    "latest_changes": "latest_changes.md",
    "paper": "paper.md",
    "paper_synthesis": "paper_synthesis.md",
    "report": "report.md",
    "research": "research.md",
    "site_synthesis": "synthesis.md",
    "site_update": "site_update.md",
    "synthesis": "synthesis.md",
    "topic_synthesis": "topic_synthesis.md",
    "topic_diff": "topic_diff.md",
    "topic_trends": "topic_trends.md",
    "transcript": "transcript.txt",
    "watch_alerts": "watch_alerts.md",
    "watch_update": "watch_update.md",
}

# Public alias for the artifact suffix map (used by WikiLink and migration tooling)
ARTIFACT_SUFFIXES: dict[str, str] = _ARTIFACT_SUFFIXES

_WINDOWS_RESERVED_CHARS = r'[<>:"/\\|?*]'


# ---------------------------------------------------------------------------
# Provenance dataclass and helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProvenanceFields:
    """Exact generation context for an artifact."""

    model: str
    model_version: str
    temperature: float
    prompt_id: str


def provenance_frontmatter(provenance: ProvenanceFields) -> dict[str, Any]:
    """Return provenance fields as a frontmatter-ready dict."""
    return {
        "model": provenance.model,
        "model_version": provenance.model_version,
        "temperature": provenance.temperature,
        "prompt_id": provenance.prompt_id,
    }


# ---------------------------------------------------------------------------
# Path / slug utilities (relocated from config.py)
# ---------------------------------------------------------------------------


def slugify_title(title: str, source_id: str = "", max_len: int = 60) -> str:
    """Convert a title or label to a clean directory name.

    Determinism guarantee: same (title, source_id) → same slug, always.
    Cross-platform: no Windows reserved chars, no trailing dots/spaces, ≤255 bytes.
    """
    slug = title.lower()
    slug = re.sub(r"[''`]", "", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    # Avoid Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    _WINDOWS_RESERVED_NAMES = frozenset(
        {"con", "prn", "aux", "nul"}
        | {f"com{i}" for i in range(1, 10)}
        | {f"lpt{i}" for i in range(1, 10)}
    )
    if slug in _WINDOWS_RESERVED_NAMES:
        slug = f"_{slug}"
    if source_id:
        # Sanitize source_id: lowercase, keep only [a-z0-9], truncate to 8
        clean_id = re.sub(r"[^a-z0-9]", "", source_id[:8].lower())
        if clean_id:
            slug = f"{slug}_{clean_id}"
    return slug or "untitled"


def sanitize_path_component(value: str) -> str:
    """Make a human-readable filesystem-safe path segment.

    This is primarily needed for Windows-invalid names like
    'AI News & Strategy Daily | Nate B Jones'.
    """
    cleaned = re.sub(_WINDOWS_RESERVED_CHARS, "-", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned or "untitled"


def sanitize_topic(value: str) -> str:
    """Sanitize a topic so it is always a single safe directory component.

    Untrusted callers (MCP tools, CLI flags) can pass values like ``../../etc``
    or ``/tmp/x``. This collapses path separators, rejects traversal-only
    segments, and falls back to ``"untitled"`` rather than letting the path
    join escape the topics root.
    """
    if not isinstance(value, str):
        return "untitled"
    # Strip leading dots so values like ``.env`` or ``..foo`` cannot point at
    # hidden parent-directory neighbours when used as a directory component.
    pre = value.lstrip(".") if value else ""
    cleaned = sanitize_path_component(pre)
    if cleaned == "untitled":
        return "untitled"
    return cleaned


def site_name_from_url(url: str) -> str:
    """Derive a readable site identifier from a URL host."""
    host = urlparse(url).netloc.lower()
    host = host.removeprefix("www.")
    return sanitize_path_component(host or "site")


def resolve_slug_collision(
    target_dir: Path,
    slug: str,
    source_type: str,
    source_id: str,
) -> str:
    """Append disambiguating suffix if slug already maps to a different source.

    Checks whether *slug* already exists in *target_dir* for a different
    (source_type, source_id) pair. If so, appends ``_2``, ``_3``, etc. until
    a unique slug is found.
    """
    candidate = slug
    counter = 1
    while True:
        candidate_path = target_dir / candidate
        if not candidate_path.exists():
            # No collision — slug is available
            return candidate
        # Check if the existing directory belongs to the same source
        meta_file = candidate_path / ".source_meta.json"
        if meta_file.exists():
            try:
                import json as _json

                meta = _json.loads(meta_file.read_text(encoding="utf-8"))
                if meta.get("source_type") == source_type and meta.get("source_id") == source_id:
                    # Same source — reuse the slug
                    return candidate
            except (OSError, ValueError):
                pass
        # Different source or unreadable meta — try next suffix
        counter += 1
        candidate = f"{slug}_{counter}"


def artifact_identity(*parts: str | None) -> str:
    """Build a filesystem-safe identity stem from meaningful context parts."""
    cleaned_parts = [_filename_stem(part or "") for part in parts if part]
    return "_".join(part for part in cleaned_parts if part) or "untitled"


def artifact_filename(identity: str, artifact_type: str, *, extension: str = "md") -> str:
    suffix = _ARTIFACT_SUFFIXES.get(artifact_type, artifact_type.title().replace("-", "_"))
    stem = artifact_identity(identity)
    return f"{stem}_{suffix}.{extension.lstrip('.')}"


def artifact_path(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
) -> Path:
    """Return the modern, Obsidian-friendly artifact path for a directory."""
    return directory / artifact_filename(
        identity or directory.name, artifact_type, extension=extension
    )


def legacy_artifact_path(directory: Path, artifact_type: str) -> Path:
    return directory / _LEGACY_NAMES[artifact_type]


def find_artifact(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
) -> Path:
    """Return the modern artifact if present, otherwise the legacy path.

    The returned path may not exist. New callers should write to
    :func:`artifact_path`; readers should use this helper so older libraries
    continue to work.
    """
    modern = artifact_path(directory, artifact_type, identity=identity, extension=extension)
    if modern.exists():
        return modern
    legacy = legacy_artifact_path(directory, artifact_type)
    if legacy.exists():
        return legacy
    return modern


def artifact_exists(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
) -> bool:
    return find_artifact(directory, artifact_type, identity=identity, extension=extension).exists()


def read_artifact(
    directory: Path,
    artifact_type: str,
    *,
    identity: str | None = None,
    extension: str = "md",
    encoding: str = "utf-8",
) -> str:
    return find_artifact(
        directory, artifact_type, identity=identity, extension=extension
    ).read_text(encoding=encoding)


def write_text_artifact(
    directory: Path,
    artifact_type: str,
    content: str,
    *,
    identity: str | None = None,
    extension: str = "md",
    encoding: str = "utf-8",
) -> Path:
    path = artifact_path(directory, artifact_type, identity=identity, extension=extension)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=encoding)
    return path


def write_markdown_artifact(
    directory: Path,
    artifact_type: str,
    content: str,
    *,
    identity: str | None = None,
    frontmatter: Mapping[str, Any] | None = None,
) -> Path:
    if frontmatter:
        content = apply_frontmatter(content, frontmatter)
    return write_text_artifact(directory, artifact_type, content, identity=identity)


def apply_frontmatter(content: str, frontmatter: Mapping[str, Any]) -> str:
    """Replace any existing frontmatter with a normalized YAML block."""
    existing = {
        key: value
        for key, value in extract_frontmatter(content).items()
        if key not in {"paper_title", "video_title", "page_title"}
    }
    merged = {**existing, **dict(frontmatter)}
    body = strip_frontmatter(content).lstrip()
    return dump_frontmatter(merged) + "\n\n" + body.rstrip() + "\n"


def extract_frontmatter(content: str) -> dict[str, str]:
    """Extract simple scalar YAML frontmatter without adding a YAML dependency."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    data: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"')
        if key:
            data[key] = value
    return data


def strip_frontmatter(content: str) -> str:
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


def dump_frontmatter(frontmatter: Mapping[str, Any]) -> str:
    lines = ["---"]
    for key, value in frontmatter.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        lines.append(f"{_yaml_key(str(key))}: {_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def base_frontmatter(
    *,
    artifact_type: str,
    title: str,
    topic: str = "",
    source: str = "",
    source_id: str = "",
    url: str = "",
    date: str = "",
    authors: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    confidence: str = "",
    extra: Mapping[str, Any] | None = None,
    provenance: ProvenanceFields | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": title,
        "type": artifact_type,
        "topic": topic,
        "source": source,
        "source_id": source_id,
        "url": url,
        "date": date,
        "authors": list(authors or []),
        "tags": list(tags or []),
        "confidence": confidence,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        for key, value in extra.items():
            if key not in data or data[key] in ("", [], {}):
                data[key] = value
    if provenance:
        prov_dict = provenance_frontmatter(provenance)
        for key, value in prov_dict.items():
            if key not in data or data[key] in ("", [], {}):
                data[key] = value
    return data


def tags_for(topic: str = "", *parts: str) -> list[str]:
    tags: list[str] = []
    if topic:
        tags.append(f"distill/{artifact_identity(topic)}")
    for part in parts:
        if part:
            tags.append(f"source/{artifact_identity(part)}")
    return tags


def _filename_stem(value: str) -> str:
    cleaned = value.replace("&", " and ")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "untitled"


def _yaml_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", key)


def _yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return "[" + ", ".join(_yaml_value(item) for item in value) + "]"
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return json.dumps(str(value), ensure_ascii=False)
