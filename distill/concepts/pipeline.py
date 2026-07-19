"""End-to-end orchestrator for the concept playbook layer.

Walks a topic directory, finds every ``_Insights.md``, runs extraction
for any source not already in ``mentions.jsonl``, then merges all
known mentions (including the historic ones) and writes the playbook
notes + jsonl exports.

This is the function both ``distill concepts <topic>`` (standalone) and
``--concepts`` on the ingest commands call. Keeping the orchestration
in one place is what makes the trigger surface a thin wrapper.

Idempotence guarantees:

- Re-running with no new insights does no LLM calls (every source_id
  is already in mentions.jsonl).
- Re-running with no new mentions writes no new playbook files
  (write_playbook is content-equal idempotent).
- Re-running with no new playbook content writes no new history entries.

The pipeline does *not* delete concept notes that drop below threshold
on refresh; they stay on disk with their current content. This is
deliberate: a concept that crossed threshold once is worth keeping as a
reference even if subsequent refreshes don't re-confirm it. The user
can prune manually if they want.
"""

# pyright: strict

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from distill.concepts.exports import write_exports
from distill.concepts.extract import extract_from_insight
from distill.concepts.locking import concept_transaction
from distill.concepts.merge import build_all
from distill.concepts.normalize import (
    DEFAULT_SOURCE_THRESHOLD,
    filter_by_threshold,
    group_mentions,
)
from distill.concepts.notes import (
    already_extracted_source_ids,
    append_mentions,
    build_playbook_ownership_index,
    ensure_extracted_sources_capacity,
    ensure_mention_store_append_capacity,
    read_extracted_sources,
    read_mentions,
    record_extracted_sources,
    write_playbook,
)
from distill.concepts.records import ConceptMention, utcnow_iso
from distill.library.confined_state import (
    atomic_write_confined_text,
    confined_file_identity,
    read_confined_state_text,
    unlink_confined_file,
)
from distill.library.insights import InsightRef, discover_insights, read_discovered_insight
from distill.llm import RouterConfig
from distill.parsing import strict_json_loads
from distill.pipeline.costs import BudgetExceededError, CostTracker

logger = logging.getLogger(__name__)
_MAX_DERIVED_DIRTY_BYTES = 64 * 1024

# InsightRef / discover_insights are re-exported from the shared
# ``distill.library.insights`` helper, lifted there so the claim layer can
# share the same topic walk.
__all__ = ["ConceptRunSummary", "InsightRef", "discover_insights", "run_concepts"]


def _derived_dirty_path(topic_dir: Path) -> Path:
    return topic_dir / ".distill-concepts-derived-dirty"


def _read_derived_dirty(topic_dir: Path) -> tuple[bool, dict[str, str]]:
    path = _derived_dirty_path(topic_dir)
    if confined_file_identity(path, topic_dir) is None:
        return False, {}
    content = read_confined_state_text(
        path,
        topic_dir,
        max_bytes=_MAX_DERIVED_DIRTY_BYTES,
    )
    if content is None:
        raise ValueError(f"Could not safely read derived-state recovery marker: {path}")
    try:
        loaded = strict_json_loads(content)
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid derived-state recovery marker at {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"Invalid derived-state recovery marker schema at {path}")
    marker = cast("dict[object, object]", loaded)
    if set(marker) != {"version", "provenance"}:
        raise ValueError(f"Invalid derived-state recovery marker schema at {path}")
    if marker.get("version") != 1:
        raise ValueError(f"Unsupported derived-state recovery marker version at {path}")
    raw_provenance = marker.get("provenance")
    if not isinstance(raw_provenance, dict):
        raise ValueError(f"Invalid derived-state recovery provenance at {path}")
    provenance: dict[str, str] = {}
    for key, value in cast("dict[object, object]", raw_provenance).items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"Invalid derived-state recovery provenance at {path}")
        provenance[key] = value
    return True, provenance


def _mark_derived_dirty(
    topic_dir: Path,
    *,
    provenance: dict[str, str] | None = None,
) -> None:
    _, existing = _read_derived_dirty(topic_dir)
    retained = existing or dict(provenance or {})
    encoded = json.dumps(
        {"version": 1, "provenance": retained},
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )
    if len(encoded.encode("utf-8")) > _MAX_DERIVED_DIRTY_BYTES:
        raise ValueError("Derived-state recovery provenance exceeds its storage limit")
    atomic_write_confined_text(_derived_dirty_path(topic_dir), encoded, topic_dir)


