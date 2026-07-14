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
import re
import unicodedata
from pathlib import Path
from typing import Any, cast

from distill.concepts.normalize import canonicalize
from distill.concepts.records import ConceptKind, ConceptMention, Polarity, utcnow_iso
from distill.library.confined import read_confined_text
from distill.library.paths import strip_frontmatter
from distill.llm import RouterConfig
from distill.llm import call as llm_call
from distill.llm.json_extract import extract_json
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.concepts import EXTRACTION_PROMPT_ID, concept_extraction_prompt

logger = logging.getLogger(__name__)

__all__ = ["ExtractionResult", "extract_from_insight"]


_VALID_POLARITIES = {p.value for p in Polarity}
_VALID_KINDS = {k.value for k in ConceptKind}
_VALID_EVIDENCE_TYPES = {
    "background",
    "citation",
    "comparison",
    "empirical_result",
    "limitation",
    "methodology",
}
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_RAW_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_CONTROL_RE = re.compile(r"[`*_~]")


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
    evidence_text: str,
    source_id: str,
    artifact_path: str,
    extracted_at: str,
) -> ConceptMention | None:
    """Project one LLM row into a ``ConceptMention``, or ``None`` if invalid.

    Validation is deliberately permissive on optional fields and strict on
    required fields. The surface name and exact evidence span must occur in
    the visible insight body, and the evidence span must contain the name.
    Canonical identity is derived locally from that grounded surface form.
    """
    name_value = row.get("name")
    claim_value = row.get("claim_excerpt")
    kind_value = row.get("kind")
    polarity_value = row.get("polarity")
    required = (name_value, claim_value, kind_value, polarity_value)
    if not all(isinstance(value, str) for value in required):
        return None

    name = cast("str", name_value).strip()
    claim_excerpt = cast("str", claim_value).strip()
    kind_str = cast("str", kind_value).strip().lower()
    polarity_str = cast("str", polarity_value).strip().lower()
    normalized = canonicalize(name)

    if not name or not normalized or not claim_excerpt:
        return None
    if kind_str not in _VALID_KINDS:
        return None
    if polarity_str not in _VALID_POLARITIES:
        return None

    normalized_name = _normalize_grounding_text(name)
    normalized_claim = _normalize_grounding_text(claim_excerpt)
    if (
        not _contains_name(evidence_text, normalized_name)
        or normalized_claim not in evidence_text
        or not _contains_name(normalized_claim, normalized_name)
    ):
        return None

    evidence_type_value = row.get("evidence_type", "")
    if not isinstance(evidence_type_value, str):
        return None
    evidence_type = evidence_type_value.strip().lower()
    if evidence_type and evidence_type not in _VALID_EVIDENCE_TYPES:
        return None

    return ConceptMention(
        name=name,
        normalized_name=normalized,
        kind=ConceptKind(kind_str),
        polarity=Polarity(polarity_str),
        source_id=source_id,
        artifact_path=artifact_path,
        claim_excerpt=claim_excerpt,
        evidence_type=evidence_type,
        extracted_at=extracted_at,
    )


def _normalize_grounding_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _contains_name(text: str, normalized_name: str) -> bool:
    if not normalized_name:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_name)}(?!\w)", text) is not None


def _grounding_text(insight_content: str) -> str:
    body = strip_frontmatter(insight_content)
    visible_lines: list[str] = []
    in_fence = False
    for line in body.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            visible_lines.append(line)
    visible = "\n".join(visible_lines)
    visible = _MARKDOWN_LINK_RE.sub(" ", visible)
    visible = _RAW_URL_RE.sub(" ", visible)
    visible = _HTML_TAG_RE.sub(" ", visible)
    visible = _MARKDOWN_CONTROL_RE.sub("", visible)
    return _normalize_grounding_text(visible)


def extract_from_insight(
    insight_path: Path,
    *,
    topic: str,
    source_id: str,
    artifact_path: str,
    rc: RouterConfig,
    tracker: CostTracker | None = None,
    now_iso: str | None = None,
    insight_content: str | None = None,
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
    content = insight_content
    if content is None:
        content = read_confined_text(
            insight_path,
            insight_path.parent,
            max_bytes=4 * 1024 * 1024,
        )
    if content is None:
        raise OSError(f"Insight is unsafe, unreadable, or oversized: {insight_path}")
    evidence_text = _grounding_text(content)
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
            evidence_text=evidence_text,
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
