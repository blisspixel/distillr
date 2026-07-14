"""Read and restore concept-playbook history snapshots.

0.8 writes ``.history/<slug>/<iso-timestamp>.md`` snapshots on every
overwrite (see ``notes.write_playbook``), but nothing reads them. This
module is the recovery surface: enumerate snapshots, diff two versions
of a note, and atomically roll a note back to a prior snapshot while
keeping the ``concepts.jsonl`` / ``entities.jsonl`` rollup row in sync.

Design discipline (same as the rest of the concept layer):

- Pure-ish: every function takes a ``topic_dir`` and does plain
  filesystem IO. No LLM calls, no network, no global state. The one
  side-effecting function (``rollback``) takes an injected ``now_iso``
  so tests get deterministic snapshot filenames.
- Reconstruct, don't recompute. A rollback restores the note *and* its
  rollup row from the snapshot's own frontmatter. It deliberately does
  not re-run the merge: ``mentions.jsonl`` is append-only and still
  describes every extraction, so re-merging would just reproduce the
  current (post-overwrite) state, not the snapshot the user asked for.
- Frontmatter is the source of truth for the rollup row. The note's
  flow-style YAML frontmatter (written by ``library.paths.dump_frontmatter``)
  serializes lists and intervals as inline JSON, so ``json.loads`` round-trips
  ``sources`` and the evidence intervals straight out of the header.
"""

# pyright: strict

from __future__ import annotations

import contextlib
import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import deal

from distill.concepts.exports import concepts_jsonl_path, entities_jsonl_path
from distill.concepts.locking import concept_transaction
from distill.concepts.records import ConceptKind
from distill.library.paths import atomic_write_text, extract_frontmatter, strip_frontmatter

__all__ = [
    "FieldChange",
    "NoteDiff",
    "RollbackResult",
    "Snapshot",
    "diff_notes",
    "history_dir_for_slug",
    "iso_to_safe_ts",
    "list_snapshots",
    "note_path_for_slug",
    "parse_note_fields",
    "resolve_snapshot",
    "rollback",
    "safe_ts_to_iso",
    "summarize_transition",
]


# ---- timestamp <-> filename ------------------------------------------------


def iso_to_safe_ts(iso: str) -> str:
    """Convert an ISO 8601 timestamp to the filesystem-safe stem.

    Mirrors ``notes.history_path_for``: ``:`` is illegal in Windows
    filenames, so it is swapped for ``-`` (``2026-05-29T08:10:31Z`` ->
    ``2026-05-29T08-10-31Z``).
    """
    return iso.replace(":", "-")


def safe_ts_to_iso(safe_ts: str) -> str:
    """Invert :func:`iso_to_safe_ts`.

    Only the time component carries the swapped separators; the date
    component already uses ``-`` and must be left alone. We split on the
    ISO ``T`` separator and only restore ``:`` in the right-hand side.
    A value without ``T`` is returned unchanged (defensive).
    """
    if "T" not in safe_ts:
        return safe_ts
    date_part, time_part = safe_ts.split("T", 1)
    return f"{date_part}T{time_part.replace('-', ':')}"


# ---- path resolution -------------------------------------------------------


def _is_safe_slug(slug: str) -> bool:
    """True if ``slug`` is a single safe path component (no traversal).

    Recovery entry points take ``slug`` from untrusted callers (the MCP
    ``concept_history`` / ``concept_diff`` tools and the CLI). A real note slug
    is ``[a-z0-9_]``; reject separators, ``..``, drive/UNC, and null bytes so a
    hostile slug cannot escape the topic dir to read or write arbitrary files.
    """
    if not slug or "\x00" in slug:
        return False
    if "/" in slug or "\\" in slug or ":" in slug or slug in (".", ".."):
        return False
    return slug == Path(slug).name


def history_dir_for_slug(topic_dir: Path, slug: str) -> Path:
    """Return ``<topic_dir>/.history/<slug>/``. Does not create."""
    return topic_dir / ".history" / slug


