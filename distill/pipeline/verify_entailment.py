# pyright: strict
# pyright: reportMissingImports=false
"""The entailment tier: prose claims and named entities, checked locally.

Layers on the deterministic tier (`distill.pipeline.verify`) and never
replaces it -- design in ``docs/design/entailment-tier.md``, settled by the
claim-verification dogfood corpus. The deterministic tier owns numeric
grounding; this tier scores whole prose claims against the source receipt
with a small local cross-encoder (HHEM-2.1-Open by default), closing the
limitation classes the deterministic tier names: derived arithmetic,
context-blind support, and prose claims with no checkable tokens at all.

Per the invariants, LLM proposes and Python decides: the checker is a
~110M-parameter classifier emitting a calibrated factual-consistency score
that a threshold turns into a flag -- not an LLM-as-judge-of-record, and
deliberately not the analysis model (the checker must not share its biases).

The heavy dependency (transformers + torch) is an optional extra
(``pip install distillr[entailment]``); when it is absent the tier is
skipped silently and the deterministic tier stands alone, exactly as before.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from distill.library.paths import strip_frontmatter

__all__ = [
    "EntailmentChecker",
    "EntailmentClaim",
    "EntailmentReport",
    "chunk_evidence",
    "entailment_available",
    "evaluate_entailment",
    "extract_entailment_claims",
    "load_default_checker",
    "resolve_entailment_threshold",
]

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 0.5
_MIN_CLAIM_CHARS = 40  # shorter prose units are headings/fragments, not claims
_CHUNK_CHARS = 1_500  # HHEM input budget, with headroom for the claim text
_TOP_K_CHUNKS = 3  # per-claim evidence candidates by lexical overlap

_HHEM_MODEL_ID = "vectara/hallucination_evaluation_model"
_HHEM_REVISION = "8e4a2e6e96c708cc76c2344f7e4757df2515292c"  # pinned for safety (bandit B615) and reproducibility

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_URL_RE = re.compile(r"https?://\S+|\]\([^)]*\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")


class EntailmentChecker(Protocol):
    """Scores whether *evidence* supports *claim*; higher means supported."""

    model_name: str

    def score(self, evidence: str, claim: str) -> float: ...


@dataclass(frozen=True)
class EntailmentClaim:
    """One prose unit the source receipt must support."""

    text: str


class FlaggedClaim(TypedDict):
    """A prose claim whose best evidence chunk scored below the threshold."""

    claim: str
    score: float
    best_chunk_preview: str


@dataclass(frozen=True)
class EntailmentReport:
    """Outcome of entailment-scoring one insight against its receipt."""

    checked: int
    flagged: tuple[FlaggedClaim, ...]
    model: str
    threshold: float

    @property
    def supported(self) -> int:
        return self.checked - len(self.flagged)

    @property
    def ok(self) -> bool:
        return not self.flagged


def resolve_entailment_threshold(raw: str = "") -> float:
    """The flag threshold; unparseable or out-of-range values use the default."""
    value = raw or os.environ.get("DISTILL_ENTAILMENT_THRESHOLD", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_THRESHOLD
    return parsed if 0.0 < parsed < 1.0 else _DEFAULT_THRESHOLD


def extract_entailment_claims(insight_text: str) -> list[EntailmentClaim]:
    """Pull the checkable prose units out of an insight's markdown body.

    The claim unit is the bullet/line, never the paragraph (decomposition
    measurably improves evidence matching -- 59.6 vs 36.9 F1 on PolitiFact).
    Frontmatter, fenced code, headings, URLs/link targets, and short
    fragments are excluded, mirroring the numeric tier's exclusions.
    """
    body = strip_frontmatter(insight_text)
    claims: list[EntailmentClaim] = []
    in_fence = False
    for raw_line in body.splitlines():
        if _FENCE_RE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence or _HEADING_RE.match(raw_line):
            continue
        line = _URL_RE.sub(" ", raw_line)
        line = _BULLET_PREFIX_RE.sub("", line).strip().strip("*_").strip()
        if len(line) >= _MIN_CLAIM_CHARS:
            claims.append(EntailmentClaim(text=line))
    return claims


def chunk_evidence(source_text: str, *, chunk_chars: int = _CHUNK_CHARS) -> list[str]:
    """Split the receipt into checker-sized windows with 50% overlap.

    Overlap keeps a claim's evidence intact when it straddles a boundary;
    the cost is one extra pass over the text, which is nothing next to the
    scoring itself.
    """
    text = " ".join(source_text.split())
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]
    step = max(1, chunk_chars // 2)
    return [text[i : i + chunk_chars] for i in range(0, len(text) - step + 1, step)]


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _top_chunks(claim: str, chunks: list[str], *, k: int = _TOP_K_CHUNKS) -> list[str]:
    """The k chunks most lexically similar to the claim (cheap, no embeddings)."""
    claim_tokens = _tokens(claim)
    if not claim_tokens:
        return chunks[:k]
    scored = sorted(chunks, key=lambda c: -len(claim_tokens & _tokens(c)))
    return scored[:k]


def evaluate_entailment(
    insight_text: str,
    source_text: str,
    checker: EntailmentChecker,
    *,
    threshold: float | None = None,
) -> EntailmentReport:
    """Score every prose claim against its best evidence chunks. Pure.

    A claim's score is the max over its top-K lexical chunks (the checker
    answers "does ANY evidence support this", not "does the average chunk").
    Below-threshold claims are flagged with the best chunk's preview so the
    audit surface and a human can adjudicate -- a flag means "support not
    found", not "false", same contract as the deterministic tier.
    """
    limit = threshold if threshold is not None else resolve_entailment_threshold()
    claims = extract_entailment_claims(insight_text)
    chunks = chunk_evidence(source_text)
    if not claims or not chunks:
        return EntailmentReport(checked=0, flagged=(), model=checker.model_name, threshold=limit)
    flagged: list[FlaggedClaim] = []
    for claim in claims:
        candidates = _top_chunks(claim.text, chunks)
        best_score = -1.0
        best_chunk = candidates[0]
        for chunk in candidates:
            score = checker.score(chunk, claim.text)
            if score > best_score:
                best_score, best_chunk = score, chunk
        if best_score < limit:
            flagged.append(
                {
                    "claim": claim.text[:300],
                    "score": round(max(best_score, 0.0), 4),
                    "best_chunk_preview": best_chunk[:200],
                }
            )
    return EntailmentReport(
        checked=len(claims),
        flagged=tuple(flagged),
        model=checker.model_name,
        threshold=limit,
    )


# ---- the default local checker ----------------------------------------------


class HHEMChecker:
    """HHEM-2.1-Open behind a lazy import; construction fails if the extra is absent.

    The model card's contract: ``predict([(premise, hypothesis)])`` returns a
    factual-consistency probability in [0, 1]. CPU-feasible at ~110M params;
    CUDA accelerates it where available.
    """

    model_name = _HHEM_MODEL_ID
    # transformers ships no type stubs, so the model handle is Unknown by nature.
    # It is held as Any and exercised only through the narrow score() contract.
    _model: Any

    def __init__(self):
        # transformers ships no type stubs, so the imported class and the model
        # handle are Unknown; both are ignored here and held as Any (see _model).
        from transformers import (
            AutoModelForSequenceClassification,  # pyright: ignore[reportUnknownVariableType]
        )

        self._model = AutoModelForSequenceClassification.from_pretrained(  # pyright: ignore[reportUnknownMemberType]
            _HHEM_MODEL_ID, revision=_HHEM_REVISION, trust_remote_code=True
        )

    def score(self, evidence: str, claim: str) -> float:
        result: Any = self._model.predict([(evidence, claim)])
        return float(result[0])


def entailment_available() -> bool:
    """Whether the optional dependency is importable (not whether the model is cached)."""
    import importlib.util

    return importlib.util.find_spec("transformers") is not None


def load_default_checker() -> EntailmentChecker | None:
    """The HHEM checker, or ``None`` when the extra is absent or loading fails.

    Absence is silent by design: the deterministic tier stands alone exactly
    as it did before this tier existed; ``distill doctor`` is where
    availability is surfaced, not an error in the middle of an ingest run.
    """
    if not entailment_available():
        return None
    try:
        return HHEMChecker()
    except Exception as exc:
        logger.debug("entailment checker unavailable: %s", exc)
        return None
