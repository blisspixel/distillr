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
    # SECURITY: check the *resolved* path's directory parts, not the raw input.
    # An earlier version did substring checks on the unnormalized path string,
    # which let inputs like ``concepts/../secret.md`` pass the guard while
    # resolving outside the concepts/entities tree. ``_resolve_within_library``
    # keeps the read inside ``library_dir``, but that alone doesn't enforce
    # this tool's narrower contract (concept/entity playbook notes only).
    try:
        resolved_parts = {p.lower() for p in full_path.parts}
    except (OSError, ValueError):
        return json.dumps(
            {"status": "error", "error": "Path is not a concept or entity note."},
            indent=2,
        )
    if not (resolved_parts & {"concepts", "entities"}):
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
