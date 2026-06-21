"""Stateful property test of the concept-playbook lifecycle.

This is the 1.0 "Stateful property testing of the playbook lifecycle" item
(ROADMAP.md, Verification depth): a Hypothesis state machine drives the real
lifecycle -- append mentions to ``mentions.jsonl``, rebuild (merge -> render ->
export), snapshot to ``.history``, roll back, re-merge -- across arbitrary
operation orderings, and asserts the invariants hold at every step. That is the
class of bug (ordering, accumulation, rollback-after-merge) that the example and
single-function property tests in ``test_merge.py`` / ``test_recovery.py`` miss.

Invariants guarded:

- **Merge consistency.** After a rebuild, every concept note on disk equals the
  deterministic ``render_playbook`` of the merge of the accumulated mention log.
- **Idempotence.** An immediate identical rebuild rewrites nothing (no spurious
  ``.history`` churn).
- **Order independence.** Building from the mention log in reverse yields the
  identical set of merged concepts.
- **Rollback round-trip.** After a rollback, the live note byte-matches the
  chosen snapshot, and the rebuilt rollup row round-trips the snapshot's own
  frontmatter (normalized name, both evidence intervals, source count, contested).
- **Evidence intervals never invert.** Every note on disk satisfies
  ``0 <= lower <= upper`` for both polarities, always.

The machine drives the same non-LLM sequence ``run_concepts`` uses
(``group_mentions -> filter_by_threshold -> build_all -> write_playbook ->
write_exports``), so no model mocking is needed.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from distill.concepts.exports import (
    concepts_jsonl_path,
    entities_jsonl_path,
    write_exports,
)
from distill.concepts.merge import build_all
from distill.concepts.normalize import filter_by_threshold, group_mentions
from distill.concepts.notes import (
    append_mentions,
    read_mentions,
    render_playbook,
    write_playbook,
)
from distill.concepts.records import ConceptKind, ConceptMention, MergedConcept, Polarity
from distill.concepts.recovery import (
    list_snapshots,
    note_path_for_slug,
    parse_note_fields,
    rollback,
)

# A fixed (never wall-clock) base so snapshot filenames are deterministic and
# reproducible under shrinking; the clock only ever moves forward.
_BASE = datetime(2026, 1, 1, 0, 0, 0)  # naive base, used only for ISO stamping

# A small fixed vocabulary so mentions actually collide and aggregate. Each name
# keeps a stable kind so its slug and target directory (concepts/ vs entities/)
# never churn -- alpha/beta are concepts, gamma is an entity.
_KIND_BY_NAME = {
    "alpha": ConceptKind.TECHNIQUE,
    "beta": ConceptKind.METRIC,
    "gamma": ConceptKind.ORGANIZATION,
}
_NAMES = tuple(_KIND_BY_NAME)
_SOURCES = ("s1", "s2", "s3", "s4")
_THRESHOLD = 2  # a concept needs two distinct sources to earn a note

_mention_spec = st.tuples(
    st.sampled_from(_NAMES),
    st.sampled_from(_SOURCES),
    st.sampled_from(tuple(Polarity)),
)


class ConceptPlaybookMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self._dir = tempfile.mkdtemp(prefix="distill_playbook_")
        self.topic_dir = Path(self._dir)
        self.topic = "tkg"
        self.model: list[ConceptMention] = []  # shadow of mentions.jsonl
        self.clock = 0

    def teardown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _now(self) -> str:
        self.clock += 1
        return (_BASE + timedelta(seconds=self.clock)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _build(self, rows: list[dict]) -> list[MergedConcept]:
        mentions = [ConceptMention.from_jsonl_row(row) for row in rows]
        filtered = filter_by_threshold(group_mentions(mentions), min_sources=_THRESHOLD)
        return build_all(filtered.items(), topic=self.topic)

    def _snapshot_slugs(self) -> list[str]:
        return [slug for slug in _NAMES if list_snapshots(self.topic_dir, slug)]

    # -- rules ---------------------------------------------------------------

    @rule(specs=st.lists(_mention_spec, min_size=1, max_size=3))
    def append(self, specs: list[tuple[str, str, Polarity]]) -> None:
        mentions = [
            ConceptMention(
                name=name,
                normalized_name=name,
                kind=_KIND_BY_NAME[name],
                polarity=polarity,
                source_id=source,
                artifact_path=f"papers/{source}/{source}_Insights.md",
                extracted_at=self._now(),
            )
            for name, source, polarity in specs
        ]
        append_mentions(self.topic_dir, [m.to_jsonl_row() for m in mentions])
        self.model.extend(mentions)

    @rule()
    def rebuild(self) -> None:
        rows = read_mentions(self.topic_dir)
        merged = self._build(rows)
        now = self._now()
        for concept in merged:
            write_playbook(self.topic_dir, concept, now_iso=now)
        write_exports(self.topic_dir, merged)

        # Merge consistency: the persisted note is exactly the deterministic render.
        for concept in merged:
            note = note_path_for_slug(self.topic_dir, concept.slug)
            assert note is not None, f"no note written for {concept.slug}"
            assert note.read_text(encoding="utf-8") == render_playbook(concept)

        # Idempotence: an immediate identical rebuild rewrites nothing.
        later = self._now()
        for concept in merged:
            _, changed = write_playbook(self.topic_dir, concept, now_iso=later)
            assert changed is False, f"redundant rebuild rewrote {concept.slug}"

        # Order independence: the reversed mention log yields identical concepts.
        assert self._build(list(reversed(rows))) == merged

    @precondition(lambda self: bool(self._snapshot_slugs()))
    @rule(pick=st.integers(min_value=0, max_value=50))
    def rollback_to_snapshot(self, pick: int) -> None:
        slugs = self._snapshot_slugs()
        slug = slugs[pick % len(slugs)]
        snapshots = list_snapshots(self.topic_dir, slug)
        target = snapshots[pick % len(snapshots)]
        target_content = target.path.read_text(encoding="utf-8")

        result = rollback(self.topic_dir, slug, target.iso, now_iso=self._now())

        live = note_path_for_slug(self.topic_dir, slug)
        assert live is not None
        assert live.read_text(encoding="utf-8") == target_content

        if result.changed:
            # Rollup round-trip: the rewritten row reconstructs the snapshot's
            # own frontmatter, key-for-key on the load-bearing fields.
            fields = parse_note_fields(target_content)
            kind = str(fields.get("kind", ""))
            try:
                is_entity = ConceptKind(kind).is_entity
            except ValueError:
                is_entity = False
            rollup = (
                entities_jsonl_path(self.topic_dir)
                if is_entity
                else concepts_jsonl_path(self.topic_dir)
            )
            matching = [
                json.loads(line)
                for line in rollup.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("slug") == slug
            ]
            assert len(matching) == 1
            row = matching[0]
            assert row["normalized_name"] == fields.get("normalized_name")
            assert row["helpful_evidence"] == fields.get("helpful_evidence")
            assert row["harmful_evidence"] == fields.get("harmful_evidence")
            assert row["source_count"] == fields.get("source_count")
            assert row["contested"] == fields.get("contested")

    # -- invariants ----------------------------------------------------------

    @invariant()
    def mentions_log_matches_model(self) -> None:
        assert len(read_mentions(self.topic_dir)) == len(self.model)

    @invariant()
    def intervals_never_invert(self) -> None:
        for sub in ("concepts", "entities"):
            directory = self.topic_dir / sub
            if not directory.is_dir():
                continue
            for note in directory.glob("*.md"):
                fields = parse_note_fields(note.read_text(encoding="utf-8"))
                for key in ("helpful_evidence", "harmful_evidence"):
                    interval = fields.get(key)
                    if isinstance(interval, list) and len(interval) == 2:
                        lower, upper = interval
                        assert 0 <= lower <= upper, f"{note.name} {key}={interval}"


TestConceptPlaybookLifecycle = ConceptPlaybookMachine.TestCase
TestConceptPlaybookLifecycle.settings = settings(
    max_examples=30,
    stateful_step_count=24,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
