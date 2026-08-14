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
    ensure_claim_store_append_capacity,
    ensure_extracted_sources_capacity,
    read_claims,
    read_extracted_sources,
    record_extracted_sources,
)
from distill.claims.extract import extract_claims_from_insight
from distill.claims.locking import claims_transaction
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


def _validated_source_claims(ref: InsightRef, claims: list[Claim]) -> list[Claim]:
    """Reject a provider batch that crosses source boundaries or duplicates IDs."""

    claim_ids: set[str] = set()
    for claim in claims:
        if claim.source_id != ref.source_id:
            raise ValueError(
                f"Claim {claim.claim_id!r} belongs to source {claim.source_id!r}, "
                f"not the active source {ref.source_id!r}"
            )
        if claim.artifact_path != ref.artifact_path:
            raise ValueError(
                f"Claim {claim.claim_id!r} has artifact path {claim.artifact_path!r}, "
                f"not {ref.artifact_path!r}"
            )
        if claim.claim_id in claim_ids:
            raise ValueError(f"Claim batch repeats claim_id {claim.claim_id!r}")
        claim_ids.add(claim.claim_id)
    return claims


def _pending_claim_refs(
    topic_dir: Path,
    *,
    refresh: bool = False,
    repair_completion_ledger: bool = False,
) -> tuple[list[InsightRef], list[InsightRef], int]:
    """Return all refs, this run's bounded pending refs, and the uncapped count."""
    refs = discover_insights(topic_dir)
    claim_sources = already_extracted_source_ids(topic_dir)
    completed_sources = read_extracted_sources(topic_dir)
    # A durable claim batch is canonical evidence that extraction completed.
    # If publishing the redundant completion ledger failed after that append,
    # repair it before any new provider work so the source does not remain in
    # a permanently split checkpoint state.
    missing_completion = claim_sources - completed_sources
    if repair_completion_ledger and missing_completion:
        record_extracted_sources(topic_dir, missing_completion)
        completed_sources.update(missing_completion)
    seen = set[str]() if refresh else claim_sources | completed_sources
    pending = [ref for ref in refs if ref.source_id not in seen]
    uncapped_count = len(pending)
    cap = _max_insights_per_run()
    if cap:
        pending = pending[: min(cap, uncapped_count)]
    if pending:
        ensure_extracted_sources_capacity(topic_dir, (ref.source_id for ref in pending))
        ensure_claim_store_append_capacity(topic_dir)
    return refs, pending, uncapped_count


def pending_claim_extraction_count(topic_dir: Path) -> int:
    """Return the claim extraction calls the next two-pass run will make."""

    with claims_transaction(topic_dir):
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
    with claims_transaction(topic_dir):
        return _run_claims_transaction(
            topic,
            topic_dir,
            rc=rc,
            refresh=refresh,
            tracker=tracker,
            now_iso=now_iso,
        )


def _run_claims_transaction(
    topic: str,
    topic_dir: Path,
    *,
    rc: RouterConfig,
    refresh: bool,
    tracker: CostTracker | None,
    now_iso: str | None,
) -> ClaimsSummary:
    """Run claims extraction while the caller owns the topic transaction."""

    summary = ClaimsSummary(topic=topic)
    refs, pending, uncapped_count = _pending_claim_refs(
        topic_dir,
        refresh=refresh,
        repair_completion_ledger=True,
    )
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
        claims = _validated_source_claims(ref, result.claims)
        # Evidence is durable before completion. If the ledger update fails,
        # claim-producing sources are repaired from claims.jsonl on the next
        # run. A zero-claim source has no independent evidence receipt, so a
        # failed ledger write aborts immediately and leaves that source pending;
        # replay is safer than publishing unproven completion.
        if claims:
            append_claims(topic_dir, claims)
            summary.claims_added += len(claims)
        if result.parsed:
            record_extracted_sources(topic_dir, [ref.source_id])

    # Count distinct claims, not raw rows: claims.jsonl is append-only, so a
    # --refresh re-appends a source's claims and len(read_claims) would double-
    # count them. Dedup by claim_id (stable hash of normalized text) for an
    # honest total.
    summary.total_claims = len({c.claim_id for c in read_claims(topic_dir)})
    return summary
