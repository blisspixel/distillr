# pyright: strict
"""Structural research-desk baseline checks.

Deterministic CI owns fixture identity, source roles, and exact anchor
binding. It does not score prose quality. Semantic criteria stay unreviewed
until a recorded human review and a separate model judge exist. Nothing here
calls a provider or changes a discovery or synthesis default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Track = Literal["retrieval", "synthesis", "semantic"]
Status = Literal["pass", "fail", "not_applicable", "unreviewed"]
FieldKind = Literal["mature", "fast_moving", "contested"]
PoolRole = Literal[
    "essential",
    "redundant",
    "derivative",
    "inaccessible",
    "omitted",
    "later_material",
    "later_immaterial",
    "correction",
]
AnchorRole = Literal[
    "measurement",
    "headline",
    "qualification",
    "unaffected",
    "withdrawn",
    "gap",
    "history",
    "disagreement",
    "immaterial",
]
SynthesisStatus = Literal["answered", "zero_claim", "refused"]
Expect = Literal["pass", "fail"]

_REQUIRE_SELECTED: frozenset[str] = frozenset({"essential", "correction", "later_material"})
_ROLE_OR_REJECT: frozenset[str] = frozenset({"redundant", "derivative", "later_immaterial"})
_MUST_OMIT: frozenset[str] = frozenset({"omitted", "inaccessible"})
_NO_MEASUREMENT_VARIANTS: frozenset[str] = frozenset({"invalid_extraction", "zero_claim"})
_POOL_ORDER: tuple[str, ...] = (
    "essential",
    "correction",
    "later_material",
    "redundant",
    "derivative",
    "later_immaterial",
    "omitted",
    "inaccessible",
)
_EXPECTED_STATUS: dict[str, SynthesisStatus] = {
    "invalid_extraction": "refused",
    "zero_claim": "zero_claim",
}
_SEMANTIC: tuple[tuple[str, str], ...] = (
    (
        "faithful_qualification_prose",
        "No model judge ran, so prose faithfulness is unreviewed.",
    ),
    (
        "fair_disagreement_explanation",
        "No model judge ran, so disagreement fairness is unreviewed.",
    ),
    (
        "useful_change_explanation",
        "No model judge ran, so the change explanation is unreviewed.",
    ),
    (
        "judge_calibration",
        "No recorded human review exists, so judge calibration is unreviewed.",
    ),
)


@dataclass(frozen=True, slots=True)
class Anchor:
    """One frozen claim a brief may present, and only as its own role."""

    anchor_id: str
    role: AnchorRole
    metric_kind: str
    denominator: str
    relative_change: str
    population: str
    comparison: str
    causal: str
    text: str
    equivalents: tuple[str, ...] = ()
    authored: bool = False


@dataclass(frozen=True, slots=True)
class Source:
    """A candidate in the pool. Retrieval and synthesis read different fields."""

    source_id: str
    title: str
    locator: str
    accessed: str
    pool_role: PoolRole
    origin: str
    active: bool
    anchors: tuple[Anchor, ...]
    note: str


@dataclass(frozen=True, slots=True)
class DeskCase:
    """One frozen episode. Required ids are coverage, not a quality score."""

    case_id: str
    field: FieldKind
    variant: str
    question: str
    sources: tuple[Source, ...]
    measurement_ids: tuple[str, ...]
    qualification_ids: tuple[str, ...]
    disagreement_ids: tuple[str, ...]
    gap_ids: tuple[str, ...]
    history_ids: tuple[str, ...]
    unaffected_ids: tuple[str, ...]
    withdrawn_ids: tuple[str, ...]
    limits: str


@dataclass(frozen=True, slots=True)
class Selection:
    """Retrieval output: chosen role, rejection reason, or omission reason."""

    selected: tuple[tuple[str, str], ...]
    rejected: tuple[tuple[str, str], ...]
    omissions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Sentence:
    """One reader-facing sentence bound to exactly one frozen anchor."""

    text: str
    anchor_id: str
    presents_as: AnchorRole


@dataclass(frozen=True, slots=True)
class Synthesis:
    """The brief under test. Prose is the sentence text, not a keyword bag."""

    status: SynthesisStatus
    sentences: tuple[Sentence, ...]

    @property
    def prose(self) -> str:
        return "\n".join(sentence.text for sentence in self.sentences)


@dataclass(frozen=True, slots=True)
class Control:
    """An authored candidate and the structural result it must produce."""

    control_id: str
    case_id: str
    expect: Expect
    kind: Literal["positive", "negative"]
    selection: Selection
    synthesis: Synthesis
    note: str


@dataclass(frozen=True, slots=True)
class CriterionResult:
    criterion: str
    track: Track
    status: Status
    detail: str


@dataclass(frozen=True, slots=True)
class Assessment:
    retrieval: tuple[CriterionResult, ...]
    synthesis: tuple[CriterionResult, ...]
    semantic: tuple[CriterionResult, ...]

    def track_status(self, rows: tuple[CriterionResult, ...]) -> Literal["pass", "fail"]:
        if any(row.status == "fail" for row in rows):
            return "fail"
        return "pass"

    @property
    def retrieval_status(self) -> Literal["pass", "fail"]:
        return self.track_status(self.retrieval)

    @property
    def synthesis_status(self) -> Literal["pass", "fail"]:
        return self.track_status(self.synthesis)

    @property
    def structural(self) -> Literal["pass", "fail"]:
        return self.track_status((*self.retrieval, *self.synthesis))


def _result(
    criterion: str,
    track: Track,
    problems: tuple[str, ...],
    *,
    applicable: bool,
    empty_detail: str,
) -> CriterionResult:
    if not applicable:
        return CriterionResult(criterion, track, "not_applicable", empty_detail)
    if problems:
        return CriterionResult(criterion, track, "fail", "; ".join(problems))
    return CriterionResult(criterion, track, "pass", empty_detail)


def _anchors(case: DeskCase) -> dict[str, Anchor]:
    return {anchor.anchor_id: anchor for source in case.sources for anchor in source.anchors}


def _known_ids(case: DeskCase) -> set[str]:
    return {source.source_id for source in case.sources}


def _role_of(selection: Selection, source_id: str) -> str | None:
    found = [role for sid, role in selection.selected if sid == source_id]
    if not found:
        return None
    return found[0]


def _reason_present(pairs: tuple[tuple[str, str], ...], source_id: str) -> bool:
    return any(sid == source_id and reason.strip() for sid, reason in pairs)


def _mentioned(selection: Selection) -> tuple[str, ...]:
    return tuple(
        sid for sid, _reason in (*selection.selected, *selection.rejected, *selection.omissions)
    )


def _identity_problems(case: DeskCase, selection: Selection) -> tuple[str, ...]:
    known = _known_ids(case)
    unknown = [sid for sid in _mentioned(selection) if sid not in known]
    duplicate = [sid for sid, _role in selection.selected if _selected_count(selection, sid) > 1]
    problems = [f"unknown source {sid}" for sid in unknown]
    problems.extend(f"duplicate selection {sid}" for sid in sorted(set(duplicate)))
    return tuple(problems)


def _selected_count(selection: Selection, source_id: str) -> int:
    return sum(1 for sid, _role in selection.selected if sid == source_id)


def _pool_problems(case: DeskCase, selection: Selection, pool_role: str) -> tuple[str, ...]:
    problems: list[str] = []
    for source in case.sources:
        if source.pool_role != pool_role:
            continue
        chosen = _role_of(selection, source.source_id)
        problems.extend(_one_source(selection, source.source_id, pool_role, chosen))
    return tuple(problems)


def _one_source(
    selection: Selection,
    source_id: str,
    pool_role: str,
    chosen: str | None,
) -> tuple[str, ...]:
    if pool_role in _MUST_OMIT:
        return _omit_problems(selection, source_id, chosen)
    if pool_role in _REQUIRE_SELECTED:
        if chosen == pool_role:
            return ()
        return (f"{source_id} was not selected as {pool_role}",)
    if chosen is None and _reason_present(selection.rejected, source_id):
        return ()
    if chosen == pool_role:
        return ()
    if chosen is None:
        return (f"{source_id} was neither selected as {pool_role} nor rejected",)
    return (f"{source_id} was selected as {chosen}",)


def _omit_problems(selection: Selection, source_id: str, chosen: str | None) -> tuple[str, ...]:
    problems: list[str] = []
    if chosen is not None:
        problems.append(f"{source_id} was selected")
    if not _reason_present(selection.omissions, source_id):
        problems.append(f"{source_id} has no omission reason")
    return tuple(problems)


def _check_retrieval(case: DeskCase, selection: Selection) -> tuple[CriterionResult, ...]:
    rows: list[CriterionResult] = [
        _result(
            "source_identity",
            "retrieval",
            _identity_problems(case, selection),
            applicable=True,
            empty_detail="Every cited source id exists once.",
        )
    ]
    roles = tuple(dict.fromkeys(source.pool_role for source in case.sources))
    for pool_role in _POOL_ORDER:
        present = pool_role in roles
        rows.append(
            _result(
                f"pool_{pool_role}",
                "retrieval",
                _pool_problems(case, selection, pool_role),
                applicable=present,
                empty_detail=f"Sources with pool role {pool_role} follow that role.",
            )
        )
    return tuple(rows)


def _text_matches(anchor: Anchor, text: str) -> bool:
    return text == anchor.text or text in anchor.equivalents


def _binding_problems(synthesis: Synthesis, anchors: dict[str, Anchor]) -> tuple[str, ...]:
    problems: list[str] = []
    for sentence in synthesis.sentences:
        anchor = anchors.get(sentence.anchor_id)
        if anchor is None:
            problems.append(f"unknown anchor {sentence.anchor_id}")
            continue
        if sentence.presents_as != anchor.role:
            problems.append(f"{sentence.anchor_id} presented as {sentence.presents_as}")
            continue
        if not _text_matches(anchor, sentence.text):
            problems.append(f"{sentence.anchor_id} text is not bound to that anchor")
    return tuple(problems)


def _covered(synthesis: Synthesis, anchors: dict[str, Anchor], anchor_id: str) -> bool:
    anchor = anchors.get(anchor_id)
    if anchor is None:
        return False
    return any(
        sentence.anchor_id == anchor_id
        and sentence.presents_as == anchor.role
        and _text_matches(anchor, sentence.text)
        for sentence in synthesis.sentences
    )


def _missing(
    synthesis: Synthesis, anchors: dict[str, Anchor], ids: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(anchor_id for anchor_id in ids if not _covered(synthesis, anchors, anchor_id))


def _has_measurement(synthesis: Synthesis, anchors: dict[str, Anchor]) -> bool:
    return any(
        (anchor := anchors.get(sentence.anchor_id)) is not None and anchor.role == "measurement"
        for sentence in synthesis.sentences
        if sentence.presents_as == "measurement"
    )


def _status_problems(
    case: DeskCase, synthesis: Synthesis, anchors: dict[str, Anchor]
) -> tuple[str, ...]:
    expected = _EXPECTED_STATUS.get(case.variant, "answered")
    problems: list[str] = []
    if synthesis.status != expected:
        problems.append(f"status is {synthesis.status}, expected {expected}")
    if case.variant in _NO_MEASUREMENT_VARIANTS and _has_measurement(synthesis, anchors):
        problems.append("a measurement sentence is present")
    return tuple(problems)


def _coverage_row(
    criterion: str,
    synthesis: Synthesis,
    anchors: dict[str, Anchor],
    ids: tuple[str, ...],
) -> CriterionResult:
    missing = _missing(synthesis, anchors, ids)
    unknown = tuple(anchor_id for anchor_id in ids if anchor_id not in anchors)
    problems = tuple(f"missing {anchor_id}" for anchor_id in missing) + tuple(
        f"unknown required anchor {anchor_id}" for anchor_id in unknown
    )
    return _result(
        criterion,
        "synthesis",
        problems,
        applicable=bool(ids),
        empty_detail=f"Required {criterion} anchors are presented as themselves.",
    )


def _check_synthesis(case: DeskCase, synthesis: Synthesis) -> tuple[CriterionResult, ...]:
    anchors = _anchors(case)
    rows = [
        _result(
            "anchor_binding",
            "synthesis",
            _binding_problems(synthesis, anchors),
            applicable=True,
            empty_detail="Each sentence matches its anchor text and role.",
        ),
        _result(
            "extraction_status",
            "synthesis",
            _status_problems(case, synthesis, anchors),
            applicable=True,
            empty_detail="Extraction status matches the variant.",
        ),
        _coverage_row("measurement", synthesis, anchors, case.measurement_ids),
        _coverage_row("qualification", synthesis, anchors, case.qualification_ids),
        _coverage_row("disagreement", synthesis, anchors, case.disagreement_ids),
        _coverage_row("unavailable_evidence", synthesis, anchors, case.gap_ids),
        _coverage_row("history", synthesis, anchors, case.history_ids),
        _coverage_row("unaffected", synthesis, anchors, case.unaffected_ids),
        _coverage_row("withdrawal", synthesis, anchors, case.withdrawn_ids),
    ]
    return tuple(rows)


def _semantic() -> tuple[CriterionResult, ...]:
    return tuple(
        CriterionResult(criterion, "semantic", "unreviewed", detail)
        for criterion, detail in _SEMANTIC
    )


def assess(case: DeskCase, selection: Selection, synthesis: Synthesis) -> Assessment:
    """Score retrieval and synthesis separately. Semantic rows stay unreviewed."""
    return Assessment(
        retrieval=_check_retrieval(case, selection),
        synthesis=_check_synthesis(case, synthesis),
        semantic=_semantic(),
    )
