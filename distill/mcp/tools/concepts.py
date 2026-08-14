# pyright: strict
"""MCP tools for the 0.8 concept playbook: find_concepts, read_concept.

Mirrors the find_insights / read_insight JIT-retrieval pattern. Returns
ranked previews rather than full file payloads so agents pull the
playbook .md by name only when they need the body. The roadmap's
"token-efficient tool descriptions" constraint applies here: docstrings
are short and stay focused on the agent-facing contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from distill.concepts import recovery
from distill.concepts.exports import concepts_jsonl_path, entities_jsonl_path
from distill.library.confined import list_confined_files, read_confined_text, validate_confined_path
from distill.library.paths import extract_frontmatter, strip_frontmatter
from distill.mcp.server import READ_TOOL_ANNOTATIONS, load_config, mcp, resolve_within_library
from distill.parsing import strict_json_loads

__all__: list[str] = []

type ConceptJsonRow = dict[str, Any]
type ConceptSearchRow = dict[str, str | int | bool]
type ConceptHistoryRow = dict[str, str | None]
type ConceptRepolarizedRow = dict[str, str]
type ConceptFieldChangeRow = dict[str, Any]
type DiffSelection = tuple[Path, Path, str, str]

_MAX_CONCEPT_FILE_BYTES = 8 * 1024 * 1024
_MAX_CONCEPT_DIRECTORY_ENTRIES = 4096
_MAX_COLLISION_SCAN_BYTES = 16 * 1024 * 1024
_MAX_HISTORY_SNAPSHOTS = 512
_MAX_CONCEPT_RESULTS = 100


def _read_confined_text(path: Path, root: Path) -> str | None:
    return read_confined_text(path, root, max_bytes=_MAX_CONCEPT_FILE_BYTES)


def _is_confined_topic_dir(topic_dir: Path, library_dir: Path) -> bool:
    return validate_confined_path(topic_dir, library_dir, expect_directory=True) is not None


def _read_jsonl(path: Path, library_dir: Path) -> list[ConceptJsonRow]:
    content = _read_confined_text(path, library_dir)
    if content is None:
        return []
    rows: list[ConceptJsonRow] = []
    for line in content.splitlines():
        line = line.strip()
        if line:
            try:
                decoded = strict_json_loads(line)
            except (RecursionError, ValueError):
                continue
            if isinstance(decoded, dict):
                rows.append(cast("ConceptJsonRow", decoded))
    return rows


def _row_str(row: ConceptJsonRow, key: str) -> str:
    value = row.get(key, "")
    return value if isinstance(value, str) else ""


def _row_int(row: ConceptJsonRow, key: str) -> int:
    value = row.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _row_bool(row: ConceptJsonRow, key: str) -> bool:
    value = row.get(key)
    return value if isinstance(value, bool) else False


def _read_topic_note(path: Path, topic_dir: Path, library_dir: Path) -> str | None:
    """Read a regular note whose lexical path remains inside its trusted topic."""

    try:
        relative = path.relative_to(topic_dir)
    except ValueError:
        return None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    return _read_confined_text(path, library_dir)


def _is_safe_slug(slug: str) -> bool:
    from distill.library.paths import is_safe_path_slug

    return is_safe_path_slug(slug)


def _list_confined_markdown_paths(
    directory: Path,
    library_dir: Path,
    *,
    max_files: int,
) -> list[Path] | None:
    """Enumerate a bounded regular-file directory without trusting its entries."""

    return list_confined_files(
        directory,
        library_dir,
        suffix=".md",
        max_entries=_MAX_CONCEPT_DIRECTORY_ENTRIES,
        max_files=max_files,
        max_file_bytes=_MAX_CONCEPT_FILE_BYTES,
    )


def _find_canonical_note_path(
    topic_dir: Path,
    slug: str,
    library_dir: Path,
) -> tuple[Path | None, bool]:
    for subdirectory in ("concepts", "entities"):
        candidate = topic_dir / subdirectory / f"{slug}.md"
        content = _read_topic_note(candidate, topic_dir, library_dir)
        if content is not None:
            return candidate, False
        try:
            candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return None, True
        return None, True
    return None, False


def _find_collision_note_path(
    topic_dir: Path,
    slug: str,
    library_dir: Path,
) -> tuple[Path | None, bool]:
    """Scan collision names within a total byte and directory-entry budget."""

    scanned_bytes = 0
    for subdirectory in ("concepts", "entities"):
        paths = _list_confined_markdown_paths(
            topic_dir / subdirectory,
            library_dir,
            max_files=_MAX_CONCEPT_DIRECTORY_ENTRIES,
        )
        if paths is None:
            return None, True
        for path in paths:
            content = _read_topic_note(path, topic_dir, library_dir)
            if content is None:
                return None, True
            scanned_bytes += len(content.encode("utf-8"))
            if scanned_bytes > _MAX_COLLISION_SCAN_BYTES:
                return None, True
            if extract_frontmatter(content).get("slug") == slug:
                return path, False
    return None, False


def _find_confined_note_path(
    topic_dir: Path,
    slug: str,
    library_dir: Path,
) -> tuple[Path | None, bool]:
    """Find a live note using only confined reads; return an unsafe flag."""

    if not _is_safe_slug(slug):
        return None, False
    canonical, unsafe = _find_canonical_note_path(topic_dir, slug, library_dir)
    if canonical is not None or unsafe:
        return canonical, unsafe
    return _find_collision_note_path(topic_dir, slug, library_dir)


def _list_confined_snapshots(
    topic_dir: Path,
    slug: str,
    library_dir: Path,
) -> list[recovery.Snapshot] | None:
    if not _is_safe_slug(slug):
        return []
    paths = _list_confined_markdown_paths(
        recovery.history_dir_for_slug(topic_dir, slug),
        library_dir,
        max_files=_MAX_HISTORY_SNAPSHOTS,
    )
    if paths is None:
        return None
    snapshots = [
        recovery.Snapshot(
            slug=slug,
            safe_ts=path.stem,
            iso=recovery.safe_ts_to_iso(path.stem),
            path=path,
        )
        for path in paths
    ]
    snapshots.sort(key=lambda snapshot: snapshot.safe_ts)
    return snapshots


def _resolve_snapshot(
    snapshots: list[recovery.Snapshot],
    timestamp: str,
) -> recovery.Snapshot | None:
    wanted = timestamp.strip().removesuffix(".md")
    wanted_safe = recovery.iso_to_safe_ts(wanted)
    return next(
        (
            snapshot
            for snapshot in snapshots
            if wanted in {snapshot.safe_ts, snapshot.iso} or wanted_safe == snapshot.safe_ts
        ),
        None,
    )


def _unsafe_note_response() -> str:
    return json.dumps(
        {"status": "error", "error": "Note path is unsafe or unreadable."},
        indent=2,
    )


@mcp.tool(annotations=READ_TOOL_ANNOTATIONS)
def find_concepts(
    topic: str,
    query: str = "",
    kind: str = "",
    contested_only: bool = False,
    limit: int = 20,
) -> str:
    """Search topic concept playbook; return ranked rows.

    Args:
        topic: Topic name to search within.
        query: Optional substring filter on concept name (case-insensitive).
        kind: Optional kind filter: technique/architecture/dataset/metric/person/organization/vendor.
        contested_only: Restrict to concepts where both helpful and harmful evidence exist.
        limit: Max rows to return.
    """
    config = load_config()
    topic_dir = config.topic_dir(topic)
    if not _is_confined_topic_dir(topic_dir, config.library_dir):
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    if isinstance(limit, bool) or limit < 1:
        return json.dumps(
            {"status": "error", "error": "limit must be a positive integer."},
            indent=2,
        )
    limit = min(limit, _MAX_CONCEPT_RESULTS)

    rows = _read_jsonl(concepts_jsonl_path(topic_dir), config.library_dir) + _read_jsonl(
        entities_jsonl_path(topic_dir), config.library_dir
    )

    if contested_only:
        rows = [r for r in rows if _row_bool(r, "contested")]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in _row_str(r, "name").lower()]

    # Sort: source_count desc, then alphabetically by slug for stable order
    rows.sort(key=lambda r: (-_row_int(r, "source_count"), _row_str(r, "slug")))
    rows = rows[:limit]

    results: list[ConceptSearchRow] = []
    for r in rows:
        kind_value = _row_str(r, "kind")
        is_entity = kind_value in {"person", "organization", "vendor"}
        slug = _row_str(r, "slug")
        path = f"topics/{topic}/{'entities' if is_entity else 'concepts'}/{slug}.md"
        results.append(
            {
                "path": path,
                "name": _row_str(r, "name"),
                "kind": kind_value,
                "source_count": _row_int(r, "source_count"),
                "helpful_count": _row_int(r, "helpful_count"),
                "harmful_count": _row_int(r, "harmful_count"),
                "contested": _row_bool(r, "contested"),
            }
        )

    return json.dumps({"results": results, "count": len(results), "topic": topic}, indent=2)


@mcp.tool(annotations=READ_TOOL_ANNOTATIONS)
def read_concept(path: str) -> str:
    """Read concept playbook markdown by relative library path.

    Args:
        path: Relative path from library root (e.g. ``topics/tkg/concepts/rotational_embedding.md``).
    """
    config = load_config()
    full_path = resolve_within_library(config.library_dir, path)

    if full_path is None:
        return json.dumps(
            {"status": "error", "error": "Path must be a relative path inside the library root."},
            indent=2,
        )
    # SECURITY: enforce the *library-relative* layout, not absolute-path parts.
    # An earlier version did substring checks on the unnormalized path string
    # (bypassed by ``concepts/../secret.md``); the replacement inspected
    # ``full_path.parts`` (bypassed when ``library_dir`` itself sits under an
    # ancestor named ``concepts`` or ``entities`` -- e.g. a user configured
    # ``DISTILL_OUTPUT_DIR=/home/alice/concepts/library``, which makes every
    # library file's absolute parts contain "concepts" and pass the guard).
    # ``resolve_within_library`` keeps the read inside ``library_dir``, but
    # this tool's contract is narrower: only ``topics/<topic>/(concepts|entities)/<file>.md``.
    try:
        relative_parts = full_path.relative_to(config.library_dir.resolve(strict=False)).parts
    except ValueError:
        return json.dumps(
            {"status": "error", "error": "Path is not a concept or entity note."},
            indent=2,
        )
    if (
        len(relative_parts) != 4
        or relative_parts[0] != "topics"
        or relative_parts[2] not in {"concepts", "entities"}
        or not relative_parts[3].endswith(".md")
    ):
        return json.dumps(
            {"status": "error", "error": "Path is not a concept or entity note."},
            indent=2,
        )

    lexical_path = config.library_dir.joinpath(*Path(path).parts)
    raw = _read_confined_text(lexical_path, config.library_dir)
    if raw is None:
        return json.dumps(
            {"status": "error", "error": "Cannot read concept or entity note."},
            indent=2,
        )

    return json.dumps({"path": path, "content": strip_frontmatter(raw)}, indent=2)


# NOTE: there is deliberately no separate list-contested tool. Contested-only
# retrieval is `find_concepts(topic, contested_only=True)` -- the dedicated
# wrapper was removed in 0.9.30 because every always-loaded tool schema costs
# the consuming agent context before any work happens, and a strict duplicate
# bought nothing.


@mcp.tool(annotations=READ_TOOL_ANNOTATIONS)
def concept_history(topic: str, slug: str) -> str:
    """List history snapshots for a concept/entity note, newest first.

    Each step summarizes what changed (source deltas, evidence-interval
    shifts, contested flips) moving forward to the next-newer version.

    Args:
        topic: Topic name.
        slug: Concept/entity slug (the note's filename stem).
    """
    config = load_config()
    topic_dir = config.topic_dir(topic)
    if not _is_confined_topic_dir(topic_dir, config.library_dir):
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    snapshots = _list_confined_snapshots(topic_dir, slug, config.library_dir)
    live_path, unsafe_note = _find_confined_note_path(topic_dir, slug, config.library_dir)
    if snapshots is None or unsafe_note:
        return _unsafe_note_response()
    if live_path is None and not snapshots:
        return json.dumps(
            {"status": "error", "error": f"No note for slug '{slug}' in topic '{topic}'."},
            indent=2,
        )

    live_text = (
        _read_topic_note(live_path, topic_dir, config.library_dir)
        if live_path is not None
        else None
    )
    if live_path is not None and live_text is None:
        return _unsafe_note_response()
    newer_fields = recovery.parse_note_fields(live_text) if live_text is not None else None
    newer_label = "current"
    steps: list[ConceptHistoryRow] = []
    for snap in reversed(snapshots):
        snap_text = _read_topic_note(snap.path, topic_dir, config.library_dir)
        if snap_text is None:
            return _unsafe_note_response()
        snap_fields = recovery.parse_note_fields(snap_text)
        steps.append(
            {
                "timestamp": snap.iso,
                "replaced_by": newer_label if newer_fields is not None else None,
                "change": (
                    recovery.summarize_transition(snap_fields, newer_fields)
                    if newer_fields is not None
                    else None
                ),
            }
        )
        newer_label = snap.iso
        newer_fields = snap_fields

    return json.dumps(
        {
            "topic": topic,
            "slug": slug,
            "has_live_note": live_path is not None,
            "snapshot_count": len(snapshots),
            "history": steps,
        },
        indent=2,
    )


def _select_diff_versions(
    topic: str,
    slug: str,
    live_path: Path | None,
    snapshots: list[recovery.Snapshot],
    ts_a: str,
    ts_b: str,
) -> DiffSelection | str:
    if ts_a and ts_b:
        a = _resolve_snapshot(snapshots, ts_a)
        b = _resolve_snapshot(snapshots, ts_b)
        if a is None or b is None:
            missing = ts_a if a is None else ts_b
            return json.dumps(
                {"status": "error", "error": f"No snapshot matching '{missing}'."}, indent=2
            )
        return (a.path, b.path, a.iso, b.iso)
    if live_path is None:
        return json.dumps(
            {"status": "error", "error": "No live note; pass two timestamps."}, indent=2
        )
    if ts_a:
        old = _resolve_snapshot(snapshots, ts_a)
        if old is None:
            return json.dumps(
                {"status": "error", "error": f"No snapshot matching '{ts_a}'."}, indent=2
            )
    elif snapshots:
        old = snapshots[-1]
    else:
        return json.dumps(
            {
                "topic": topic,
                "slug": slug,
                "message": "No history snapshots yet; nothing to diff.",
            },
            indent=2,
        )
    return (old.path, live_path, old.iso, "current")


def _read_diff(
    selection: DiffSelection,
    topic_dir: Path,
    library_dir: Path,
) -> recovery.NoteDiff | None:
    old_path, new_path, old_label, new_label = selection
    old_text = _read_topic_note(old_path, topic_dir, library_dir)
    new_text = _read_topic_note(new_path, topic_dir, library_dir)
    if old_text is None or new_text is None:
        return None
    return recovery.diff_notes(old_text, new_text, old_label=old_label, new_label=new_label)


@mcp.tool(annotations=READ_TOOL_ANNOTATIONS)
def concept_diff(topic: str, slug: str, ts_a: str = "", ts_b: str = "") -> str:
    """Diff a concept note across versions; return a structured delta.

    No timestamps: most recent snapshot vs the live note. One timestamp:
    that snapshot vs the live note. Two timestamps: ts_a vs ts_b.

    Args:
        topic: Topic name.
        slug: Concept/entity slug (the note's filename stem).
        ts_a: Optional older snapshot timestamp.
        ts_b: Optional newer snapshot timestamp.
    """
    config = load_config()
    topic_dir = config.topic_dir(topic)
    if not _is_confined_topic_dir(topic_dir, config.library_dir):
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    live_path, unsafe_note = _find_confined_note_path(topic_dir, slug, config.library_dir)
    snapshots = _list_confined_snapshots(topic_dir, slug, config.library_dir)
    if snapshots is None or unsafe_note:
        return _unsafe_note_response()
    if live_path is None and not snapshots:
        return json.dumps(
            {"status": "error", "error": f"No note for slug '{slug}' in topic '{topic}'."},
            indent=2,
        )

    selection = _select_diff_versions(topic, slug, live_path, snapshots, ts_a, ts_b)
    if isinstance(selection, str):
        return selection
    diff = _read_diff(selection, topic_dir, config.library_dir)
    if diff is None:
        return _unsafe_note_response()

    sources_repolarized: list[ConceptRepolarizedRow] = [
        {"source_id": sid, "from": old_pol, "to": new_pol}
        for sid, old_pol, new_pol in diff.sources_repolarized
    ]
    field_changes: list[ConceptFieldChangeRow] = [
        {"field": c.field, "old": c.old, "new": c.new} for c in diff.field_changes
    ]

    return json.dumps(
        {
            "topic": topic,
            "slug": slug,
            "old": diff.old_label,
            "new": diff.new_label,
            "sources_added": diff.sources_added,
            "sources_removed": diff.sources_removed,
            "sources_repolarized": sources_repolarized,
            "field_changes": field_changes,
            "body_diff": diff.body_diff,
        },
        indent=2,
    )
