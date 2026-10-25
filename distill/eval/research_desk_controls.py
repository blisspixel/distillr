# pyright: strict
"""Authored controls and the offline baseline receipt.

The controls are not model output. ``baseline_document`` records structural
results only. Expert review is absent and the gate stays closed.
"""

from __future__ import annotations

from distill.eval.research_desk import (
    Anchor,
    Control,
    DeskCase,
    Selection,
    Sentence,
    Synthesis,
    SynthesisStatus,
)
from distill.eval.research_desk_cases import baseline_material

_MATERIAL = baseline_material()
CASES = _MATERIAL.cases
_ACCESSED = _MATERIAL.accessed
_FAROS_SELECTION = _MATERIAL.faros_selection
_FAROS_RATIO = _MATERIAL.faros_ratio
_FAROS_NOT_PROBABILITY = _MATERIAL.faros_not_probability
_FAROS_METHOD = _MATERIAL.faros_method
_FAROS_OBSERVATIONAL = _MATERIAL.faros_observational
_FAROS_POPULATION = _MATERIAL.faros_population
_FAROS_GAP = _MATERIAL.faros_gap
_FAROS_REPORT_GAP = _MATERIAL.faros_report_gap
_FAROS_HEADLINE = _MATERIAL.faros_headline
_FAROS_MONTHLY = _MATERIAL.faros_monthly
_PROBABILITY = _MATERIAL.probability
_PROBABILITY_GAP = _MATERIAL.probability_gap
_ADULT = _MATERIAL.adult
_CHILDREN = _MATERIAL.children
_ENROLLED = _MATERIAL.enrolled
_PEDIATRIC = _MATERIAL.pediatric
_PEDIATRIC_UNKNOWN = _MATERIAL.pediatric_unknown
_SCORE_NEW = _MATERIAL.score_new
_SCORE_OLD = _MATERIAL.score_old
_SCORE_STILL = _MATERIAL.score_still
_SCORE_UNCHANGED = _MATERIAL.score_unchanged
_WEBSITE = _MATERIAL.website
_NARROWED = _MATERIAL.narrowed
_A_DISAGREE = _MATERIAL.a_disagree
_A_HISTORY = _MATERIAL.a_history
_ZERO_UNCHANGED = _MATERIAL.zero_unchanged
_B_DISAGREE = _MATERIAL.b_disagree
_A_CALIBRATED = _MATERIAL.a_calibrated
_WITHDRAWN = _MATERIAL.withdrawn
_REFUSAL = _MATERIAL.refusal


def _sentence(anchor: Anchor, text: str | None = None) -> Sentence:
    return Sentence(
        text=anchor.text if text is None else text,
        anchor_id=anchor.anchor_id,
        presents_as=anchor.role,
    )


def _answered(sentences: tuple[Sentence, ...]) -> Synthesis:
    return Synthesis(status="answered", sentences=sentences)


def _status(status: SynthesisStatus, sentences: tuple[Sentence, ...] = ()) -> Synthesis:
    return Synthesis(status=status, sentences=sentences)


def _faros_sentences(use_equivalent: bool) -> tuple[Sentence, ...]:
    required = (
        _FAROS_RATIO,
        _FAROS_NOT_PROBABILITY,
        _FAROS_METHOD,
        _FAROS_OBSERVATIONAL,
        _FAROS_POPULATION,
        _FAROS_GAP,
        _FAROS_REPORT_GAP,
    )
    if not use_equivalent:
        return tuple(_sentence(anchor) for anchor in required)
    return tuple(
        _sentence(anchor, anchor.equivalents[0] if anchor.equivalents else None)
        for anchor in required
    )


def _correction_selection(case_id: str) -> Selection:
    """Bind each episode to only its own available source events."""
    return Selection(
        selected=tuple(
            (source.source_id, source.pool_role)
            for source in CASES[case_id].sources
            if source.pool_role != "later_immaterial"
        ),
        rejected=tuple(
            (source.source_id, "homepage redesign is not condition X evidence")
            for source in CASES[case_id].sources
            if source.pool_role == "later_immaterial"
        ),
        omissions=(),
    )


