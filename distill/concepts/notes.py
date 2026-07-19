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

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from distill.concepts.locking import concept_transaction
from distill.concepts.records import ConceptMention, MergedConcept, Polarity, SourceEvidence
from distill.jsonl import (
    JsonlIntegrityError,
    append_jsonl_lines_locked,
    jsonl_append_lock,
    read_jsonl_objects_strict,
)
from distill.library.confined_state import (
    ConfinedStateError,
    FileIdentity,
    atomic_write_confined_text,
    confined_file_identity,
    confined_state_lock_path,
    ensure_confined_parent,
    read_confined_state_bytes,
    read_confined_state_text,
    unlink_confined_file,
)
from distill.library.locking import exclusive_path_lock
from distill.library.paths import dump_frontmatter, extract_frontmatter, text_write_lock
from distill.library.source_ledger import (
    ensure_source_ledger_merge_capacity,
    merge_source_ledger,
    read_source_ledger,
    validate_source_id,
)

__all__ = [
    "build_playbook_ownership_index",
    "concept_dir_for_topic",
    "ensure_extracted_sources_capacity",
    "ensure_mention_store_append_capacity",
    "entity_dir_for_topic",
    "history_path_for",
    "note_path_for",
    "read_extracted_sources",
    "record_extracted_sources",
    "render_playbook",
    "write_history_snapshot",
    "write_playbook",
]