def note_path_for_slug(topic_dir: Path, slug: str) -> Path | None:
    """Locate the live note for ``slug`` under ``concepts/`` or ``entities/``.

    Checks the canonical ``<slug>.md`` in both directories first. If
    neither exists (a collision-bumped ``<slug>__2.md`` owns the slug, or
    the kind directory differs), it scans both directories for a note
    whose frontmatter ``slug`` field matches. Returns ``None`` when no
    live note exists for the slug.
    """
    if not _is_safe_slug(slug):
        return None
    for sub in ("concepts", "entities"):
        candidate = topic_dir / sub / f"{slug}.md"
        if candidate.is_file():
            return candidate
    for sub in ("concepts", "entities"):
        parent = topic_dir / sub
        if not parent.is_dir():
            continue
        for path in sorted(parent.glob("*.md")):
            try:
                fm = extract_frontmatter(path.read_text(encoding="utf-8"))
            except OSError:
                continue
            if fm.get("slug") == slug:
                return path
    return None


# ---- snapshot enumeration --------------------------------------------------


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One ``.history`` snapshot of a concept note.

    ``safe_ts`` is the filename stem; ``iso`` is the display form. Sorted
    lexicographically by ``safe_ts`` (which is chronological for ISO
    timestamps) so ``list_snapshots`` returns oldest -> newest.
    """

    slug: str
    safe_ts: str
    iso: str
    path: Path


def list_snapshots(topic_dir: Path, slug: str) -> list[Snapshot]:
    """Return all snapshots for ``slug``, oldest first. Empty if none."""
    if not _is_safe_slug(slug):
        return []
    history = history_dir_for_slug(topic_dir, slug)
    if not history.is_dir():
        return []
    snapshots = [
        Snapshot(slug=slug, safe_ts=path.stem, iso=safe_ts_to_iso(path.stem), path=path)
        for path in history.glob("*.md")
    ]
    snapshots.sort(key=lambda s: s.safe_ts)
    return snapshots


def resolve_snapshot(topic_dir: Path, slug: str, timestamp: str) -> Snapshot | None:
    """Find the snapshot identified by ``timestamp``.

    Accepts either the filesystem stem (``2026-05-29T08-10-31Z``, as shown
    by ``log``) or the ISO form (``2026-05-29T08:10:31Z``), with or
    without a trailing ``.md``. Returns ``None`` if no snapshot matches.
    """
    wanted = timestamp.strip().removesuffix(".md")
    wanted_safe = iso_to_safe_ts(wanted)
    for snap in list_snapshots(topic_dir, slug):
        if wanted in (snap.safe_ts, snap.iso) or wanted_safe == snap.safe_ts:
            return snap
    return None


# ---- frontmatter parsing ---------------------------------------------------

_INTERVAL_FIELDS = ("helpful_evidence", "harmful_evidence")
_INT_FIELDS = ("source_count", "helpful_count", "harmful_count")
_ROLLUP_KEYS: set[str] = {
    "name",
    "normalized_name",
    "slug",
    "kind",
    "topic",
    "source_count",
    "helpful_evidence",
    "harmful_evidence",
    "helpful_count",
    "harmful_count",
    "contested",
    "first_seen",
    "last_seen",
}


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_evidence_interval(value: object) -> bool:
    if not isinstance(value, list):
        return False
    items = cast("list[object]", value)
    if len(items) != 2:
        return False
    lower, upper = items
    if not (_is_non_negative_int(lower) and _is_non_negative_int(upper)):
        return False
    return cast("int", lower) <= cast("int", upper)


def _parse_non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    with contextlib.suppress(TypeError, ValueError):
        parsed = int(value)  # pyright: ignore[reportArgumentType] -- int() is the parser boundary
        if parsed >= 0:
            return parsed
    return 0


def _parse_json_list(value: object) -> list[Any] | None:
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(decoded, list):
        return cast("list[Any]", decoded)
    return None


def _parse_evidence_interval(value: object) -> list[int]:
    decoded = _parse_json_list(value)
    if _is_evidence_interval(decoded):
        return cast("list[int]", decoded)
    if _is_evidence_interval(value):
        return cast("list[int]", value)
    return [0, 0]


def _parsed_note_fields_are_typed(fields: dict[str, Any]) -> bool:
    for key in _INTERVAL_FIELDS:
        if key in fields and not _is_evidence_interval(fields[key]):
            return False
    if "sources" in fields and not isinstance(fields["sources"], list):
        return False
    for key in _INT_FIELDS:
        if key in fields and not _is_non_negative_int(fields[key]):
            return False
    return "contested" not in fields or isinstance(fields["contested"], bool)


def _rollup_row_is_structural(row: dict[str, Any]) -> bool:
    return (
        set(row) == _ROLLUP_KEYS
        and _is_non_negative_int(row["source_count"])
        and _is_evidence_interval(row["helpful_evidence"])
        and _is_evidence_interval(row["harmful_evidence"])
        and _is_non_negative_int(row["helpful_count"])
        and _is_non_negative_int(row["harmful_count"])
        and isinstance(row["contested"], bool)
    )


@deal.post(_parsed_note_fields_are_typed)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def parse_note_fields(content: str) -> dict[str, Any]:
    """Parse a note's frontmatter into typed values.

    The flat ``extract_frontmatter`` returns every field as a string;
    this layer decodes the structured ones. ``sources`` and the evidence
    intervals are inline JSON in the flow-style YAML, so ``json.loads``
    recovers them directly. Anything unparseable falls back to a safe
    default rather than raising, so a hand-edited or older note still
    diffs without blowing up.
    """
    raw = extract_frontmatter(content)
    fields: dict[str, Any] = dict(raw)

    for key in _INTERVAL_FIELDS:
        if key in raw:
            fields[key] = _parse_evidence_interval(raw[key])
    if "sources" in raw:
        fields["sources"] = _parse_json_list(raw["sources"]) or []
    for key in _INT_FIELDS:
        if key in raw:
            fields[key] = _parse_non_negative_int(raw[key])
    if "contested" in raw:
        fields["contested"] = str(raw["contested"]).lower() == "true"
    return fields


def _sources_by_id(fields: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    raw_sources = fields.get("sources")
    if not isinstance(raw_sources, list):
        return out
    for src in cast("list[object]", raw_sources):
        if isinstance(src, dict):
            src_dict = cast("dict[str, Any]", src)
            if src_dict.get("source_id"):
                out[str(src_dict["source_id"])] = src_dict
    return out


# ---- diffing ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FieldChange:
    """A single scalar / interval frontmatter field that shifted."""

    field: str
    old: Any
    new: Any


@dataclass(slots=True)
class NoteDiff:
    """Structured diff between two versions of a concept note.

    Frontmatter changes are itemized (which sources joined or left, how
    the evidence intervals shifted, which scalars moved); the prose body
    is a plain unified-diff string. ``old_label`` / ``new_label`` describe
    the two sides for display.
    """

    old_label: str
    new_label: str
    sources_added: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]
    sources_removed: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[str]
    sources_repolarized: list[tuple[str, str, str]] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[tuple]
    field_changes: list[FieldChange] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType] dataclass default_factory appears as list[Unknown] under strict; usage confirms list[FieldChange]
    body_diff: str = ""

    @property
    def has_frontmatter_changes(self) -> bool:
        return bool(
            self.sources_added
            or self.sources_removed
            or self.sources_repolarized
            or self.field_changes
        )

    @property
    def is_empty(self) -> bool:
        return not self.has_frontmatter_changes and not self.body_diff.strip()


# Scalar / interval fields compared verbatim, in display order.
_DIFF_FIELDS = (
    "name",
    "normalized_name",
    "kind",
    "source_count",
    "helpful_evidence",
    "harmful_evidence",
    "helpful_count",
    "harmful_count",
    "contested",
    "first_seen",
    "last_seen",
)


def diff_notes(
    old_content: str,
    new_content: str,
    *,
    old_label: str = "old",
    new_label: str = "new",
) -> NoteDiff:
    """Compute the structured diff from ``old_content`` to ``new_content``."""
    old_f = parse_note_fields(old_content)
    new_f = parse_note_fields(new_content)

    old_sources = _sources_by_id(old_f)
    new_sources = _sources_by_id(new_f)

    added = sorted(set(new_sources) - set(old_sources))
    removed = sorted(set(old_sources) - set(new_sources))
    repolarized: list[tuple[str, str, str]] = []
    for sid in sorted(set(old_sources) & set(new_sources)):
        old_pol = str(old_sources[sid].get("polarity", ""))
        new_pol = str(new_sources[sid].get("polarity", ""))
        if old_pol != new_pol:
            repolarized.append((sid, old_pol, new_pol))

    field_changes: list[FieldChange] = [
        FieldChange(name, old_f.get(name), new_f.get(name))
        for name in _DIFF_FIELDS
        if old_f.get(name) != new_f.get(name)
    ]

    body_diff = "\n".join(
        difflib.unified_diff(
            strip_frontmatter(old_content).splitlines(),
            strip_frontmatter(new_content).splitlines(),
            fromfile=old_label,
            tofile=new_label,
            lineterm="",
        )
    )

    return NoteDiff(
        old_label=old_label,
        new_label=new_label,
        sources_added=added,
        sources_removed=removed,
        sources_repolarized=repolarized,
        field_changes=field_changes,
        body_diff=body_diff,
    )


def summarize_transition(old_fields: dict[str, Any], new_fields: dict[str, Any]) -> str:
    """One-line summary of what changed from ``old_fields`` to ``new_fields``.

    Used by ``distill concepts log`` to annotate each step. Reports source
    count deltas, evidence-interval shifts, and contested flips; falls
    back to a body-only note when no structured field moved.
    """
    old_ids = set(_sources_by_id(old_fields))
    new_ids = set(_sources_by_id(new_fields))
    bits: list[str] = []

    n_added = len(new_ids - old_ids)
    n_removed = len(old_ids - new_ids)
    if n_added:
        bits.append(f"+{n_added} source{'s' if n_added != 1 else ''}")
    if n_removed:
        bits.append(f"-{n_removed} source{'s' if n_removed != 1 else ''}")

    for label in ("helpful_evidence", "harmful_evidence"):
        old_iv = old_fields.get(label)
        new_iv = new_fields.get(label)
        if old_iv != new_iv:
            kind = label.split("_", 1)[0]
            bits.append(f"{kind} {_fmt_interval(old_iv)}->{_fmt_interval(new_iv)}")

    old_contested = bool(old_fields.get("contested"))
    new_contested = bool(new_fields.get("contested"))
    if old_contested != new_contested:
        bits.append("became contested" if new_contested else "no longer contested")

    return ", ".join(bits) if bits else "body/wording only"


def _fmt_interval(value: Any) -> str:
    if isinstance(value, list):
        items = cast("list[Any]", value)
        if len(items) == 2:
            return f"[{items[0]},{items[1]}]"
        return str(items)
    return str(value)


# ---- rollback --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RollbackResult:
    """Outcome of a rollback for caller display."""

    slug: str
    restored_from: str  # iso timestamp of the chosen snapshot
    note_path: Path
    backup_path: Path | None  # snapshot of the pre-rollback live content
    rollup_path: Path | None  # the jsonl whose row was rewritten

    @property
    def changed(self) -> bool:
        """Return whether rollback repaired any persisted state.

        Every mutation rewrites the target rollup, including a rollup-only
        repair after an interrupted prior restore. A missing rollup path thus
        identifies the fully consistent no-op and prevents contradictory
        constructor states.
        """
        return self.rollup_path is not None


@deal.post(_rollup_row_is_structural)  # pyright: ignore[reportUnknownMemberType] -- deal stubs type the validator as Unknown
def _rollup_row_from_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a ``concepts.jsonl`` row from a note's parsed frontmatter.

    Mirrors ``MergedConcept.to_jsonl_row`` key-for-key so the restored row
    is byte-compatible with what the merge layer would emit.
    """
    return {
        "name": fields.get("name", ""),
        "normalized_name": fields.get("normalized_name", ""),
        "slug": fields.get("slug", ""),
        "kind": fields.get("kind", ""),
        "topic": fields.get("topic", ""),
        "source_count": _parse_non_negative_int(fields.get("source_count", 0)),
        "helpful_evidence": _parse_evidence_interval(fields.get("helpful_evidence", [0, 0])),
        "harmful_evidence": _parse_evidence_interval(fields.get("harmful_evidence", [0, 0])),
        "helpful_count": _parse_non_negative_int(fields.get("helpful_count", 0)),
        "harmful_count": _parse_non_negative_int(fields.get("harmful_count", 0)),
        "contested": bool(fields.get("contested", False)),
        "first_seen": fields.get("first_seen", ""),
        "last_seen": fields.get("last_seen", ""),
    }