_FAST_SELECTION = Selection(
    selected=(("bench-2024", "essential"), ("bench-2026", "later_material")),
    rejected=(("lab-site", "website redesign is not a score change"),),
    omissions=(),
)
_MATURE_SELECTION = Selection(
    selected=(("review-2019", "essential"),),
    rejected=(("textbook", "textbook restates the review"),),
    omissions=(("pediatric-cohort", "pediatric cohort was not captured"),),
)

CONTROLS: tuple[Control, ...] = (
    Control(
        "faros-full",
        "faros-headline-body",
        "pass",
        "positive",
        _FAROS_SELECTION,
        _answered(_faros_sentences(False)),
        "Full verbatim brief. The headline is not used as the measurement.",
    ),
    Control(
        "faros-concise",
        "faros-headline-body",
        "pass",
        "positive",
        _FAROS_SELECTION,
        _answered(_faros_sentences(True)),
        "Registered concise equivalents. Probability remains only in the corrective qualification.",
    ),
    Control(
        "faros-reordered",
        "faros-headline-body",
        "pass",
        "positive",
        _FAROS_SELECTION,
        _answered(tuple(reversed(_faros_sentences(False)))),
        "The same full sentences in reverse order.",
    ),
    Control(
        "faros-headline-as-measurement",
        "faros-headline-body",
        "fail",
        "negative",
        _FAROS_SELECTION,
        _answered((Sentence(_FAROS_HEADLINE.text, "faros-ratio", "measurement"),)),
        "Uses the heading's probability wording as the ratio measurement.",
    ),
    Control(
        "faros-claims-causation",
        "faros-headline-body",
        "fail",
        "negative",
        _FAROS_SELECTION,
        _answered(
            (
                Sentence(
                    "AI caused the incident increase.",
                    "faros-ratio",
                    "measurement",
                ),
            )
        ),
        "The causation sentence is not the ratio anchor.",
    ),
    Control(
        "faros-monthly-replaces-ratio",
        "faros-headline-body",
        "fail",
        "negative",
        _FAROS_SELECTION,
        _answered((_sentence(_FAROS_MONTHLY),)),
        "Monthly incidents are a different measurement and do not cover the ratio.",
    ),
    Control(
        "faros-derivative-as-essential",
        "faros-headline-body",
        "fail",
        "negative",
        Selection(
            selected=(("faros-takeaways", "essential"), ("faros-talk-stand-in", "essential")),
            rejected=(),
            omissions=(("faros-full-report", "full report file was not captured"),),
        ),
        _answered(_faros_sentences(False)),
        "Retrieval treats the talk stand-in as essential. Synthesis can still be faithful.",
    ),
    Control(
        "faros-body-stored-headline-used",
        "faros-headline-body",
        "fail",
        "negative",
        _FAROS_SELECTION,
        Synthesis(
            "answered",
            (Sentence(_FAROS_HEADLINE.text, "faros-headline", "measurement"),),
        ),
        "The body is in the selected source, and the brief still uses the headline as the result.",
    ),
    Control(
        "probability-as-probability",
        "synthetic-probability",
        "pass",
        "positive",
        Selection(selected=(("synthetic-trial", "essential"),), rejected=(), omissions=()),
        _answered((_sentence(_PROBABILITY), _sentence(_PROBABILITY_GAP))),
        "A source that reports probability may be briefed as probability.",
    ),
    Control(
        "probability-rewritten-as-ratio",
        "synthetic-probability",
        "fail",
        "negative",
        Selection(selected=(("synthetic-trial", "essential"),), rejected=(), omissions=()),
        _answered((Sentence(_FAROS_RATIO.text, "trial-probability", "measurement"),)),
        "Rewriting this trial into an incidents-to-PR ratio is not entailed.",
    ),
    Control(
        "mature-selection",
        "mature-adult-review",
        "pass",
        "positive",
        _MATURE_SELECTION,
        _answered(
            (
                _sentence(_ADULT),
                _sentence(_CHILDREN),
                _sentence(_ENROLLED),
                _sentence(_PEDIATRIC),
                _sentence(_PEDIATRIC_UNKNOWN),
            )
        ),
        "Essential review, redundant textbook rejected, pediatric omission recorded.",
    ),
    Control(
        "mature-textbook-as-essential",
        "mature-adult-review",
        "fail",
        "negative",
        Selection(
            selected=(("review-2019", "essential"), ("textbook", "essential")),
            rejected=(),
            omissions=(("pediatric-cohort", "pediatric cohort was not captured"),),
        ),
        _answered(
            (
                _sentence(_ADULT),
                _sentence(_CHILDREN),
                _sentence(_ENROLLED),
                _sentence(_PEDIATRIC),
                _sentence(_PEDIATRIC_UNKNOWN),
            )
        ),
        "A derivative restatement is not an essential source.",
    ),
    Control(
        "fast-material-change",
        "fast-score-change",
        "pass",
        "positive",
        _FAST_SELECTION,
        _answered((_sentence(_SCORE_NEW), _sentence(_SCORE_OLD))),
        "The new score is current and the old score stays visible.",
    ),
    Control(
        "fast-website-as-change",
        "fast-score-change",
        "fail",
        "negative",
        _FAST_SELECTION,
        _answered((Sentence(_WEBSITE.text, "lab-website", "measurement"),)),
        "The website batch does not become the score change.",
    ),
    Control(
        "fast-no-meaningful-change",
        "fast-website-batch",
        "pass",
        "positive",
        Selection(
            selected=(("bench-2024-only", "essential"),),
            rejected=(("lab-site-only", "website redesign is not a score change"),),
            omissions=(),
        ),
        _answered((_sentence(_SCORE_STILL), _sentence(_SCORE_UNCHANGED))),
        "The score stays 70. The website is rejected rather than synthesized as a change.",
    ),
    Control(
        "correction-narrowing",
        "correction-narrowing",
        "pass",
        "positive",
        _correction_selection("correction-narrowing"),
        _answered(
            (
                _sentence(_NARROWED),
                _sentence(_A_HISTORY),
                _sentence(_B_DISAGREE),
                _sentence(_A_CALIBRATED),
            )
        ),
        "The narrowed result, both sides, and the unaffected calibration stay visible.",
    ),
    Control(
        "correction-drops-disagreement",
        "correction-narrowing",
        "fail",
        "negative",
        _correction_selection("correction-narrowing"),
        _answered((_sentence(_NARROWED), _sentence(_A_CALIBRATED))),
        "Method B disappears, so the unresolved conflict is gone.",
    ),
    Control(
        "correction-withdrawal",
        "correction-withdrawal",
        "pass",
        "positive",
        _correction_selection("correction-withdrawal"),
        _answered(
            (
                _sentence(_WITHDRAWN),
                _sentence(_B_DISAGREE),
                _sentence(_A_CALIBRATED),
                _sentence(_A_HISTORY),
            )
        ),
        "Withdrawal stays visible and is not a current measurement. Method B remains.",
    ),
    Control(
        "correction-uses-withdrawn-as-current",
        "correction-withdrawal",
        "fail",
        "negative",
        _correction_selection("correction-withdrawal"),
        _answered((Sentence(_WITHDRAWN.text, "method-a-withdrawn", "measurement"),)),
        "A withdrawn result presented as the current measurement fails.",
    ),
    Control(
        "correction-zero-claim",
        "correction-zero-claim",
        "pass",
        "positive",
        _correction_selection("correction-zero-claim"),
        _status(
            "zero_claim",
            (
                _sentence(_A_CALIBRATED),
                _sentence(_A_DISAGREE),
                _sentence(_B_DISAGREE),
                _sentence(_ZERO_UNCHANGED),
            ),
        ),
        "Zero claims. The unaffected calibration and the earlier result stay visible.",
    ),
    Control(
        "correction-zero-claim-drops-unaffected",
        "correction-zero-claim",
        "fail",
        "negative",
        _correction_selection("correction-zero-claim"),
        _status("zero_claim", (_sentence(_A_DISAGREE),)),
        "Zero-claim extraction must not retire the unaffected conclusion.",
    ),
    Control(
        "correction-refused",
        "correction-refused",
        "pass",
        "positive",
        _correction_selection("correction-refused"),
        _status(
            "refused",
            (
                _sentence(_REFUSAL),
                _sentence(_A_DISAGREE),
                _sentence(_B_DISAGREE),
                _sentence(_A_CALIBRATED),
            ),
        ),
        "Refusal stays a refusal and keeps the earlier result visible.",
    ),
    Control(
        "correction-refusal-masquerades",
        "correction-refused",
        "fail",
        "negative",
        _correction_selection("correction-refused"),
        Synthesis("answered", (_sentence(_NARROWED),)),
        "A refused verification must not appear as a successful correction.",
    ),
    Control(
        "correction-immaterial-batch",
        "correction-homepage",
        "pass",
        "positive",
        _correction_selection("correction-homepage"),
        _answered((_sentence(_A_DISAGREE), _sentence(_B_DISAGREE), _sentence(_A_CALIBRATED))),
        "The homepage is rejected and the disagreement is unchanged.",
    ),
)


