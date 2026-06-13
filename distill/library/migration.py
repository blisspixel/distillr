"""Corpus migration tooling — rename legacy artifacts and update wiki-links.

Provides scan and apply functions for migrating pre-0.7 corpora from legacy
filenames (e.g., ``insights.md``, ``synthesis.md``) to the modern naming
convention (``<slug>_Insights.md``), and a 0.8.1 helper that rewrites the
``confidence:`` frontmatter field to ``synthesis_scope:`` for the same
class of pre-existing artifacts.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from distill.library.paths import (
    _ARTIFACT_SUFFIXES,
    _LEGACY_NAMES,
    atomic_write_text,
)

__all__ = [
    "FrontmatterFieldAction",
    "FrontmatterFieldResult",
    "MigrationAction",
    "MigrationResult",
    "apply_frontmatter_field_migration",
    "apply_migration",
    "scan_confidence_field",
    "scan_legacy_artifacts",
]

logger = logging.getLogger(__name__)

# Reverse lookup: legacy filename → artifact type key
# When multiple types share the same legacy filename (e.g., synthesis.md is used
# by both "synthesis" and "site_synthesis"), prefer the shorter/simpler type name.
# We build the dict in reverse order of preference so that preferred entries win.
_REVERSE_LEGACY: dict[str, str] = {}
for _type, _filename in sorted(_LEGACY_NAMES.items(), key=lambda x: -len(x[0])):
    _REVERSE_LEGACY[_filename] = _type


@dataclass(frozen=True, slots=True)
class MigrationAction:
    """A proposed rename or link update."""

    source_path: Path
    target_path: Path
    action_type: str  # "rename" | "link_update"
    details: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Summary of a migration run."""

    files_renamed: int
    links_updated: int
    conflicts_skipped: int
    errors: list[str] = field(default_factory=list)


def _compute_modern_name(legacy_path: Path) -> str:
    """Derive modern filename from legacy path context.

    The parent directory name IS the slug (it was created by slugify_title).
    Maps legacy filename to the modern ``<parent-slug>_<Suffix><ext>`` form.
    """
    parent_name = legacy_path.parent.name
    legacy_filename = legacy_path.name
    artifact_type = _REVERSE_LEGACY.get(legacy_filename)
    if artifact_type is None:
        # Shouldn't happen if called correctly, but be defensive
        return legacy_filename
    suffix = _ARTIFACT_SUFFIXES[artifact_type]
    extension = legacy_path.suffix  # .md or .txt
    return f"{parent_name}_{suffix}{extension}"


