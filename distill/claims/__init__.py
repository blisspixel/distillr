"""Per-topic claim layer for two-pass synthesis (0.9).

The claim layer is the structured intermediate that makes single-prompt
synthesis scale: instead of re-reading every ``_Insights.md`` into one giant
prompt, pass 1 extracts atomic claims into an append-only ``claims.jsonl``,
and pass 2 synthesizes over the claim set -- clustering, naming
contradictions, and citing each statement back to specific claims.

Architecture (data flow), mirroring the 0.8 concept layer:

    per-insight claim extraction (LLM)
            v
    claim records (claims.jsonl, append-only)
            v
    claim-aware synthesis pass (LLM, clusters + contradictions + citations)

Extraction is the only per-source LLM step; everything between the two passes
(parse, dedup, append, read) is pure Python. The layer depends only on
foundational modules (``library``, ``llm``, ``prompts``, ``pipeline.costs``),
enforced by an import-linter contract.

Module surface:

- ``records`` -- the ``Claim`` dataclass and ``ClaimRole`` enum.
- ``extract`` -- LLM-driven claim extraction from one insight file.
- ``exports`` -- the ``claims.jsonl`` append-only store (read / append / dedup).
- ``pipeline`` -- ``run_claims(topic, ...)`` end-to-end pass-1 orchestrator.
"""

from __future__ import annotations

from distill.claims.pipeline import ClaimsSummary, run_claims
from distill.claims.records import Claim, ClaimRole

__all__ = [
    "Claim",
    "ClaimRole",
    "ClaimsSummary",
    "run_claims",
]