def _control_row(case: DeskCase, control: Control) -> dict[str, object]:
    from distill.eval.research_desk import assess

    assessment = assess(case, control.selection, control.synthesis)
    return {
        "control_id": control.control_id,
        "case_id": control.case_id,
        "kind": control.kind,
        "expect": control.expect,
        "structural": assessment.structural,
        "retrieval": assessment.retrieval_status,
        "synthesis": assessment.synthesis_status,
        "matches_expectation": assessment.structural == control.expect,
        "note": control.note,
        "criteria": [
            {
                "criterion": row.criterion,
                "track": row.track,
                "status": row.status,
                "detail": row.detail,
            }
            for row in (*assessment.retrieval, *assessment.synthesis, *assessment.semantic)
        ],
    }


def _case_index(case: DeskCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "field": case.field,
        "variant": case.variant,
        "question": case.question,
        "limits": case.limits,
        "sources": [
            {
                "source_id": source.source_id,
                "title": source.title,
                "locator": source.locator,
                "accessed": source.accessed,
                "pool_role": source.pool_role,
                "origin": source.origin,
                "active": source.active,
                "note": source.note,
                "anchors": [
                    {
                        "anchor_id": anchor.anchor_id,
                        "role": anchor.role,
                        "metric_kind": anchor.metric_kind,
                        "denominator": anchor.denominator,
                        "relative_change": anchor.relative_change,
                        "population": anchor.population,
                        "comparison": anchor.comparison,
                        "causal": anchor.causal,
                        "authored": anchor.authored,
                        "text": anchor.text,
                    }
                    for anchor in source.anchors
                ],
            }
            for source in case.sources
        ],
    }


