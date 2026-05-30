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

from distill.concepts import recovery
from distill.concepts.contradictions import find_contested
from distill.concepts.exports import concepts_jsonl_path, entities_jsonl_path
from distill.library.paths import strip_frontmatter
from distill.mcp import server as _server
from distill.mcp.tools.find import _resolve_within_library

__all__: list[str] = []


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


@_server.mcp.tool()
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
    config = _server._config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    rows = _read_jsonl(concepts_jsonl_path(topic_dir)) + _read_jsonl(entities_jsonl_path(topic_dir))

    if contested_only:
        rows = [r for r in rows if r.get("contested")]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in r.get("name", "").lower()]

    # Sort: source_count desc, then alphabetically by slug for stable order
    rows.sort(key=lambda r: (-r.get("source_count", 0), r.get("slug", "")))
    rows = rows[:limit]

    results = []
    for r in rows:
        is_entity = r.get("kind") in {"person", "organization", "vendor"}
        path = f"topics/{topic}/{'entities' if is_entity else 'concepts'}/{r.get('slug', '')}.md"
        results.append(
            {
                "path": path,
                "name": r.get("name", ""),
                "kind": r.get("kind", ""),
                "source_count": r.get("source_count", 0),
                "helpful_count": r.get("helpful_count", 0),
                "harmful_count": r.get("harmful_count", 0),
                "contested": bool(r.get("contested")),
            }
        )

    return json.dumps({"results": results, "count": len(results), "topic": topic}, indent=2)


@_server.mcp.tool()
def read_concept(path: str) -> str:
    """Read concept playbook markdown by relative library path.

    Args:
        path: Relative path from library root (e.g. ``topics/tkg/concepts/rotational_embedding.md``).
    """
    config = _server._config()
    full_path = _resolve_within_library(config.library_dir, path)

    if full_path is None:
        return json.dumps(
            {"status": "error", "error": "Path must be a relative path inside the library root."},
            indent=2,
        )
    if not full_path.is_file():
        return json.dumps({"status": "error", "error": f"Path not found: {path}"}, indent=2)
    # SECURITY: enforce the *library-relative* layout, not absolute-path parts.
    # An earlier version did substring checks on the unnormalized path string
    # (bypassed by ``concepts/../secret.md``); the replacement inspected
    # ``full_path.parts`` (bypassed when ``library_dir`` itself sits under an
    # ancestor named ``concepts`` or ``entities`` -- e.g. a user configured
    # ``DISTILL_OUTPUT_DIR=/home/alice/concepts/library``, which makes every
    # library file's absolute parts contain "concepts" and pass the guard).
    # ``_resolve_within_library`` keeps the read inside ``library_dir``, but
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

    try:
        raw = full_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return json.dumps({"status": "error", "error": f"Cannot read file: {exc}"}, indent=2)

    return json.dumps({"path": path, "content": strip_frontmatter(raw)}, indent=2)


@_server.mcp.tool()
def list_contested(topic: str, limit: int = 20) -> str:
    """List contested concepts and entities for a topic (both polarities present).

    Args:
        topic: Topic name.
        limit: Max rows.
    """
    config = _server._config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)
    items = find_contested(topic_dir)[:limit]
    return json.dumps(
        {"contested": [c.to_dict() for c in items], "count": len(items), "topic": topic},
        indent=2,
    )


@_server.mcp.tool()
def concept_history(topic: str, slug: str) -> str:
    """List history snapshots for a concept/entity note, newest first.

    Each step summarizes what changed (source deltas, evidence-interval
    shifts, contested flips) moving forward to the next-newer version.

    Args:
        topic: Topic name.
        slug: Concept/entity slug (the note's filename stem).
    """
    config = _server._config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    snapshots = recovery.list_snapshots(topic_dir, slug)
    live_path = recovery.note_path_for_slug(topic_dir, slug)
    if live_path is None and not snapshots:
        return json.dumps(
            {"status": "error", "error": f"No note for slug '{slug}' in topic '{topic}'."},
            indent=2,
        )

    newer_fields = (
        recovery.parse_note_fields(live_path.read_text(encoding="utf-8"))
        if live_path is not None
        else None
    )
    newer_label = "current"
    steps = []
    for snap in reversed(snapshots):
        snap_fields = recovery.parse_note_fields(snap.path.read_text(encoding="utf-8"))
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


@_server.mcp.tool()
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
    config = _server._config()
    topic_dir = config.topic_dir(topic)
    if not topic_dir.exists():
        return json.dumps({"status": "error", "error": f"Topic '{topic}' not found."}, indent=2)

    live_path = recovery.note_path_for_slug(topic_dir, slug)
    snapshots = recovery.list_snapshots(topic_dir, slug)
    if live_path is None and not snapshots:
        return json.dumps(
            {"status": "error", "error": f"No note for slug '{slug}' in topic '{topic}'."},
            indent=2,
        )

    def _resolve(ts: str) -> recovery.Snapshot | None:
        return recovery.resolve_snapshot(topic_dir, slug, ts)

    if ts_a and ts_b:
        a, b = _resolve(ts_a), _resolve(ts_b)
        if a is None or b is None:
            missing = ts_a if a is None else ts_b
            return json.dumps(
                {"status": "error", "error": f"No snapshot matching '{missing}'."}, indent=2
            )
        diff = recovery.diff_notes(
            a.path.read_text(encoding="utf-8"),
            b.path.read_text(encoding="utf-8"),
            old_label=a.iso,
            new_label=b.iso,
        )
    else:
        if live_path is None:
            return json.dumps(
                {"status": "error", "error": "No live note; pass two timestamps."}, indent=2
            )
        if ts_a:
            old = _resolve(ts_a)
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
        diff = recovery.diff_notes(
            old.path.read_text(encoding="utf-8"),
            live_path.read_text(encoding="utf-8"),
            old_label=old.iso,
            new_label="current",
        )

    return json.dumps(
        {
            "topic": topic,
            "slug": slug,
            "old": diff.old_label,
            "new": diff.new_label,
            "sources_added": diff.sources_added,
            "sources_removed": diff.sources_removed,
            "sources_repolarized": [
                {"source_id": sid, "from": old_pol, "to": new_pol}
                for sid, old_pol, new_pol in diff.sources_repolarized
            ],
            "field_changes": [
                {"field": c.field, "old": c.old, "new": c.new} for c in diff.field_changes
            ],
            "body_diff": diff.body_diff,
        },
        indent=2,
    )