_MAX_MENTIONS_HISTORY_BYTES = 8 * 1024 * 1024
_MAX_MENTION_ROW_BYTES = 1024 * 1024
_MAX_MENTIONS_HISTORY_ROWS = 10_000
_MAX_PLAYBOOK_NOTE_BYTES = 8 * 1024 * 1024


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
    the writer picks a deterministic ``<slug>__<hash>.md`` fallback and the
    ``.normalized_name`` frontmatter field becomes the authoritative
    identity that resolves the collision on subsequent writes.
    """
    parent = (
        entity_dir_for_topic(topic_dir)
        if concept.kind.is_entity
        else concept_dir_for_topic(topic_dir)
    )
    return parent / f"{concept.slug}.md"


def _content_owner(content: str) -> str | None:
    """Return the normalized concept identity recorded in note content."""

    name = extract_frontmatter(content).get("normalized_name", "")
    return name or None


def _existing_owner(target: Path, topic_dir: Path) -> str | None:
    """Return the ``normalized_name`` recorded in an existing note's frontmatter, or ``None``.

    Used by collision detection: two distinct concepts can produce the
    same slug, so before overwriting we read the target's frontmatter
    and confirm the existing note belongs to the same logical concept.
    Returns ``None`` if the file doesn't exist or the frontmatter is
    unreadable / missing the field.
    """
    record = _read_safe_note(target, topic_dir)
    if record is None:
        return None
    return _content_owner(record[0])


def _read_safe_note(path: Path, topic_dir: Path) -> tuple[str, FileIdentity] | None:
    """Read one bounded private regular note without following filesystem links."""

    initial_identity = confined_file_identity(path, topic_dir)
    if initial_identity is None:
        return None
    content = read_confined_state_text(
        path,
        topic_dir,
        max_bytes=_MAX_PLAYBOOK_NOTE_BYTES,
    )
    if content is None:
        return None
    # Match ``Path.read_text`` universal-newline semantics so Windows atomic
    # text writes compare byte-equivalent Markdown as content-equivalent.
    final_identity = confined_file_identity(path, topic_dir)
    if final_identity != initial_identity:
        raise ValueError(f"Playbook note changed while it was being read: {path}")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, initial_identity


def _resolve_collision(
    topic_dir: Path,
    parent: Path,
    slug: str,
    normalized_name: str,
    occupied_paths: set[Path] | None = None,
) -> Path:
    """Find a bounded deterministic path that this concept can own."""

    base = parent / f"{slug}.md"
    if _collision_path_available(topic_dir, base, normalized_name, occupied_paths):
        return base
    digest = hashlib.sha256(
        normalized_name.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    for length in (12, 20, 32, 64):
        candidate = parent / f"{slug}__{digest[:length]}.md"
        if _collision_path_available(topic_dir, candidate, normalized_name, occupied_paths):
            return candidate
    raise ConfinedStateError(f"Could not allocate a collision-safe note for {normalized_name!r}")


def _collision_path_available(
    topic_dir: Path,
    path: Path,
    normalized_name: str,
    occupied_paths: set[Path] | None,
) -> bool:
    """Check one candidate without probing unrelated collision suffixes."""

    if occupied_paths is not None and path not in occupied_paths:
        return True
    identity = confined_file_identity(path, topic_dir)
    return identity is None or _existing_owner(path, topic_dir) == normalized_name


def history_path_for(
    topic_dir: Path,
    concept: MergedConcept,
    timestamp: str,
    *,
    storage_slug: str | None = None,
) -> Path:
    """Return the snapshot path under ``.history/<storage-slug>/<timestamp>.md``.

    The storage slug is the live note stem after collision resolution. This
    keeps the histories of concepts with the same lossy logical slug isolated.
    Callers that only need the canonical base path may omit it.
    Timestamp should be ISO 8601 with second precision, ``:`` swapped to
    ``-`` for filesystem compatibility (Windows can't have ``:`` in
    filenames).
    """
    history_slug = concept.slug if storage_slug is None else storage_slug
    if (
        not history_slug
        or history_slug in {".", ".."}
        or any(character in history_slug for character in ("/", "\\", ":", "\x00"))
        or Path(history_slug).name != history_slug
    ):
        raise ValueError(f"Unsafe history storage slug: {history_slug!r}")
    safe_ts = timestamp.replace(":", "-")
    return topic_dir / ".history" / history_slug / f"{safe_ts}.md"


def _note_lock_path(topic_dir: Path, path: Path, purpose: str) -> Path:
    return confined_state_lock_path(path, topic_dir, purpose)


def write_history_snapshot(base_path: Path, content: str, *, root: Path) -> Path:
    """Atomically preserve ``content`` without overwriting a same-time snapshot.

    The canonical timestamp filename is used first, followed by ``__2``,
    ``__3``, and so on. Selection and creation share the destination's write
    lock, so cooperating concurrent writers cannot choose the same slot.
    """

    for index in range(1, 10_001):
        candidate = (
            base_path
            if index == 1
            else base_path.with_name(f"{base_path.stem}__{index}{base_path.suffix}")
        )
        lock_path = _note_lock_path(root, candidate, "history")
        ensure_confined_parent(lock_path, root, create=False)
        with exclusive_path_lock(
            lock_path,
            timeout_seconds=30.0,
            timeout_message=f"Timed out preserving history snapshot: {candidate}",
        ):
            try:
                atomic_write_confined_text(
                    candidate,
                    content,
                    root,
                    exclusive=True,
                )
                return candidate
            except FileExistsError:
                continue
    raise RuntimeError(f"Could not allocate a unique history snapshot below {base_path.parent}")


def build_playbook_ownership_index(
    topic_dir: Path,
    *,
    occupied_paths: set[Path] | None = None,
) -> dict[str, list[Path]]:
    """Read every live note once and index paths by normalized identity."""

    ownership: dict[str, list[Path]] = {}
    for parent in (concept_dir_for_topic(topic_dir), entity_dir_for_topic(topic_dir)):
        if ensure_confined_parent(parent / ".probe", topic_dir, create=False) is None:
            continue
        for path in sorted(parent.glob("*.md")):
            if occupied_paths is not None:
                occupied_paths.add(path)
            record = _read_safe_note(path, topic_dir)
            if record is None:
                continue
            owner = _content_owner(record[0])
            if owner is not None:
                ownership.setdefault(owner, []).append(path)
    return ownership


def _owned_note_paths(topic_dir: Path, normalized_name: str) -> list[Path]:
    """Find live concept/entity notes owned by one normalized identity."""

    return list(build_playbook_ownership_index(topic_dir).get(normalized_name, ()))


def _migration_target(
    topic_dir: Path,
    concept: MergedConcept,
    owned_paths: list[Path],
    occupied_paths: set[Path] | None,
) -> Path:
    """Preserve an owned storage slug while routing a kind to its new family."""

    desired_parent = note_path_for(topic_dir, concept).parent
    same_family = [path for path in owned_paths if path.parent == desired_parent]
    if same_family:
        return same_family[0]
    if owned_paths:
        preserved = desired_parent / owned_paths[0].name
        if (
            confined_file_identity(preserved, topic_dir) is None
            or _existing_owner(preserved, topic_dir) == concept.normalized_name
        ):
            return preserved
    return _resolve_collision(
        topic_dir,
        desired_parent,
        concept.slug,
        concept.normalized_name,
        occupied_paths,
    )


def _snapshot_owned_notes(
    topic_dir: Path,
    concept: MergedConcept,
    owned_paths: list[Path],
    target: Path,
    now_iso: str,
) -> list[tuple[Path, FileIdentity]]:
    """Preserve owned live notes that will be removed after kind migration."""

    created: list[tuple[Path, FileIdentity]] = []
    try:
        for old_path in owned_paths:
            if old_path == target:
                continue
            record = _read_safe_note(old_path, topic_dir)
            if record is None:
                continue
            history = history_path_for(
                topic_dir,
                concept,
                now_iso,
                storage_slug=target.stem,
            )
            snapshot = write_history_snapshot(history, record[0], root=topic_dir)
            identity = confined_file_identity(snapshot, topic_dir)
            if identity is None:  # pragma: no cover - exclusive publication succeeded
                raise ConfinedStateError(f"History snapshot disappeared after write: {snapshot}")
            created.append((snapshot, identity))
    except Exception as snapshot_error:
        try:
            _remove_created_snapshots(topic_dir, created)
        except Exception as cleanup_error:
            raise ExceptionGroup(
                "History snapshot publication and cleanup both failed",
                [snapshot_error, cleanup_error],
            ) from None
        raise
    return created


def _remove_created_snapshots(
    topic_dir: Path,
    snapshots: list[tuple[Path, FileIdentity]],
) -> None:
    """Remove only snapshots created by the current failed publication."""

    errors: list[Exception] = []
    for path, identity in reversed(snapshots):
        try:
            unlink_confined_file(path, topic_dir, expected=identity)
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise ExceptionGroup("Could not remove failed-publication snapshots", errors)


def _remove_migrated_notes(
    topic_dir: Path,
    owned_paths: list[Path],
    target: Path,
    normalized_name: str,
) -> bool:
    """Delete only verified old-family duplicates after target publication."""

    removed = False
    for old_path in owned_paths:
        if old_path == target:
            continue
        record = _read_safe_note(old_path, topic_dir)
        if record is None or _content_owner(record[0]) != normalized_name:
            continue
        try:
            unlink_confined_file(old_path, topic_dir, expected=record[1])
            removed = True
        except FileNotFoundError:
            continue
    return removed


def _update_playbook_target(
    topic_dir: Path,
    concept: MergedConcept,
    target: Path,
    new_content: str,
    now_iso: str,
) -> bool | None:
    """Safely compare and replace one live note under its cooperating lock."""

    lock_path = _note_lock_path(topic_dir, target, "note")
    ensure_confined_parent(lock_path, topic_dir, create=False)
    with (
        exclusive_path_lock(
            lock_path,
            timeout_seconds=30.0,
            timeout_message=f"Timed out writing playbook note: {target}",
        ),
        text_write_lock(target),
    ):
        record = _read_safe_note(target, topic_dir)
        if record is not None:
            existing = record[0]
            if _content_owner(existing) != concept.normalized_name:
                return None
        else:
            existing = ""
        if existing == new_content:
            return False
        snapshots: list[tuple[Path, FileIdentity]] = []
        if existing:
            history = history_path_for(
                topic_dir,
                concept,
                now_iso,
                storage_slug=target.stem,
            )
            snapshot = write_history_snapshot(history, existing, root=topic_dir)
            identity = confined_file_identity(snapshot, topic_dir)
            if identity is None:  # pragma: no cover - exclusive publication succeeded
                raise ConfinedStateError(f"History snapshot disappeared after write: {snapshot}")
            snapshots.append((snapshot, identity))
        try:
            atomic_write_confined_text(
                target,
                new_content,
                topic_dir,
                exclusive=record is None,
                expected=None if record is None else record[1],
            )
        except Exception as write_error:
            try:
                _remove_created_snapshots(topic_dir, snapshots)
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "Playbook publication and history cleanup both failed",
                    [write_error, cleanup_error],
                ) from None
            raise
        return True


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
        # different one (use a bounded deterministic hash suffix).
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
    owned_paths: Iterable[Path] | None = None,
    occupied_paths: set[Path] | None = None,
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
    a deterministic hash-suffixed path when the slot is owned by a different
    ``normalized_name``. The ``.history/`` snapshot path also tracks the
    chosen filename so the snapshot tree mirrors the live tree.
    """
    with concept_transaction(topic_dir):
        return _write_playbook_transaction(
            topic_dir,
            concept,
            now_iso=now_iso,
            owned_paths=owned_paths,
            occupied_paths=occupied_paths,
        )