def baseline_document() -> dict[str, object]:
    """Offline baseline receipt. Expert review is absent and the gate is closed."""
    rows = [_control_row(CASES[control.case_id], control) for control in CONTROLS]
    return {
        "schema": "research-desk-baseline.v1",
        "date": _ACCESSED,
        "expert_review": "not_performed",
        "judge_model": None,
        "live_model_trial": False,
        "cost_usd": 0,
        "cloud_calls": 0,
        "defaults_changed": False,
        "gate_passed": False,
        "gate_reason": (
            "Structural controls are recorded. Expert review and judge "
            "calibration were not performed. Discovery and synthesis defaults "
            "are unchanged. This receipt does not ship 0.20.9."
        ),
        "controls_match_expectations": all(row["matches_expectation"] is True for row in rows),
        "limitations": [
            {
                "id": "expert-review",
                "disposition": "unreviewed",
                "owner": "0.20.9",
                "detail": (
                    "No human expert reviewed these fixtures. No model judge ran. "
                    "The roadmap row stays queued."
                ),
            },
            {
                "id": "selective-revision",
                "disposition": "planned_capability",
                "owner": "post-1.0 research desk",
                "detail": (
                    "The correction controls score authored briefs. They do not "
                    "run production refresh, and they do not show that an existing "
                    "corpus revises only affected conclusions."
                ),
            },
        ],
        "cases": [_case_index(case) for case in CASES.values()],
        "controls": rows,
    }
