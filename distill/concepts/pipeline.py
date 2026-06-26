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

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from distill.concepts.exports import write_exports
from distill.concepts.extract import extract_from_insight
from distill.concepts.merge import build_all
from distill.concepts.normalize import (
    DEFAULT_SOURCE_THRESHOLD,
    filter_by_threshold,
    group_mentions,
)
from distill.concepts.notes import (
    already_extracted_source_ids,
    append_mentions,
    read_extracted_sources,
    record_extracted_sources,
    write_playbook,
)
from distill.concepts.records import ConceptMention, utcnow_iso
from distill.library.insights import InsightRef, discover_insights
from distill.llm import RouterConfig
from distill.pipeline.costs import CostTracker

logger = logging.getLogger(__name__)

# InsightRef / discover_insights are re-exported from the shared
# ``distill.library.insights`` helper, lifted there so the claim layer can
# share the same topic walk.
__all__ = ["ConceptRunSummary", "InsightRef", "discover_insights", "run_concepts"]


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
    """Hydrate ``ConceptMention`` records from ``mentions.jsonl`` rows."""
    out: list[ConceptMention] = []
    for row in rows:
        try:
            out.append(ConceptMention.from_jsonl_row(row))
        except (KeyError, ValueError) as exc:
            logger.warning("Skipping malformed mentions.jsonl row: %s", exc)
    return out


def run_concepts(  # noqa: C901 -- orchestrator, complexity from sequential pipeline steps
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
    seen = (
        set[str]()
        if refresh
        else already_extracted_source_ids(topic_dir) | read_extracted_sources(topic_dir)
    )

    pending = [r for r in refs if r.source_id not in seen]
    summary.insights_extracted = len(pending)

    new_rows: list[dict[str, Any]] = []
    processed: list[str] = []
    extraction_provenance: dict[str, str] = {}
    for ref in pending:
        try:
            result = extract_from_insight(
                ref.path,
                topic=topic,
                source_id=ref.source_id,
                artifact_path=ref.artifact_path,
                rc=rc,
                tracker=tracker,
                now_iso=timestamp,
            )
        except Exception as exc:
            logger.warning("Extraction failed for %s: %s", ref.path, exc)
            continue
        for mention in result.mentions:
            new_rows.append(mention.to_jsonl_row())
        # Record every successfully-processed source -- even a zero-mention one --
        # so it is not re-extracted on the next run.
        processed.append(ref.source_id)
        if not extraction_provenance:
            extraction_provenance = result.provenance

    if new_rows:
        append_mentions(topic_dir, new_rows)
        summary.mentions_added = len(new_rows)
    record_extracted_sources(topic_dir, processed)

    # Refresh path always rebuilds; otherwise only rebuild when new mentions
    # arrived. Without this short-circuit, a second run on an unchanged
    # corpus would still re-render every concept note because the merge step
    # reads provenance from the *current* extraction run (which is empty on
    # idle runs), and that empty provenance differs from the existing note's
    # frontmatter -- producing spurious .history snapshots on every refresh.
    if not refresh and not new_rows:
        return summary

    from distill.concepts.notes import read_mentions

    all_rows = read_mentions(topic_dir)
    all_mentions = _mentions_from_jsonl(all_rows)
    if not all_mentions:
        return summary

    grouped = group_mentions(all_mentions)
    filtered = filter_by_threshold(grouped, min_sources=threshold)
    merged = build_all(filtered.items(), topic=topic, provenance=extraction_provenance)

    for concept in merged:
        _, changed = write_playbook(topic_dir, concept, now_iso=timestamp)
        if changed:
            if concept.kind.is_entity:
                summary.entities_written += 1
            else:
                summary.concepts_written += 1
        else:
            summary.concepts_unchanged += 1

    write_exports(topic_dir, merged)
    return summary
