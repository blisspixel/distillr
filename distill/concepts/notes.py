"""Render concept and entity playbook notes from merged records.

The notes layer is the I/O boundary for the playbook: take a
``MergedConcept`` (pure data) and write the on-disk Markdown file with
YAML frontmatter. Before any overwrite, the previous file content is
snapshot to ``.history/<slug>/<iso-timestamp>.md`` so refresh runs
preserve the version trail.

Routing:

- Concepts (techniques, architectures, datasets, metrics) -> ``concepts/``
- Entities (people, organizations, vendors) -> ``entities/``

Both kinds share the same renderer; only the directory differs.

Backlinks: the ``## Sources`` section emits wiki-links via
``library.wikilinks.emit_wiki_link``. The slug for each backlink is
derived from the source's ``artifact_path`` so an Obsidian backlink
graph stays consistent with the rest of the corpus.
"""

# pyright: strict

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from distill.concepts.records import MergedConcept, Polarity, SourceEvidence
from distill.library.paths import dump_frontmatter

__all__ = [
    "concept_dir_for_topic",
    "entity_dir_for_topic",
    "history_path_for",
    "note_path_for",
    "read_extracted_sources",
    "record_extracted_sources",
    "render_playbook",
    "write_playbook",
]


# ---- path resolution -------------------------------------------------------


def concept_dir_for_topic(topic_dir: Path) -> Path:
    """Return ``<topic_dir>/concepts/``. Does not create."""
    return topic_dir / "concepts"


def entity_dir_for_topic(topic_dir: Path) -> Path:
    """Return ``<topic_dir>/entities/``. Does not create."""
    return topic_dir / "entities"


def note_path_for(topic_dir: Path, concept: MergedConcept) -> Path:
    """Return the on-disk path for a concept or entity note.

    Routing is by ``concept.kind.is_entity``; the filename is
    ``<slug>.md`` so Obsidian-style ``[[slug]]`` links resolve cleanly.

    Slug collision handling lives in ``write_playbook`` rather than here:
    this function returns the *base* path the slug points at; if another
    concept already owns that path with a different ``normalized_name``,
    the writer picks ``<slug>__<n>.md`` (suffix bumping) and the
    ``.normalized_name`` frontmatter field becomes the authoritative
    identity that resolves the collision on subsequent writes.
    """
    parent = (
        entity_dir_for_topic(topic_dir)
        if concept.kind.is_entity
        else concept_dir_for_topic(topic_dir)
    )
    return parent / f"{concept.slug}.md"


def _existing_owner(target: Path) -> str | None:
    """Return the ``normalized_name`` recorded in an existing note's frontmatter, or ``None``.

    Used by collision detection: two distinct concepts can produce the
    same slug, so before overwriting we read the target's frontmatter
    and confirm the existing note belongs to the same logical concept.
    Returns ``None`` if the file doesn't exist or the frontmatter is
    unreadable / missing the field.
    """
    if not target.is_file():
        return None
    try:
        content = target.read_text(encoding="utf-8")
    except OSError:
        return None
    from distill.library.paths import extract_frontmatter

    fm = extract_frontmatter(content)
    name = fm.get("normalized_name", "")
    return name or None