def _clear_derived_dirty(topic_dir: Path) -> None:
    path = _derived_dirty_path(topic_dir)
    identity = confined_file_identity(path, topic_dir)
    if identity is not None:
        unlink_confined_file(path, topic_dir, expected=identity)


@dataclass
class ConceptRunSummary:
    """What one ``run_concepts`` invocation did.

    Returned for callers that want to surface results (CLI, MCP). All
    counts are observable from the filesystem afterward; this dataclass
    just saves the caller a walk.
    """

    topic: str
    insights_scanned: int = 0
    insights_extracted: int = 0
    mentions_added: int = 0
    concepts_written: int = 0
    entities_written: int = 0
    concepts_unchanged: int = 0

    @property
    def notes_written(self) -> int:
        return self.concepts_written + self.entities_written

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "insights_scanned": self.insights_scanned,
            "insights_extracted": self.insights_extracted,
            "mentions_added": self.mentions_added,
            "concepts_written": self.concepts_written,
            "entities_written": self.entities_written,
            "concepts_unchanged": self.concepts_unchanged,
            "notes_written": self.notes_written,
        }


def _mentions_from_jsonl(rows: Iterable[dict[str, Any]]) -> list[ConceptMention]:
    """Hydrate rows already validated by the strict mention store."""
    return [ConceptMention.from_jsonl_row(row) for row in rows]


def run_concepts(
    topic: str,
    topic_dir: Path,
    *,
    rc: RouterConfig,
    threshold: int = DEFAULT_SOURCE_THRESHOLD,
    refresh: bool = False,
    tracker: CostTracker | None = None,
    now_iso: str | None = None,
) -> ConceptRunSummary:
    """Serialize and run one complete concept build for a topic."""

    if not discover_insights(topic_dir):
        logger.info("No _Insights.md found under %s", topic_dir)
        return ConceptRunSummary(topic=topic)
    with concept_transaction(topic_dir):
        return _run_concepts_transaction(
            topic,
            topic_dir,
            rc=rc,
            threshold=threshold,
            refresh=refresh,
            tracker=tracker,
            now_iso=now_iso,
        )