def _write_playbook_transaction(
    topic_dir: Path,
    concept: MergedConcept,
    *,
    now_iso: str,
    owned_paths: Iterable[Path] | None,
    occupied_paths: set[Path] | None,
) -> tuple[Path, bool]:
    """Publish one playbook note while the topic transaction is held."""

    new_content = render_playbook(concept)
    rendered_bytes = len(new_content.encode("utf-8"))
    if rendered_bytes > _MAX_PLAYBOOK_NOTE_BYTES:
        raise ConfinedStateError(
            f"Rendered playbook note exceeds the {_MAX_PLAYBOOK_NOTE_BYTES:,}-byte "
            f"reader limit: {rendered_bytes:,} bytes"
        )

    initial_owned_paths = None if owned_paths is None else list(owned_paths)
    for attempt in range(1001):
        current_owned_paths = (
            initial_owned_paths
            if attempt == 0 and initial_owned_paths is not None
            else _owned_note_paths(topic_dir, concept.normalized_name)
        )
        target = _migration_target(
            topic_dir,
            concept,
            current_owned_paths,
            occupied_paths,
        )

        # Preserve opposite-family or duplicate live notes before publishing
        # the canonical target. The target stem owns the unified history so a
        # later rollback can cross the kind boundary in either direction.
        snapshots = _snapshot_owned_notes(
            topic_dir,
            concept,
            current_owned_paths,
            target,
            now_iso,
        )

        try:
            changed = _update_playbook_target(
                topic_dir,
                concept,
                target,
                new_content,
                now_iso,
            )
        except Exception as write_error:
            try:
                _remove_created_snapshots(topic_dir, snapshots)
            except Exception as cleanup_error:
                raise ExceptionGroup(
                    "Playbook migration and history cleanup both failed",
                    [write_error, cleanup_error],
                ) from None
            raise
        if changed is not None:
            removed_old_note = _remove_migrated_notes(
                topic_dir,
                current_owned_paths,
                target,
                concept.normalized_name,
            )
            if occupied_paths is not None:
                occupied_paths.difference_update(current_owned_paths)
                occupied_paths.add(target)
            return target, changed or removed_old_note
        _remove_created_snapshots(topic_dir, snapshots)
        if occupied_paths is not None:
            occupied_paths.add(target)

    raise RuntimeError(
        f"Could not claim a collision-safe note path for {concept.normalized_name!r}"
    )


