"""End-to-end orchestrator for the claim layer (0.9 two-pass synthesis, pass 1).

Walks a topic directory, finds every ``_Insights.md`` via the shared
``library.insights`` helper, runs claim extraction for any source not already
in ``claims.jsonl``, and appends the new claims. The claim-aware synthesis
(pass 2) reads the accumulated ``claims.jsonl`` separately.

This mirrors ``concepts.pipeline.run_concepts`` and its idempotence guarantees:

- Re-running with no new insights does no LLM calls (every source_id is
  already in ``claims.jsonl``).
- ``refresh=True`` re-extracts from every insight regardless of the log.

The pipeline does not deduplicate across runs beyond ``source_id`` skipping:
``refresh`` intentionally re-appends, so the synthesis pass should read the
latest claim per ``claim_id`` if it needs strict dedup. For the default
(non-refresh) path each source is extracted exactly once.
"""

# pyright: strict

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from distill.claims.exports import (
    already_extracted_source_ids,
    append_claims,
    read_claims,
    read_extracted_sources,
    record_extracted_sources,
)
from distill.claims.extract import extract_claims_from_insight
from distill.claims.records import Claim, utcnow_iso
from distill.library.insights import InsightRef, discover_insights, read_discovered_insight
from distill.llm import RouterConfig
from distill.parsing import parse_ascii_uint
from distill.pipeline.costs import BudgetExceededError, CostTracker

logger = logging.getLogger(__name__)

__all__ = ["ClaimsSummary", "pending_claim_extraction_count", "run_claims"]

# Cap on insights extracted in a single run. Two-pass synthesis runs one paid LLM
# call per pending insight, and it is reachable from the MCP ``synthesize`` tool
# (``two_pass=true``), so a prompt-injected agent could induce one tool call that
# fans out into thousands of calls on a large topic. A per-call ceiling bounds
# that amplification; because every processed source is recorded in the
# extracted-sources ledger, the remainder simply extracts on the next run rather
# than being dropped. ``DISTILL_CLAIMS_MAX_INSIGHTS`` overrides it (0 = unlimited).
_DEFAULT_MAX_INSIGHTS_PER_RUN = 250


def _max_insights_per_run() -> int:
    raw = os.environ.get("DISTILL_CLAIMS_MAX_INSIGHTS", "").strip()
    parsed = parse_ascii_uint(raw)
    return parsed if parsed is not None else _DEFAULT_MAX_INSIGHTS_PER_RUN


def _pending_claim_refs(
    topic_dir: Path,
    *,
    refresh: bool = False,
) -> tuple[list[InsightRef], list[InsightRef], int]:
    """Return all refs, this run's bounded pending refs, and the uncapped count."""
    refs = discover_insights(topic_dir)
    seen = (
        set[str]()
        if refresh
        else already_extracted_source_ids(topic_dir) | read_extracted_sources(topic_dir)
    )
    pending = [ref for ref in refs if ref.source_id not in seen]
    uncapped_count = len(pending)
    cap = _max_insights_per_run()
    if cap:
        pending = pending[: min(cap, uncapped_count)]
    return refs, pending, uncapped_count


def pending_claim_extraction_count(topic_dir: Path) -> int:
    """Return the claim extraction calls the next two-pass run will make."""
    _, pending, _ = _pending_claim_refs(topic_dir)
    return len(pending)


@dataclass
class ClaimsSummary:
    """What one ``run_claims`` invocation did.

    Counts are observable from ``claims.jsonl`` afterward; this dataclass saves
    the caller (CLI, MCP) a re-read. Mirrors ``concepts.ConceptRunSummary``.
    """

    topic: str
    insights_scanned: int = 0
    insights_extracted: int = 0
    claims_added: int = 0
    total_claims: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "insights_scanned": self.insights_scanned,
            "insights_extracted": self.insights_extracted,
            "claims_added": self.claims_added,
            "total_claims": self.total_claims,
        }


def run_claims(
    topic: str,
    topic_dir: Path,
    *,
    rc: RouterConfig,
    refresh: bool = False,
    tracker: CostTracker | None = None,
    now_iso: str | None = None,
) -> ClaimsSummary:
    """Run the extract -> append pass over every insight in a topic.

    Args:
        topic: the topic name (display label; also passed to the extractor for
            topical-relevance judgement).
        topic_dir: on-disk topic root, e.g. ``library/topics/<topic>``.
        rc: LLM router config; claim extraction routes via
            ``workload_tag="concepts"`` (shared cheap-extraction workload).
        refresh: when True, re-extract from every insight regardless of the
            existing ``claims.jsonl``. When False (default), skip insights whose
            ``source_id`` already appears in the store.
        tracker: optional cost tracker for telemetry.
        now_iso: injected timestamp for ``extracted_at``. Production callers
            omit; tests supply a fixed string for reproducibility.

    Returns a ``ClaimsSummary`` of what was scanned, extracted, and added.
    """
    summary = ClaimsSummary(topic=topic)
    refs, pending, uncapped_count = _pending_claim_refs(topic_dir, refresh=refresh)
    summary.insights_scanned = len(refs)
    if not refs:
        logger.info("No _Insights.md found under %s", topic_dir)
        return summary

    timestamp = now_iso or utcnow_iso()
    # Bound per-run spend: process at most _max_insights_per_run() insights, the
    # rest fall to the next run (they stay pending via the extracted-sources
    # ledger, so nothing is lost -- only batched).
    if len(pending) < uncapped_count:
        logger.warning(
            "Claim extraction capping at %d of %d pending insights for %s "
            "(set DISTILL_CLAIMS_MAX_INSIGHTS=0 to disable); the rest extract next run.",
            len(pending),
            uncapped_count,
            topic,
        )
    summary.insights_extracted = len(pending)

    new_claims: list[Claim] = []
    processed: list[str] = []
    for ref in pending:
        try:
            content = read_discovered_insight(ref, topic_dir.parent.parent)
            if content is None:
                logger.warning("Claim extraction skipped changed or unsafe insight %s", ref.path)
                continue
            result = extract_claims_from_insight(
                ref.path,
                topic=topic,
                source_id=ref.source_id,
                artifact_path=ref.artifact_path,
                rc=rc,
                tracker=tracker,
                now_iso=timestamp,
                insight_content=content,
            )
        except BudgetExceededError:
            raise
        except Exception as exc:
            logger.warning("Claim extraction failed for %s: %s", ref.path, exc)
            continue
        new_claims.extend(result.claims)
        # Record every successfully-processed source -- even a zero-claim one --
        # so it is not re-extracted on the next run.
        processed.append(ref.source_id)

    if new_claims:
        append_claims(topic_dir, new_claims)
        summary.claims_added = len(new_claims)

    record_extracted_sources(topic_dir, processed)

    # Count distinct claims, not raw rows: claims.jsonl is append-only, so a
    # --refresh re-appends a source's claims and len(read_claims) would double-
    # count them. Dedup by claim_id (stable hash of normalized text) for an
    # honest total.
    summary.total_claims = len({c.claim_id for c in read_claims(topic_dir)})
    return summary