def _run_concepts_transaction(  # noqa: C901 -- sequential transaction orchestration
    topic: str,
    topic_dir: Path,
    *,
    rc: RouterConfig,
    threshold: int = DEFAULT_SOURCE_THRESHOLD,
    refresh: bool = False,
    tracker: CostTracker | None = None,
    now_iso: str | None = None,
) -> ConceptRunSummary:
    """Run the full extract -> merge -> render -> export pipeline for one topic.

    Args:
        topic: the topic name (display label; also used in frontmatter).
        topic_dir: the on-disk root for the topic, e.g.
            ``library/topics/<topic>``.
        rc: LLM router config; concept extraction routes via
            ``workload_tag="concepts"`` and ``DISTILL_CONCEPTS_MODEL``.
        threshold: minimum number of distinct sources to emit a concept
            note. Default 3 -- below this, the concept is filtered out
            as noise.
        refresh: when True, ignore the existing ``mentions.jsonl`` and
            re-extract from every insight. When False (default), skip
            insights whose ``source_id`` already appears in the log.
        tracker: optional cost tracker for telemetry.
        now_iso: injected timestamp for ``.history/`` naming and
            ``extracted_at`` fields. Production callers omit; tests
            supply a fixed string for reproducibility.
    """
    summary = ConceptRunSummary(topic=topic)
    refs = discover_insights(topic_dir)
    summary.insights_scanned = len(refs)
    if not refs:
        logger.info("No _Insights.md found under %s", topic_dir)
        return summary

    timestamp = now_iso or utcnow_iso()
    # Skip insights already extracted. Union the mention rows with the
    # extracted-sources ledger so a source that produced zero mentions (no row in
    # mentions.jsonl, but a valid empty extraction) is still recognized as done
    # and not re-extracted -- and re-billed -- on every subsequent run.
    derived_dirty, extraction_provenance = _read_derived_dirty(topic_dir)
    mention_sources = already_extracted_source_ids(topic_dir)
    completed_sources = read_extracted_sources(topic_dir)
    missing_completion = mention_sources - completed_sources
    if missing_completion:
        # A durable mention row is canonical evidence that extraction completed.
        # Repair a ledger publication interrupted after the mention append before
        # issuing any more provider work.
        record_extracted_sources(topic_dir, missing_completion)
        completed_sources.update(missing_completion)
        _mark_derived_dirty(topic_dir, provenance=extraction_provenance)
        derived_dirty = True
    seen = set[str]() if refresh else mention_sources | completed_sources

    pending = [r for r in refs if r.source_id not in seen]
    if pending:
        ensure_extracted_sources_capacity(topic_dir, (ref.source_id for ref in pending))
        ensure_mention_store_append_capacity(topic_dir)
    summary.insights_extracted = len(pending)

    new_rows: list[dict[str, Any]] = []
    budget_error: BudgetExceededError | None = None
    for ref in pending:
        try:
            content = read_discovered_insight(ref, topic_dir.parent.parent)
            if content is None:
                logger.warning("Extraction skipped changed or unsafe insight %s", ref.path)
                continue
            result = extract_from_insight(
                ref.path,
                topic=topic,
                source_id=ref.source_id,
                artifact_path=ref.artifact_path,
                rc=rc,
                tracker=tracker,
                now_iso=timestamp,
                insight_content=content,
            )
        except BudgetExceededError as exc:
            budget_error = exc
            break
        except Exception as exc:
            logger.warning("Extraction failed for %s: %s", ref.path, exc)
            continue
        source_rows = [mention.to_jsonl_row() for mention in result.mentions]
        if not extraction_provenance:
            extraction_provenance = result.provenance
        # Evidence is durable before completion. Publishing each source as its
        # own checkpoint preserves prior work when a later source reaches the
        # budget boundary or fails.
        if source_rows:
            append_mentions(topic_dir, source_rows)
            _mark_derived_dirty(topic_dir, provenance=extraction_provenance)
            derived_dirty = True
            new_rows.extend(source_rows)
            summary.mentions_added += len(source_rows)
        # Record every successfully processed source, including a zero-mention
        # result, only after its evidence batch is durable.
        record_extracted_sources(topic_dir, [ref.source_id])

    # Refresh path always rebuilds; otherwise only rebuild when new mentions
    # arrived. Without this short-circuit, a second run on an unchanged
    # corpus would still re-render every concept note because the merge step
    # reads provenance from the *current* extraction run (which is empty on
    # idle runs), and that empty provenance differs from the existing note's
    # frontmatter -- producing spurious .history snapshots on every refresh.
    should_rebuild = (
        bool(new_rows)
        or bool(missing_completion)
        or derived_dirty
        or (refresh and budget_error is None)
    )
    if not should_rebuild:
        if budget_error is not None:
            raise budget_error
        return summary

    all_rows = read_mentions(topic_dir)
    all_mentions = _mentions_from_jsonl(all_rows)
    if not all_mentions:
        _clear_derived_dirty(topic_dir)
        if budget_error is not None:
            raise budget_error
        return summary

    grouped = group_mentions(all_mentions)
    filtered = filter_by_threshold(grouped, min_sources=threshold)
    merged = build_all(filtered.items(), topic=topic, provenance=extraction_provenance)

    occupied_paths: set[Path] = set()
    ownership = build_playbook_ownership_index(
        topic_dir,
        occupied_paths=occupied_paths,
    )
    for concept in merged:
        path, changed = write_playbook(
            topic_dir,
            concept,
            now_iso=timestamp,
            owned_paths=list(ownership.get(concept.normalized_name, ())),
            occupied_paths=occupied_paths,
        )
        ownership[concept.normalized_name] = [path]
        if changed:
            if concept.kind.is_entity:
                summary.entities_written += 1
            else:
                summary.concepts_written += 1
        else:
            summary.concepts_unchanged += 1

    write_exports(topic_dir, merged)
    _clear_derived_dirty(topic_dir)
    if budget_error is not None:
        raise budget_error
    return summary