def _resolve_collision(parent: Path, slug: str, normalized_name: str) -> Path:
    """Find a path under ``parent`` that this concept can own, suffix-bumping on collision.

    Algorithm: start at ``<slug>.md``. If unused, take it. If used by
    *this* normalized_name (idempotent re-write), take it. Otherwise
    bump to ``<slug>__2.md``, ``<slug>__3.md``, ... until we find a
    free or self-owned slot. Returns the path to use.
    """
    base = parent / f"{slug}.md"
    owner = _existing_owner(base)
    if owner is None or owner == normalized_name:
        return base
    for n in range(2, 1000):
        candidate = parent / f"{slug}__{n}.md"
        owner = _existing_owner(candidate)
        if owner is None or owner == normalized_name:
            return candidate
    # Pathological: 1000 distinct slug collisions in one topic. Fall
    # back to a name-hash suffix so we still produce a deterministic
    # path rather than raising.
    import hashlib

    digest = hashlib.sha1(normalized_name.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return parent / f"{slug}__{digest}.md"


def history_path_for(topic_dir: Path, concept: MergedConcept, timestamp: str) -> Path:
    """Return the snapshot path under ``.history/<slug>/<timestamp>.md``.

    Snapshots are per-slug so a single concept's history is easy to
    browse; per-topic ``.history`` keeps the layout self-contained.
    Timestamp should be ISO 8601 with second precision, ``:`` swapped to
    ``-`` for filesystem compatibility (Windows can't have ``:`` in
    filenames).
    """
    safe_ts = timestamp.replace(":", "-")
    return topic_dir / ".history" / concept.slug / f"{safe_ts}.md"


# ---- rendering -------------------------------------------------------------


def _build_frontmatter(concept: MergedConcept) -> dict[str, Any]:
    """Map a ``MergedConcept`` to a frontmatter dict.

    Order matters here -- the dict is iterated by ``dump_frontmatter``
    in insertion order, so the most-important fields (type, name, kind,
    evidence) come first. ``sources`` lives at the bottom because it
    can be long.
    """
    fm: dict[str, Any] = {
        "type": "entity" if concept.kind.is_entity else "concept",
        "name": concept.name,
        "slug": concept.slug,
        # normalized_name is the *identity* field for collision detection.
        # Two distinct concepts can hash to the same slug under the lossy
        # canonicalization (e.g. "a b" and "a/b" both -> "a_b"); the writer
        # reads this field back on the next write to decide whether the
        # target file belongs to the same concept (overwrite) or a
        # different one (suffix-bump to "<slug>__2.md", etc).
        "normalized_name": concept.normalized_name,
        "topic": concept.topic,
        "kind": concept.kind.value,
        "source_count": concept.source_count,
        "helpful_evidence": concept.helpful_evidence.to_list(),
        "harmful_evidence": concept.harmful_evidence.to_list(),
        "helpful_count": concept.helpful_evidence.upper,
        "harmful_count": concept.harmful_evidence.upper,
        "contested": concept.contested,
        "first_seen": concept.first_seen,
        "last_seen": concept.last_seen,
        "sources": [s.to_dict() for s in concept.sources],
    }
    for key, value in concept.provenance.items():
        if key not in fm:
            fm[key] = value
    return fm


def _wiki_link(source: SourceEvidence) -> str:
    """Build a wiki-link backlink to an ``_Insights.md`` from a SourceEvidence row.

    The artifact_path stem is what Obsidian resolves -- e.g.
    ``papers/romem/romem_Insights.md`` -> ``[[romem_Insights]]``. We
    don't validate the link target here; the corpus is the source of
    truth and stale links surface in ``distill doctor --links``.
    """
    stem = Path(source.artifact_path).stem
    return f"[[{stem}]]"


def _evidence_section(
    heading: str,
    sources: list[SourceEvidence],
) -> str:
    """Render one evidence section (helpful or harmful) as bullets."""
    if not sources:
        return ""
    lines = [f"## {heading}", ""]
    for source in sources:
        link = _wiki_link(source)
        if source.claim_excerpt:
            lines.append(f"- {link}: {source.claim_excerpt}")
        else:
            lines.append(f"- {link}")
        if source.evidence_type:
            lines.append(f"  - evidence_type: {source.evidence_type}")
    lines.append("")
    return "\n".join(lines)


def _cross_source_section(concept: MergedConcept) -> str:
    """Render a factual one-line cross-source summary.

    No LLM prose: just project the merged counts into a sentence. This
    is the ACE-playbook discipline -- the body is a deterministic view
    of the merged record, nothing more.
    """
    n = concept.source_count
    helpful_lo, helpful_hi = concept.helpful_evidence.lower, concept.helpful_evidence.upper
    harmful_lo, harmful_hi = concept.harmful_evidence.lower, concept.harmful_evidence.upper

    bits: list[str] = []
    if helpful_hi == helpful_lo:
        bits.append(f"{helpful_lo} of {n} sources treat this concept as helpful")
    else:
        bits.append(
            f"{helpful_lo}-{helpful_hi} of {n} sources treat this concept as helpful "
            f"(width {helpful_hi - helpful_lo} reflects ambiguous mentions)"
        )
    if harmful_hi > 0:
        if harmful_hi == harmful_lo:
            bits.append(f"{harmful_lo} contradict or push back")
        else:
            bits.append(f"{harmful_lo}-{harmful_hi} contradict or push back")
    if concept.contested:
        bits.append("**[contested]**")

    return "## Cross-source patterns\n\n" + "; ".join(bits) + ".\n"


def _sources_section(concept: MergedConcept) -> str:
    if not concept.sources:
        return ""
    lines = ["## Sources", ""]
    for source in concept.sources:
        lines.append(
            f"- {_wiki_link(source)}  (`{source.polarity.value}`, source_id: `{source.source_id}`)"
        )
    lines.append("")
    return "\n".join(lines)


def render_playbook(concept: MergedConcept) -> str:
    """Render the full markdown file (frontmatter + body) for one concept.

    Deterministic: same input always produces byte-identical output.
    """
    fm = dump_frontmatter(_build_frontmatter(concept))

    helpful_sources = [s for s in concept.sources if s.polarity == Polarity.HELPFUL]
    harmful_sources = [s for s in concept.sources if s.polarity == Polarity.HARMFUL]
    neutral_sources = [s for s in concept.sources if s.polarity == Polarity.NEUTRAL]

    body_sections: list[str] = [f"# {concept.name}", ""]
    body_sections.append(_evidence_section("Helpful evidence", helpful_sources))
    body_sections.append(_evidence_section("Harmful or contradicting evidence", harmful_sources))
    if neutral_sources:
        body_sections.append(_evidence_section("Neutral / ambiguous mentions", neutral_sources))
    body_sections.append(_cross_source_section(concept))
    body_sections.append(_sources_section(concept))

    body = "\n".join(part for part in body_sections if part).rstrip() + "\n"
    return fm + "\n\n" + body


# ---- IO --------------------------------------------------------------------


def write_playbook(
    topic_dir: Path,
    concept: MergedConcept,
    *,
    now_iso: str,
) -> tuple[Path, bool]:
    """Write a concept's playbook note to disk.

    Returns ``(path, changed)`` where ``changed`` is ``True`` iff the
    file contents would differ from what's already on disk. When the
    file exists and the new content differs, the prior content is first
    snapshot to ``.history/<slug>/<now_iso>.md`` before being overwritten.
    When the content is unchanged, no write happens and no history entry
    is created -- idempotent refresh runs leave the filesystem alone.

    ``now_iso`` is injected so callers can supply a stable timestamp for
    testing; in production this is ``utcnow_iso()``.

    Collision handling: ``MergedConcept.slug`` collapses non-alphanumeric
    characters to underscores, so distinct concepts can produce the same
    slug ("a b", "a/b", "a-b" all -> "a_b"). The writer reads the existing
    target's frontmatter to check ownership and falls back to
    ``<slug>__2.md`` etc. when the slot is owned by a different
    ``normalized_name``. The ``.history/`` snapshot path also tracks the
    chosen filename so the snapshot tree mirrors the live tree.
    """
    parent = note_path_for(topic_dir, concept).parent
    target = _resolve_collision(parent, concept.slug, concept.normalized_name)
    new_content = render_playbook(concept)

    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing == new_content:
            return target, False
        history = history_path_for(topic_dir, concept, now_iso)
        history.parent.mkdir(parents=True, exist_ok=True)
        history.write_text(existing, encoding="utf-8")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")
    return target, True


# ---- mentions.jsonl (append-only log) -------------------------------------


def mentions_jsonl_path(topic_dir: Path) -> Path:
    """Return the path to the per-topic ``mentions.jsonl`` append-only log."""
    return topic_dir / ".concepts" / "mentions.jsonl"


def append_mentions(topic_dir: Path, rows: list[Mapping[str, Any]] | list[dict[str, Any]]) -> Path:
    """Append mention records to ``mentions.jsonl``, creating directories as needed.

    Append-only: this file is the audit trail of what the LLM produced
    on which insights and when. The merge layer re-reads the entire file
    on refresh; never edited or overwritten.
    """
    path = mentions_jsonl_path(topic_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def read_mentions(topic_dir: Path) -> list[dict[str, Any]]:
    """Read all rows from ``mentions.jsonl``, or empty list if missing."""
    path = mentions_jsonl_path(topic_dir)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Keep only object rows. A valid-JSON-but-non-dict line (``[]``, a bare
        # string) would otherwise crash downstream: ``from_jsonl_row`` does
        # ``row["name"]`` (TypeError on a list) and ``already_extracted_source_ids``
        # does ``"source_id" in row`` (a substring test on a string -> TypeError).
        if isinstance(row, dict):
            rows.append(cast("dict[str, Any]", row))
    return rows


def already_extracted_source_ids(topic_dir: Path) -> set[str]:
    """Return the set of source_ids already present in mentions.jsonl.

    Used by the pipeline to decide which insights still need an
    extraction LLM call. Skipping already-extracted insights keeps
    refresh cheap.
    """
    return {row["source_id"] for row in read_mentions(topic_dir) if "source_id" in row}


def _extracted_sources_path(topic_dir: Path) -> Path:
    return topic_dir / ".concepts" / "extracted_sources.json"


def read_extracted_sources(topic_dir: Path) -> set[str]:
    """Ledger of source_ids whose insight has been extracted, incl. zero-mention ones.

    ``mentions.jsonl`` only records sources that produced at least one mention, so
    a successful *empty* extraction (the prompt explicitly allows ``[]`` for an
    insight with no substantive concepts) leaves no row -- and the insight is then
    re-extracted, a wasted paid LLM call, on every subsequent non-refresh run.
    This ledger records every successfully-processed source so empty results stay
    idempotent. Missing/unreadable ledger -> empty set.
    """
    path = _extracted_sources_path(topic_dir)
    if not path.exists():
        return set[str]()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set[str]()
    if not isinstance(data, list):
        return set[str]()
    return {str(s) for s in cast("list[object]", data)}


def record_extracted_sources(topic_dir: Path, source_ids: Iterable[str]) -> None:
    """Merge ``source_ids`` into the extracted-sources ledger (idempotent)."""
    new = {str(s) for s in source_ids}
    if not new:
        return
    merged = read_extracted_sources(topic_dir) | new
    path = _extracted_sources_path(topic_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(merged), ensure_ascii=False, indent=2), encoding="utf-8")