def scan_legacy_artifacts(library_dir: Path) -> list[MigrationAction]:
    """Find artifacts using legacy naming and propose renames.

    Scans all files in library_dir recursively, identifies those matching
    legacy naming patterns, and returns a list of proposed MigrationActions.
    """
    actions: list[MigrationAction] = []
    legacy_filenames = set(_LEGACY_NAMES.values())

    for file_path in sorted(library_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.name not in legacy_filenames:
            continue
        # Skip hidden directories (.git, .hypothesis, .distill, etc.)
        if any(part.startswith(".") for part in file_path.relative_to(library_dir).parts[:-1]):
            continue
        # Skip files at the library root (they need a parent slug)
        if file_path.parent == library_dir:
            continue

        modern_name = _compute_modern_name(file_path)
        target_path = file_path.parent / modern_name

        # Skip if already has the modern name (shouldn't happen, but be safe)
        if file_path.name == modern_name:
            continue

        actions.append(
            MigrationAction(
                source_path=file_path,
                target_path=target_path,
                action_type="rename",
                details=f"{file_path.name} → {modern_name}",
            )
        )

    return actions


def apply_migration(
    actions: list[MigrationAction], *, library_dir: Path | None = None
) -> MigrationResult:
    """Execute proposed renames and update wiki-links in referencing files.

    Handles conflicts (target exists → skip) and missing files (source
    disappeared between scan and apply → skip).

    If *library_dir* is provided, wiki-link updates will scan that directory.
    Otherwise, the common ancestor of all action paths is used.
    """
    files_renamed = 0
    links_updated = 0
    conflicts_skipped = 0
    errors: list[str] = []

    # Track old_stem → new_stem for link updates
    stem_remap: dict[str, str] = {}

    for action in actions:
        if action.action_type != "rename":
            continue

        source = action.source_path
        target = action.target_path

        # Check if source still exists
        if not source.exists():
            errors.append(f"Source disappeared: {source}")
            continue

        # Check for conflicts
        if target.exists():
            conflicts_skipped += 1
            logger.info("Conflict: target already exists, skipping: %s", target)
            continue

        # Execute rename
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            files_renamed += 1
            # Record stem mapping for link updates
            old_stem = source.stem
            new_stem = target.stem
            if old_stem != new_stem:
                stem_remap[old_stem] = new_stem
        except OSError as e:
            errors.append(f"Rename failed {source} → {target}: {e}")

    # Update wiki-links in all markdown files in the library
    if stem_remap:
        root = library_dir or _find_library_root(actions)
        if root:
            links_updated = _update_wiki_links(root, stem_remap)

    return MigrationResult(
        files_renamed=files_renamed,
        links_updated=links_updated,
        conflicts_skipped=conflicts_skipped,
        errors=errors,
    )


def _find_library_root(actions: list[MigrationAction]) -> Path | None:
    """Heuristic: find the common ancestor of all action paths."""
    if not actions:
        return None
    # Walk up from the first action's source to find a reasonable root
    paths = [a.source_path for a in actions]
    # Fallback: go up from first action until we find a reasonable root
    candidate = paths[0].parent
    while candidate.parent != candidate:
        # Check if all actions are under this directory
        if all(p.is_relative_to(candidate) for p in paths):
            return candidate
        candidate = candidate.parent
    return paths[0].parent


# ---------------------------------------------------------------------------
# 0.8.1 — confidence: → synthesis_scope: frontmatter rename
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrontmatterFieldAction:
    """A proposed in-place frontmatter field rewrite for one file."""

    path: Path
    old_field: str  # always "confidence" in 0.8.1
    new_field: str  # always "synthesis_scope" in 0.8.1
    value: str


@dataclass(frozen=True, slots=True)
class FrontmatterFieldResult:
    """Summary of a frontmatter-field migration run."""

    files_rewritten: int
    files_skipped: int  # already had new_field, no rewrite needed
    errors: list[str] = field(default_factory=list)


# The emitter writes one key per line via dump_frontmatter: ``key: value``.
# Match a top-level line whose key is exactly ``confidence`` (not
# ``confidence_score`` or some unrelated occurrence) and replace only the
# key part. The match is anchored to line start with the same indentation
# the dumper produces (none) so we don't touch nested-block YAML such as
# ``concept: \n  confidence: ...`` if that ever appears later.
_CONFIDENCE_LINE_RE = re.compile(
    r"^confidence:(?P<sep>\s*)(?P<value>.*)$",
    re.MULTILINE,
)


def _partition_frontmatter(text: str) -> tuple[str, str, str] | None:
    """Split ``---\\n...\\n---\\n<body>`` into (opening, frontmatter, rest).

    Named distinctly from ``library.paths._split_frontmatter`` (which returns a
    2-tuple ``(block_or_none, body)``): this is a different function with a
    different contract -- a 3-way partition that returns ``None`` when absent.

    Returns ``None`` if the file does not start with a frontmatter block.
    ``opening`` is the leading ``---\\n``; ``frontmatter`` is the lines
    between the markers; ``rest`` is the trailing ``---`` plus body.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    return text[:4], text[4 : end + 1], text[end + 1 :]


def scan_confidence_field(library_dir: Path) -> list[FrontmatterFieldAction]:
    """Find ``.md`` files whose frontmatter has ``confidence:`` to rewrite.

    Skips hidden directories (``.git``, ``.distill``, ``.history``, ``.concepts``)
    so versioned snapshots and op artifacts stay untouched -- they're
    immutable history, not live corpus state. Files that already use
    ``synthesis_scope:`` and have no ``confidence:`` are skipped silently;
    they're already on the new schema.
    """
    actions: list[FrontmatterFieldAction] = []

    for md_path in sorted(library_dir.rglob("*.md")):
        if not md_path.is_file():
            continue
        # Skip hidden ancestors (.git, .distill, .history, .concepts, ...)
        if any(part.startswith(".") for part in md_path.relative_to(library_dir).parts):
            continue
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        split = _partition_frontmatter(text)
        if split is None:
            continue
        _, fm_block, _ = split
        match = _CONFIDENCE_LINE_RE.search(fm_block)
        if match is None:
            continue
        actions.append(
            FrontmatterFieldAction(
                path=md_path,
                old_field="confidence",
                new_field="synthesis_scope",
                value=match.group("value").strip(),
            )
        )

    return actions


def apply_frontmatter_field_migration(
    actions: list[FrontmatterFieldAction],
) -> FrontmatterFieldResult:
    """Rewrite ``confidence:`` -> ``synthesis_scope:`` in each action's file.

    Idempotent: if a file already has ``synthesis_scope:`` AND ``confidence:``
    coexisting (from a partial prior run, or from manual edits), the
    ``confidence:`` line is removed rather than producing a duplicate key.
    Per-file writes are best-effort; one failure does not block the others.
    """
    files_rewritten = 0
    files_skipped = 0
    errors: list[str] = []

    for action in actions:
        try:
            text = action.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"Read failed {action.path}: {exc}")
            continue

        split = _partition_frontmatter(text)
        if split is None:
            files_skipped += 1
            continue
        opening, fm_block, rest = split

        # If both fields are present (partial prior run, manual edit),
        # drop the old line entirely rather than emitting a duplicate.
        has_new = re.search(
            rf"^{re.escape(action.new_field)}:",
            fm_block,
            re.MULTILINE,
        )
        if has_new:
            new_fm = _CONFIDENCE_LINE_RE.sub("", fm_block)
            # Collapse a blank line left behind by the deletion.
            new_fm = re.sub(r"\n\n+", "\n", new_fm)
        else:
            new_fm = _CONFIDENCE_LINE_RE.sub(
                rf"{action.new_field}:\g<sep>\g<value>",
                fm_block,
                count=1,
            )

        if new_fm == fm_block:
            files_skipped += 1
            continue

        try:
            atomic_write_text(action.path, opening + new_fm + rest)
            files_rewritten += 1
        except OSError as exc:
            errors.append(f"Write failed {action.path}: {exc}")

    return FrontmatterFieldResult(
        files_rewritten=files_rewritten,
        files_skipped=files_skipped,
        errors=errors,
    )


def _update_wiki_links(library_dir: Path, stem_remap: dict[str, str]) -> int:
    """Update wiki-links in all markdown files to reflect renamed stems."""
    updated_count = 0

    for md_file in library_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Could not read file for link update: %s", md_file)
            continue

        new_content = content
        file_updates = 0
        for old_stem, new_stem in stem_remap.items():
            # Count replacements in original content before modifying
            old_pattern = re.escape(old_stem)
            matches = re.findall(rf"\[\[{old_pattern}([^\]]*)\]\]", new_content)
            file_updates += len(matches)
            # Replace references to old stem in wiki-links
            new_content = re.sub(
                rf"\[\[{old_pattern}([^\]]*)\]\]",
                rf"[[{new_stem}\1]]",
                new_content,
            )

        if new_content != content:
            try:
                atomic_write_text(md_file, new_content)
                updated_count += file_updates
            except OSError:
                logger.warning("Could not write updated links: %s", md_file)

    return updated_count