def _rollup_path_for_kind(topic_dir: Path, kind: str) -> Path:
    try:
        is_entity = ConceptKind(kind).is_entity
    except ValueError:
        is_entity = False
    return entities_jsonl_path(topic_dir) if is_entity else concepts_jsonl_path(topic_dir)


def _read_rollup_rows(path: Path) -> list[dict[str, Any]]:
    """Read structurally valid object rows while tolerating damaged lines."""
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(cast("dict[str, Any]", value))
    return rows


def _same_rollup_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Match one logical concept without conflating lossy-slug collisions."""

    if str(left.get("kind", "")) != str(right.get("kind", "")):
        return False
    left_name = str(left.get("normalized_name", "")).strip()
    right_name = str(right.get("normalized_name", "")).strip()
    if left_name or right_name:
        return bool(left_name and right_name and left_name == right_name)
    return str(left.get("slug", "")) == str(right.get("slug", ""))


def _assert_rollup_identity_unambiguous(topic_dir: Path, fields: dict[str, Any]) -> None:
    """Reject a legacy rollback when its identity cannot be selected safely."""

    expected = _rollup_row_from_fields(fields)
    if str(expected.get("normalized_name", "")).strip():
        return
    path = _rollup_path_for_kind(topic_dir, expected["kind"])
    rows = _read_rollup_rows(path)
    matches = [row for row in rows if _same_rollup_identity(row, expected)]
    if len(matches) > 1:
        raise ValueError(
            f"Rollup contains multiple legacy rows for kind {expected['kind']!r} "
            f"and slug {expected['slug']!r}; normalized_name is required to roll back safely."
        )
    named_collisions = [
        row
        for row in rows
        if str(row.get("kind", "")) == str(expected["kind"])
        and str(row.get("slug", "")) == str(expected["slug"])
        and str(row.get("normalized_name", "")).strip()
    ]
    if named_collisions:
        raise ValueError(
            f"An identity-less snapshot cannot be matched safely among named rows "
            f"for kind {expected['kind']!r} and slug {expected['slug']!r}."
        )


def _rollup_matches_fields(topic_dir: Path, fields: dict[str, Any]) -> bool:
    """Return whether exactly one target row matches restored frontmatter."""
    expected = _rollup_row_from_fields(fields)
    path = _rollup_path_for_kind(topic_dir, expected["kind"])
    matches = [row for row in _read_rollup_rows(path) if _same_rollup_identity(row, expected)]
    return matches == [expected]


def _update_rollup(topic_dir: Path, fields: dict[str, Any]) -> Path:
    """Replace (or append) the rollup row for the restored concept identity.

    Keeps the file sorted by ``(kind, slug)`` to match ``write_exports``
    so a subsequent ``distill concepts build`` produces a clean diff
    rather than reordering noise. ``normalized_name`` disambiguates distinct
    concepts whose lossy slugs collide; legacy rows without that field fall
    back to their kind and slug.
    """
    row = _rollup_row_from_fields(fields)
    path = _rollup_path_for_kind(topic_dir, row["kind"])
    _assert_rollup_identity_unambiguous(topic_dir, fields)

    rows: list[dict[str, Any]] = []
    replaced = False
    for existing in _read_rollup_rows(path):
        if not _same_rollup_identity(existing, row):
            rows.append(existing)
        elif not replaced:
            rows.append(row)
            replaced = True
    if not replaced:
        rows.append(row)
    rows.sort(key=lambda r: (str(r.get("kind", "")), str(r.get("slug", ""))))

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
    )
    return path


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically and durably (see paths helper)."""
    atomic_write_text(path, content)


