"""LLM-driven extraction of concept and entity mentions from an insight file.

This is the only LLM-burning step in the playbook layer. Everything
downstream (normalize, merge, render) is pure Python.

Contract:

- Input: the on-disk path of an ``_Insights.md`` file plus the source's
  stable identifier and source-relative artifact path.
- Output: a list of ``ConceptMention`` records, ready to append to
  ``mentions.jsonl`` and feed the normalize layer.
- LLM call is tagged ``workload_tag="concepts"`` and routes through the
  per-workload override mechanism (DISTILL_CONCEPTS_MODEL etc.) so the
  cheap-extraction model is independent of the analysis model.

Error handling: extraction is best-effort. A malformed LLM response,
JSON parse failure, or missing required field skips that mention but
doesn't fail the whole extraction. The pipeline tolerates partial
results because partial coverage is still useful -- the merge step's
threshold filter will catch noise either way.
"""

# pyright: strict

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from distill.concepts.records import ConceptKind, ConceptMention, Polarity, utcnow_iso
from distill.llm import RouterConfig
from distill.llm import call as llm_call
from distill.llm.json_extract import extract_json
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.concepts import EXTRACTION_PROMPT_ID, concept_extraction_prompt

logger = logging.getLogger(__name__)

__all__ = ["ExtractionResult", "extract_from_insight"]


_VALID_POLARITIES = {p.value for p in Polarity}
_VALID_KINDS = {k.value for k in ConceptKind}


class ExtractionResult:
    """Container for what one extraction LLM call produced.

    Holds the parsed mentions plus the raw response so the caller can
    record token telemetry and surface any soft failures. ``provenance``
    captures the model + prompt ID for downstream MergedConcept records.
    """

    __slots__ = ("mentions", "model", "prompt_id", "skipped_rows")

    def __init__(
        self,
        mentions: list[ConceptMention],
        model: str,
        prompt_id: str,
        skipped_rows: list[str],
    ) -> None:
        self.mentions = mentions
        self.model = model
        self.prompt_id = prompt_id
        self.skipped_rows = skipped_rows

    @property
    def provenance(self) -> dict[str, str]:
        return {"model": self.model, "model_version": self.model, "prompt_id": self.prompt_id}


def _row_to_mention(
    row: dict[str, Any],
    *,
    source_id: str,
    artifact_path: str,
    extracted_at: str,
) -> ConceptMention | None:
    """Project one LLM row into a ``ConceptMention``, or ``None`` if invalid.

    Validation is deliberately permissive on optional fields and strict
    on required fields. A row missing ``name`` / ``normalized_name`` /
    ``kind`` / ``polarity`` is dropped (and logged via the caller's
    skipped_rows list) -- we cannot store an evidence record without
    knowing what evidence it is or what side it falls on.
    """
    name = str(row.get("name", "")).strip()
    normalized = str(row.get("normalized_name", "")).strip().lower()
    kind_str = str(row.get("kind", "")).strip().lower()
    polarity_str = str(row.get("polarity", "")).strip().lower()

    if not name or not normalized:
        return None
    if kind_str not in _VALID_KINDS:
        return None
    if polarity_str not in _VALID_POLARITIES:
        return None

    return ConceptMention(
        name=name,
        normalized_name=normalized,
        kind=ConceptKind(kind_str),
        polarity=Polarity(polarity_str),
        source_id=source_id,
        artifact_path=artifact_path,
        claim_excerpt=str(row.get("claim_excerpt", "")).strip(),
        evidence_type=str(row.get("evidence_type", "")).strip(),
        extracted_at=extracted_at,
    )


def extract_from_insight(
    insight_path: Path,
    *,
    topic: str,
    source_id: str,
    artifact_path: str,
    rc: RouterConfig,
    tracker: CostTracker | None = None,
    now_iso: str | None = None,
) -> ExtractionResult:
    """Run extraction over one ``_Insights.md`` file.

    ``insight_path`` must exist; missing files raise ``FileNotFoundError``
    rather than silently returning an empty result -- that would mask a
    real configuration bug.

    ``source_id`` is the stable per-source identifier (arXiv ID, video
    ID, page slug). It becomes the merge key.

    ``artifact_path`` is the topic-relative path used for backlinks
    (e.g. ``papers/romem/romem_Insights.md``). The renderer derives
    the wiki-link target from this.

    Telemetry: if ``tracker`` is provided, the token usage is recorded
    with ``call_type="concepts_extract"`` so ``distill costs`` can show
    the playbook's spend separately.
    """
    if not insight_path.exists():
        raise FileNotFoundError(f"Insight not found: {insight_path}")
    content = insight_path.read_text(encoding="utf-8")
    extracted_at = now_iso or utcnow_iso()

    prompt = concept_extraction_prompt(content, topic)
    response = llm_call(
        rc,
        workload_tag="concepts",
        prompt=prompt,
        call_type="concepts_extract",
        usage_tracker=tracker,
    )

    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="concepts_extract"))

    parsed = extract_json(response.text)
    if not isinstance(parsed, list):
        logger.warning(
            "Concept extraction returned non-list response for %s (got %s); skipping",
            insight_path,
            type(parsed).__name__,
        )
        return ExtractionResult([], response.model, EXTRACTION_PROMPT_ID, [response.text[:200]])

    mentions: list[ConceptMention] = []
    skipped: list[str] = []
    for raw in parsed:
        if not isinstance(raw, dict):
            skipped.append(repr(raw)[:80])
            continue
        row = cast("dict[str, Any]", raw)
        mention = _row_to_mention(
            row,
            source_id=source_id,
            artifact_path=artifact_path,
            extracted_at=extracted_at,
        )
        if mention is None:
            skipped.append(repr(row)[:80])
            continue
        mentions.append(mention)

    if skipped:
        logger.info(
            "Concept extraction dropped %d invalid rows from %s", len(skipped), insight_path
        )

    return ExtractionResult(
        mentions=mentions,
        model=response.model,
        prompt_id=EXTRACTION_PROMPT_ID,
        skipped_rows=skipped,
    )
