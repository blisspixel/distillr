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

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from distill.concepts.records import MergedConcept, Polarity, SourceEvidence
from distill.library.paths import dump_frontmatter

__all__ = [
    "concept_dir_for_topic",
    "entity_dir_for_topic",
    "history_path_for",
    "note_path_for",
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
    """
    parent = (
        entity_dir_for_topic(topic_dir)
        if concept.kind.is_entity
        else concept_dir_for_topic(topic_dir)
    )
    return parent / f"{concept.slug}.md"


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
    """
    target = note_path_for(topic_dir, concept)
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


def append_mentions(topic_dir: Path, rows: list[Mapping[str, Any]]) -> Path:
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
        rows.append(json.loads(line))
    return rows


def already_extracted_source_ids(topic_dir: Path) -> set[str]:
    """Return the set of source_ids already present in mentions.jsonl.

    Used by the pipeline to decide which insights still need an
    extraction LLM call. Skipping already-extracted insights keeps
    refresh cheap.
    """
    return {row["source_id"] for row in read_mentions(topic_dir) if "source_id" in row}
