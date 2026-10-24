# pyright: strict
"""Offline identity for a bounded research-recipe contrast.

The comparison reuses Distill's eval cache and atomic JSON writes. It does
not add a second harness, call a model, or change a default prompt. A recipe
digest in the analysis cache key stops two prompt variants from sharing one
cached completion. Missing judgments stay inconclusive. Same-task wiring is
not evidence that a variant answers better.

Harness² commit 1cfe254e8d25b15f37048c3730134686abe60335 is a reference for
separating a method from its executor and for binding a completed run to a
fingerprint. This module does not import it, copy finals-only selection, or
open a network.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

AttemptState = Literal["planned", "completed", "failed", "cancelled", "rejected", "abstained"]
Decision = Literal["keep-baseline", "reject-all", "inconclusive"]
UNKNOWN = "unknown"

BASELINE_RECIPE_ID = "current-baseline"
_ATTEMPT_STATES: tuple[AttemptState, ...] = (
    "planned",
    "completed",
    "failed",
    "cancelled",
    "rejected",
    "abstained",
)


@dataclass(frozen=True, slots=True)
class ResearchRecipe:
    """One named prompt-section variant. Source bytes stay outside this object.

    The object has no grader, threshold, or acceptance field. A candidate
    cannot edit how it is scored.
    """

    recipe_id: str
    components: tuple[str, ...]
    section_text: str

    def digest(self) -> str:
        return _digest(
            "recipe-v1",
            self.recipe_id,
            "\n".join(self.components),
            self.section_text,
        )


BASELINE_RECIPE = ResearchRecipe(
    recipe_id=BASELINE_RECIPE_ID,
    components=(),
    section_text="",
)
SEPARATION_RECIPE = ResearchRecipe(
    recipe_id="source-interpretation-qualification",
    components=("source", "interpretation", "qualification"),
    section_text=(
        "Keep each source sentence separate from the interpretation, and "
        "preserve qualifications of population, time, method, and uncertainty."
    ),
)
CORRECTION_RECIPE = ResearchRecipe(
    recipe_id="version-correction-check",
    components=("version", "correction"),
    section_text=(
        "When two notes disagree, prefer the later correction and keep the "
        "earlier claim visible as withdrawn."
    ),
)
COMPOSITION_RECIPE = ResearchRecipe(
    recipe_id="explicit-composition",
    components=(
        "source",
        "interpretation",
        "qualification",
        "version",
        "correction",
    ),
    section_text=(
        "Apply source, interpretation, and qualification separation together "
        "with the version and correction check. Do not drop either section."
    ),
)
RECIPE_VARIANTS: tuple[ResearchRecipe, ...] = (
    BASELINE_RECIPE,
    SEPARATION_RECIPE,
    CORRECTION_RECIPE,
    COMPOSITION_RECIPE,
)


def recipe_digest(recipe: ResearchRecipe | None) -> str:
    """Return the cache identity for a recipe, or the unchanged baseline."""

    return BASELINE_RECIPE.digest() if recipe is None else recipe.digest()


def runner_identity(runner: object) -> str:
    """Bind the injected analyzer so a different callable cannot reuse a cache row."""

    module = getattr(runner, "__module__", "")
    qualname = getattr(runner, "__qualname__", type(runner).__name__)
    code = getattr(runner, "__code__", None)
    code_hex = getattr(code, "co_code", b"").hex() if code is not None else ""
    return _digest("runner-v1", str(module), str(qualname), code_hex)


@dataclass(frozen=True, slots=True)
class ContrastIdentity:
    """Hashes for one scheduled contrast. Unknown fields stay the word unknown."""

    recipe_digest: str
    prompt_section_digest: str
    rendered_production_prompt: str
    runner_digest: str
    fixture_digest: str
    source_digest: str
    runtime: str
    configuration_digest: str
    evaluator_version: str


def contrast_identity(
    *,
    recipe: ResearchRecipe,
    runner: object,
    fixture_id: str,
    source_text: str,
    runtime: str | None = None,
    configuration: str | None = None,
    evaluator_version: str | None = None,
    rendered_production_prompt: str | None = None,
) -> ContrastIdentity:
    """Bind the bytes this offline step actually has. Do not invent the rest."""

    rendered = (rendered_production_prompt or "").strip()
    config = (configuration or "").strip()
    version = (evaluator_version or "").strip()
    runtime_name = (runtime or "").strip()
    return ContrastIdentity(
        recipe_digest=recipe.digest(),
        prompt_section_digest=_digest("prompt-section-v1", recipe.section_text),
        rendered_production_prompt=_digest("rendered-prompt-v1", rendered) if rendered else UNKNOWN,
        runner_digest=runner_identity(runner),
        fixture_digest=_digest("fixture-v1", fixture_id, source_text),
        source_digest=_digest("source-v1", source_text),
        runtime=runtime_name or UNKNOWN,
        configuration_digest=_digest("config-v1", config) if config else UNKNOWN,
        evaluator_version=version or UNKNOWN,
    )


def can_reuse(
    *,
    output: str,
    expected_digest: str,
    actual_digest: str,
    required_artifacts: frozenset[str],
    present_artifacts: frozenset[str],
    stage: str = "completed",
) -> bool:
    """True only for a finished output whose manifest matches the scheduled recipe."""

    if stage != "completed":
        return False
    if not output.strip():
        return False
    if not expected_digest or expected_digest != actual_digest:
        return False
    return required_artifacts <= present_artifacts


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    state: AttemptState
    recipe_digest: str
    detail: str = ""


@dataclass
class AttemptLedger:
    """Every scheduled attempt, including retries, cache hits, and abstentions."""

    rows: list[AttemptRecord]

    def __init__(self) -> None:
        self.rows = []

    def add(self, state: AttemptState, recipe_digest: str, *, detail: str = "") -> None:
        self.rows.append(AttemptRecord(state=state, recipe_digest=recipe_digest, detail=detail))

    def counts(self) -> dict[str, int]:
        found: dict[str, int] = dict.fromkeys(_ATTEMPT_STATES, 0)
        for row in self.rows:
            found[row.state] += 1
        return found


def decide(
    *,
    baseline_available: bool,
    missing_judgments: int,
    candidate_rejected: bool,
    baseline_rejected: bool = False,
) -> Decision:
    """Offline decision. Missing judgments cannot become a pass.

    No result adopts a candidate. That would claim a quality win this
    deterministic check cannot make. Answer-level abstention is an attempt
    state, not this decision.
    """

    if missing_judgments > 0:
        return "inconclusive"
    if baseline_rejected and candidate_rejected:
        return "reject-all"
    if candidate_rejected and baseline_available:
        return "keep-baseline"
    return "inconclusive"


def _digest(*parts: str) -> str:
    payload = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        payload.update(len(encoded).to_bytes(8, "big"))
        payload.update(encoded)
    return payload.hexdigest()