# ---- mentions.jsonl (append-only log) -------------------------------------


def mentions_jsonl_path(topic_dir: Path) -> Path:
    """Return the path to the per-topic ``mentions.jsonl`` append-only log."""
    return topic_dir / ".concepts" / "mentions.jsonl"


def append_mentions(topic_dir: Path, rows: list[Mapping[str, Any]] | list[dict[str, Any]]) -> Path:
    """Durably append one complete, schema-valid mention batch.

    Append-only: this file is the audit trail of what the LLM produced
    on which insights and when. The merge layer re-reads the entire file
    on refresh; never edited or overwritten.
    """
    path = mentions_jsonl_path(topic_dir)
    mentions: list[ConceptMention] = []
    for index, row in enumerate(rows, 1):
        mention = _mention_from_row(path, index, dict(row))
        try:
            validate_source_id(mention.source_id)
        except ValueError as exc:
            raise JsonlIntegrityError(
                path, f"row {index} violates the source ID contract: {exc}"
            ) from exc
        mentions.append(mention)
    lines = [
        json.dumps(mention.to_jsonl_row(), ensure_ascii=False, allow_nan=False)
        for mention in mentions
    ]
    encoded_size = sum(len(line.encode("utf-8")) + 1 for line in lines)
    if any(len(line.encode("utf-8")) > _MAX_MENTION_ROW_BYTES for line in lines):
        raise JsonlIntegrityError(
            path,
            f"mention batch contains a row above the {_MAX_MENTION_ROW_BYTES:,}-byte limit",
        )
    with jsonl_append_lock(path, confinement_root=topic_dir):
        existing = _read_mentions_history(topic_dir)
        existing_bytes = read_confined_state_bytes(
            path,
            topic_dir,
            max_bytes=_MAX_MENTIONS_HISTORY_BYTES,
        )
        if len(existing) + len(mentions) > _MAX_MENTIONS_HISTORY_ROWS:
            raise JsonlIntegrityError(
                path,
                f"append would exceed the {_MAX_MENTIONS_HISTORY_ROWS:,}-row limit",
            )
        if len(existing_bytes or b"") + encoded_size > _MAX_MENTIONS_HISTORY_BYTES:
            raise JsonlIntegrityError(
                path,
                f"append would exceed the {_MAX_MENTIONS_HISTORY_BYTES:,}-byte limit",
            )
        append_jsonl_lines_locked(
            path,
            lines,
            durable=True,
            confinement_root=topic_dir,
        )
    return path


