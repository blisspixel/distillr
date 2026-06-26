"""LLM-driven extraction of claims from one insight file.

The only LLM-burning step in the claim layer. Everything downstream (parse,
dedup, append, synthesize) is pure Python over the structured rows.

Contract mirrors ``concepts.extract``:

- Input: an ``_Insights.md`` path plus the source's stable id and topic-
  relative artifact path.
- Output: a list of ``Claim`` records ready to append to ``claims.jsonl``.
- The LLM call is tagged ``workload_tag="concepts"`` (the cheap-extraction
  workload; claims and concepts share the extraction model override) with
  ``call_type="claims_extract"`` so cost telemetry separates the two.

Error handling is best-effort: a malformed response, a JSON parse failure, or
a row missing its required fields skips that claim but never fails the whole
extraction. Partial coverage is still useful.
"""

# pyright: strict

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, cast

from distill.claims.records import Claim, ClaimRole, utcnow_iso
from distill.llm import RouterConfig
from distill.llm import call as llm_call
from distill.llm.json_extract import extract_json
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.claims import CLAIM_EXTRACTION_PROMPT_ID, claim_extraction_prompt

logger = logging.getLogger(__name__)

__all__ = ["ClaimExtractionResult", "claim_id_for", "extract_claims_from_insight"]


_VALID_ROLES = {r.value for r in ClaimRole}


def claim_id_for(source_id: str, claim_text: str) -> str:
    """Derive a stable claim id from ``source_id`` and the claim text.

    Deterministic so re-extracting the same assertion from the same source
    yields the same id -- this is what lets downstream per-claim scoring cache
    by ``claim_id``. The hash is over the normalized (whitespace-collapsed,
    lowercased) claim text so trivial reformatting does not fork the id.
    """
    normalized = " ".join(claim_text.lower().split())
    # usedforsecurity=False: this is a content-addressing id, not a security hash.
    digest = hashlib.sha1(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"{source_id}:{digest}"


class ClaimExtractionResult:
    """What one extraction LLM call produced: parsed claims plus provenance."""

    __slots__ = ("claims", "model", "prompt_id", "skipped_rows")

    def __init__(
        self,
        claims: list[Claim],
        model: str,
        prompt_id: str,
        skipped_rows: list[str],
    ) -> None:
        self.claims = claims
        self.model = model
        self.prompt_id = prompt_id
        self.skipped_rows = skipped_rows

    @property
    def provenance(self) -> dict[str, str]:
        return {"model": self.model, "model_version": self.model, "prompt_id": self.prompt_id}


def _clamp_confidence(value: Any) -> float:
    """Coerce an arbitrary JSON value into a 0.0-1.0 confidence, default 0.5."""
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, conf))


def _row_to_claim(
    row: dict[str, Any],
    *,
    source_id: str,
    artifact_path: str,
    extracted_at: str,
) -> Claim | None:
    """Project one LLM row into a ``Claim``, or ``None`` if invalid.

    Strict on the two required fields (``claim_text`` and a valid
    ``rhetorical_role``); permissive on every optional field.
    """
    claim_text = str(row.get("claim_text", "")).strip()
    role_str = str(row.get("rhetorical_role", "")).strip().lower()

    if not claim_text:
        return None
    if role_str not in _VALID_ROLES:
        return None

    return Claim(
        claim_id=claim_id_for(source_id, claim_text),
        source_id=source_id,
        artifact_path=artifact_path,
        claim_text=claim_text,
        rhetorical_role=ClaimRole(role_str),
        subject=str(row.get("subject", "")).strip(),
        predicate=str(row.get("predicate", "")).strip(),
        object=str(row.get("object", "")).strip(),
        dataset=str(row.get("dataset", "")).strip(),
        metric=str(row.get("metric", "")).strip(),
        evidence_type=str(row.get("evidence_type", "")).strip(),
        role_confidence=_clamp_confidence(row.get("role_confidence", 0.5)),
        extracted_at=extracted_at,
    )


def extract_claims_from_insight(
    insight_path: Path,
    *,
    topic: str,
    source_id: str,
    artifact_path: str,
    rc: RouterConfig,
    tracker: CostTracker | None = None,
    now_iso: str | None = None,
) -> ClaimExtractionResult:
    """Run claim extraction over one ``_Insights.md`` file.

    ``insight_path`` must exist; a missing file raises ``FileNotFoundError``
    rather than silently returning empty (that would mask a config bug).

    Telemetry: when ``tracker`` is provided the token usage is recorded with
    ``call_type="claims_extract"`` so ``distill costs`` shows the claim layer's
    spend separately from analysis and concept extraction.
    """
    if not insight_path.exists():
        raise FileNotFoundError(f"Insight not found: {insight_path}")
    content = insight_path.read_text(encoding="utf-8")
    extracted_at = now_iso or utcnow_iso()

    prompt = claim_extraction_prompt(content, topic)
    response = llm_call(
        rc,
        workload_tag="concepts",
        prompt=prompt,
        call_type="claims_extract",
    )

    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="claims_extract"))

    parsed = extract_json(response.text)
    if not isinstance(parsed, list):
        logger.warning(
            "Claim extraction returned non-list response for %s (got %s); skipping",
            insight_path,
            type(parsed).__name__,
        )
        return ClaimExtractionResult(
            [], response.model, CLAIM_EXTRACTION_PROMPT_ID, [response.text[:200]]
        )

    claims: list[Claim] = []
    skipped: list[str] = []
    seen_ids: set[str] = set()
    for raw in parsed:
        if not isinstance(raw, dict):
            skipped.append(repr(raw)[:80])
            continue
        row = cast("dict[str, Any]", raw)
        claim = _row_to_claim(
            row,
            source_id=source_id,
            artifact_path=artifact_path,
            extracted_at=extracted_at,
        )
        if claim is None:
            skipped.append(repr(row)[:80])
            continue
        # Deduplicate within a single extraction: two near-identical rows
        # collapse to one claim_id and would otherwise double-count.
        if claim.claim_id in seen_ids:
            continue
        seen_ids.add(claim.claim_id)
        claims.append(claim)

    if skipped:
        logger.info("Claim extraction dropped %d invalid rows from %s", len(skipped), insight_path)

    return ClaimExtractionResult(
        claims=claims,
        model=response.model,
        prompt_id=CLAIM_EXTRACTION_PROMPT_ID,
        skipped_rows=skipped,
    )
