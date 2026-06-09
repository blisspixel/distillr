"""Unit tests for distill.prompts.claims: extraction + claim-synthesis prompts."""

from __future__ import annotations

from distill.claims.records import Claim, ClaimRole
from distill.prompts.claims import (
    CLAIM_EXTRACTION_PROMPT_ID,
    CLAIM_SYNTHESIS_PROMPT_ID,
    claim_extraction_prompt,
    claim_synthesis_prompt,
)


def _claim(text: str, role: ClaimRole, **kw) -> Claim:
    return Claim(
        claim_id="cid",
        source_id=kw.get("source_id", "src1"),
        artifact_path="papers/x/x_Insights.md",
        claim_text=text,
        rhetorical_role=role,
        dataset=kw.get("dataset", ""),
        metric=kw.get("metric", ""),
        role_confidence=kw.get("role_confidence", 0.8),
        extracted_at="2026-05-30T00:00:00Z",
    )


def test_extraction_prompt_has_topic_and_schema():
    prompt = claim_extraction_prompt("INSIGHT BODY", "robotics")
    assert "robotics" in prompt
    assert "INSIGHT BODY" in prompt
    assert "rhetorical_role" in prompt
    assert "role_confidence" in prompt
    # JSON-only instruction so downstream extract_json gets a clean array.
    assert "JSON array" in prompt


def test_prompt_ids_are_versioned():
    assert CLAIM_EXTRACTION_PROMPT_ID == "claims.extract.v1"
    # v3 adds the thesis / white-space rung.
    assert CLAIM_SYNTHESIS_PROMPT_ID == "claims.synthesis.v3"


def test_synthesis_prompt_has_thesis_rung():
    claims = [_claim("Rotary embeddings improve generalization.", ClaimRole.RESULT)]
    prompt = claim_synthesis_prompt("ai", claims)
    assert "Thesis and White Space" in prompt
    assert "WHITE SPACE" in prompt
    assert "FALSIFY" in prompt


def test_synthesis_prompt_demands_rigor_sections():
    # v2 ports the paper-grade structure onto the claim synthesis: a comparison
    # matrix, the "no single source" payoff, and open questions with resolution
    # criteria. These are the sections that make the output deeper than a recap.
    claims = [_claim("Rotary embeddings improve generalization.", ClaimRole.RESULT)]
    prompt = claim_synthesis_prompt("ai", claims)
    assert "Comparison Matrix" in prompt
    assert "What This Corpus Says That No Single Source Says" in prompt
    assert "Open Questions Worth Settling" in prompt
    # The matrix is a real table contract, one row per source.
    assert "| Source |" in prompt
    # Anti-enumeration guardrail is present so the model does not just list claims.
    assert "ANTI-PATTERN" in prompt


def test_synthesis_prompt_embeds_claims_with_handles():
    claims = [
        _claim("Rotary embeddings improve generalization.", ClaimRole.RESULT, dataset="ICEWS"),
        _claim("The method fails on long contexts.", ClaimRole.LIMITATION, source_id="src2"),
    ]
    prompt = claim_synthesis_prompt("ai", claims)
    # Each claim is numbered and citable.
    assert "[C1]" in prompt
    assert "[C2]" in prompt
    # Claim text, role, and source appear so the model can cluster and cite.
    assert "Rotary embeddings improve generalization." in prompt
    assert "(result" in prompt
    assert "dataset=ICEWS" in prompt
    assert "source=src1" in prompt
    assert "source=src2" in prompt
    # The contract instructs naming contradictions and per-claim citations.
    assert "contradiction" in prompt.lower()
    assert "ai" in prompt


def test_synthesis_prompt_surfaces_confidence():
    claims = [_claim("Shaky claim.", ClaimRole.CONCLUSION, role_confidence=0.2)]
    prompt = claim_synthesis_prompt("ai", claims)
    assert "conf 0.20" in prompt


def test_synthesis_prompt_applies_style_emphasis():
    # --style must reach the two-pass claim synthesis prompt, not be a silent
    # no-op as it was before.
    claims = [_claim("Rotary embeddings improve generalization.", ClaimRole.RESULT)]
    assert "EMPHASIS:" not in claim_synthesis_prompt("ai", claims)
    assert "EMPHASIS:" in claim_synthesis_prompt("ai", claims, style="exec")