def _mention_from_row(path: Path, index: int, row: dict[str, Any]) -> ConceptMention:
    try:
        return ConceptMention.from_jsonl_row(row)
    except (KeyError, TypeError, ValueError) as exc:
        raise JsonlIntegrityError(
            path, f"row {index} violates the ConceptMention schema: {exc}"
        ) from exc


def _read_mentions_history(topic_dir: Path) -> list[dict[str, Any]]:
    path = mentions_jsonl_path(topic_dir)
    rows = read_jsonl_objects_strict(
        path,
        max_file_bytes=_MAX_MENTIONS_HISTORY_BYTES,
        max_row_bytes=_MAX_MENTION_ROW_BYTES,
        max_rows=_MAX_MENTIONS_HISTORY_ROWS,
        confinement_root=topic_dir,
    )
    return [
        _mention_from_row(path, index, cast("dict[str, Any]", row)).to_jsonl_row()
        for index, row in enumerate(rows, 1)
    ]


def read_mentions(topic_dir: Path) -> list[dict[str, Any]]:
    """Read a complete bounded mention history, returning empty only if missing."""

    return _read_mentions_history(topic_dir)


def ensure_mention_store_append_capacity(topic_dir: Path) -> None:
    """Fail before provider work when no additional mention row can be stored."""

    path = mentions_jsonl_path(topic_dir)
    mentions = _read_mentions_history(topic_dir)
    existing = read_confined_state_bytes(
        path,
        topic_dir,
        max_bytes=_MAX_MENTIONS_HISTORY_BYTES,
    )
    if len(mentions) >= _MAX_MENTIONS_HISTORY_ROWS:
        raise JsonlIntegrityError(
            path,
            f"history reached the {_MAX_MENTIONS_HISTORY_ROWS:,}-row limit",
        )
    if len(existing or b"") >= _MAX_MENTIONS_HISTORY_BYTES:
        raise JsonlIntegrityError(
            path,
            f"history reached the {_MAX_MENTIONS_HISTORY_BYTES:,}-byte limit",
        )


def already_extracted_source_ids(topic_dir: Path) -> set[str]:
    """Return the set of source_ids already present in mentions.jsonl.

    Used by the pipeline to decide which insights still need an
    extraction LLM call. Skipping already-extracted insights keeps
    refresh cheap.
    """
    return {cast("str", row["source_id"]) for row in read_mentions(topic_dir)}


def _extracted_sources_path(topic_dir: Path) -> Path:
    return topic_dir / ".concepts" / "extracted_sources.json"


def read_extracted_sources(topic_dir: Path) -> set[str]:
    """Ledger of source_ids whose insight has been extracted, incl. zero-mention ones.

    ``mentions.jsonl`` only records sources that produced at least one mention, so
    a successful *empty* extraction (the prompt explicitly allows ``[]`` for an
    insight with no substantive concepts) leaves no row -- and the insight is then
    re-extracted, a wasted paid LLM call, on every subsequent non-refresh run.
    This ledger records every successfully-processed source so empty results stay
    idempotent. Only a missing ledger returns an empty set; corruption is surfaced.
    """
    return read_source_ledger(_extracted_sources_path(topic_dir), root=topic_dir)


def record_extracted_sources(topic_dir: Path, source_ids: Iterable[str]) -> None:
    """Merge ``source_ids`` into the extracted-sources ledger (idempotent)."""
    merge_source_ledger(_extracted_sources_path(topic_dir), source_ids, root=topic_dir)


def ensure_extracted_sources_capacity(topic_dir: Path, source_ids: Iterable[str]) -> None:
    """Fail before provider work if completion receipts cannot be represented."""

    ensure_source_ledger_merge_capacity(
        _extracted_sources_path(topic_dir),
        source_ids,
        root=topic_dir,
    )