def rollback(
    topic_dir: Path,
    slug: str,
    timestamp: str,
    *,
    now_iso: str,
) -> RollbackResult:
    """Restore ``slug``'s note to the snapshot at ``timestamp``.

    The complete note, backup, and rollup mutation is serialized with concept
    builds and other rollbacks for the same topic. When live content differs,
    it is first snapshot into ``.history`` under ``now_iso`` so a rollback can
    itself be rolled back.

    Raises ``FileNotFoundError`` if the snapshot doesn't exist. No files change
    only when the live note and exactly one target rollup row already match the
    snapshot; then ``RollbackResult.changed`` is ``False``.
    """
    if not _is_safe_slug(slug):
        raise ValueError(f"Unsafe concept slug: {slug!r}")
    with concept_transaction(topic_dir):
        return _rollback_transaction(topic_dir, slug, timestamp, now_iso=now_iso)


def _rollback_transaction(
    topic_dir: Path,
    slug: str,
    timestamp: str,
    *,
    now_iso: str,
) -> RollbackResult:
    """Perform one rollback while the caller holds the topic transaction lock."""

    snapshot = resolve_snapshot(topic_dir, slug, timestamp)
    if snapshot is None:
        raise FileNotFoundError(f"No snapshot for slug '{slug}' matching timestamp '{timestamp}'.")

    restored_content = snapshot.path.read_text(encoding="utf-8")
    restored_fields = parse_note_fields(restored_content)
    _assert_rollup_identity_unambiguous(topic_dir, restored_fields)

    live_path = note_path_for_slug(topic_dir, slug)
    if live_path is None:
        # Note was deleted; recreate it in the directory its kind implies.
        kind = str(restored_fields.get("kind", ""))
        try:
            sub = "entities" if ConceptKind(kind).is_entity else "concepts"
        except ValueError:
            sub = "concepts"
        live_path = topic_dir / sub / f"{slug}.md"

    current_content = live_path.read_text(encoding="utf-8") if live_path.is_file() else None
    if current_content is not None:
        # Guard against slug collisions. Distinct concepts can share a slug
        # (e.g. "gpt-4" and "gpt 4" both slugify to "gpt_4"); the base
        # <slug>.md and a bumped <slug>__2.md both carry slug="gpt_4" and land
        # in one shared .history/<slug>/ dir. note_path_for_slug always returns
        # the base note, so a snapshot belonging to the bumped concept would
        # otherwise silently overwrite the base concept. Refuse on mismatch.
        live_id = str(parse_note_fields(current_content).get("normalized_name", "")).strip()
        restored_id = str(restored_fields.get("normalized_name", "")).strip()
        if (live_id or restored_id) and live_id != restored_id:
            raise ValueError(
                f"Slug '{slug}' is shared by multiple concepts "
                f"({live_id or '<legacy>'!r} vs restored "
                f"{restored_id or '<legacy>'!r}); cannot safely roll "
                f"back by slug alone -- resolve the collision manually."
            )
    note_changed = current_content != restored_content
    if not note_changed and _rollup_matches_fields(topic_dir, restored_fields):
        return RollbackResult(
            slug=slug,
            restored_from=snapshot.iso,
            note_path=live_path,
            backup_path=None,
            rollup_path=None,
        )

    backup_path: Path | None = None
    if note_changed and current_content is not None:
        backup_path = history_dir_for_slug(topic_dir, slug) / f"{iso_to_safe_ts(now_iso)}.md"
        atomic_write_text(backup_path, current_content)

    if note_changed:
        _atomic_write(live_path, restored_content)
    rollup_path = _update_rollup(topic_dir, restored_fields)

    return RollbackResult(
        slug=slug,
        restored_from=snapshot.iso,
        note_path=live_path,
        backup_path=backup_path,
        rollup_path=rollup_path,
    )
