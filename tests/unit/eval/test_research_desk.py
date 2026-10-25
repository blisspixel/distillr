"""Structural research-desk baseline. No model and no network."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from distill.eval.research_desk import (
    Anchor,
    DeskCase,
    Selection,
    Sentence,
    Source,
    Synthesis,
    assess,
)
from distill.eval.research_desk_cases import CASES
from distill.eval.research_desk_controls import CONTROLS, baseline_document

_RECEIPT = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "research"
    / "evidence"
    / "2026-10-24"
    / "research-desk-baseline.json"
)


def _control(control_id: str):
    return next(control for control in CONTROLS if control.control_id == control_id)


def _assessment(control_id: str):
    control = _control(control_id)
    return assess(CASES[control.case_id], control.selection, control.synthesis)


def test_controls_match_their_structural_expectations():
    document = baseline_document()
    assert document["controls_match_expectations"] is True
    assert document["gate_passed"] is False
    assert document["expert_review"] == "not_performed"
    assert document["live_model_trial"] is False
    assert document["defaults_changed"] is False
    assert document["judge_model"] is None
    assert document["cost_usd"] == 0


def test_semantic_rows_stay_unreviewed():
    rows = _assessment("faros-full").semantic
    assert rows
    assert {row.status for row in rows} == {"unreviewed"}


def test_faros_full_brief_may_say_probability_and_still_pass():
    control = _control("faros-full")
    assessment = _assessment("faros-full")
    assert "probability" in control.synthesis.prose
    assert assessment.structural == "pass"
    assert assessment.retrieval_status == "pass"
    assert assessment.synthesis_status == "pass"


def test_faros_concise_and_reordered_briefs_pass():
    assert _assessment("faros-concise").structural == "pass"
    assert _assessment("faros-reordered").structural == "pass"
    full = _control("faros-full").synthesis.prose.splitlines()
    reordered = _control("faros-reordered").synthesis.prose.splitlines()
    assert reordered == list(reversed(full))


def test_headline_wording_is_not_the_ratio_measurement():
    assessment = _assessment("faros-headline-as-measurement")
    assert assessment.structural == "fail"
    assert assessment.synthesis_status == "fail"
    binding = next(row for row in assessment.synthesis if row.criterion == "anchor_binding")
    assert binding.status == "fail"


def test_body_can_be_selected_while_the_brief_still_uses_the_headline():
    assessment = _assessment("faros-body-stored-headline-used")
    assert assessment.retrieval_status == "pass"
    assert assessment.synthesis_status == "fail"


def test_talk_stand_in_is_not_essential_evidence():
    assessment = _assessment("faros-derivative-as-essential")
    assert assessment.retrieval_status == "fail"
    assert assessment.synthesis_status == "pass"


def test_probability_source_keeps_probability_and_rejects_a_ratio_rewrite():
    kept = _assessment("probability-as-probability")
    rewritten = _assessment("probability-rewritten-as-ratio")
    assert "probability" in _control("probability-as-probability").synthesis.prose
    assert kept.structural == "pass"
    assert rewritten.structural == "fail"


def test_faros_ratio_anchor_is_a_quotation_with_the_reported_change():
    case = CASES["faros-headline-body"]
    anchors = {anchor.anchor_id: anchor for source in case.sources for anchor in source.anchors}
    ratio = anchors["faros-ratio"]
    headline = anchors["faros-headline"]
    observational = anchors["faros-observational"]
    assert ratio.authored is False
    assert ratio.metric_kind == "incidents_to_pr_ratio"
    assert ratio.denominator == "PR"
    assert ratio.relative_change == "up 242.7%"
    assert "242.7%" in ratio.text
    assert "incidents-to-PR ratio" in ratio.text
    assert ratio.causal == "not_claimed"
    assert headline.role == "headline"
    assert headline.metric_kind == "incident_probability"
    assert observational.authored is True
    assert "not a randomized causal effect" in observational.text
    assert case.sources[0].locator == "https://www.faros.ai/blog/ai-acceleration-whiplash-takeaways"


def test_correction_variants_keep_history_and_do_not_promote_failures():
    assert _assessment("correction-narrowing").structural == "pass"
    assert _assessment("correction-drops-disagreement").synthesis_status == "fail"
    assert _assessment("correction-withdrawal").structural == "pass"
    assert _assessment("correction-uses-withdrawn-as-current").synthesis_status == "fail"
    assert _assessment("correction-zero-claim").structural == "pass"
    assert _assessment("correction-zero-claim-drops-unaffected").synthesis_status == "fail"
    refused = _assessment("correction-refused")
    masquerade = _assessment("correction-refusal-masquerades")
    assert refused.structural == "pass"
    assert masquerade.structural == "fail"
    assert _assessment("correction-immaterial-batch").structural == "pass"
    assert _assessment("fast-material-change").structural == "pass"
    assert _assessment("fast-no-meaningful-change").structural == "pass"
    assert _assessment("fast-website-as-change").synthesis_status == "fail"
    assert _assessment("mature-selection").structural == "pass"
    assert _assessment("mature-textbook-as-essential").retrieval_status == "fail"


def test_baseline_names_the_unreviewed_and_planned_limits():
    limitations = baseline_document()["limitations"]
    assert isinstance(limitations, list)
    ids = {item["id"] for item in limitations if isinstance(item, dict)}
    assert ids == {"expert-review", "selective-revision"}


def test_published_receipt_matches_the_baseline_document():
    loaded = json.loads(_RECEIPT.read_text(encoding="utf-8"))
    assert loaded == baseline_document()


def test_role_and_anchor_failures_name_the_broken_binding():
    anchor = Anchor(
        "measured",
        "measurement",
        "count",
        "n",
        "up",
        "adults",
        "periods",
        "not_claimed",
        "The count rose.",
    )
    case = DeskCase(
        "tiny-roles",
        "mature",
        "baseline",
        "What was measured?",
        (
            Source(
                "paper", "Paper", "loc", "2026-10-24", "essential", "primary", True, (anchor,), ""
            ),
            Source("copy", "Copy", "loc", "2026-10-24", "redundant", "copy", True, (), ""),
            Source("gap", "Gap", "loc", "2026-10-24", "omitted", "unknown", False, (), ""),
        ),
        ("missing-measurement",),
        (),
        (),
        (),
        (),
        (),
        (),
        "Synthetic role check.",
    )
    missed = assess(case, Selection((), (), ()), Synthesis("answered", ()))
    assert any("was not selected as essential" in row.detail for row in missed.retrieval)
    assert any("neither selected" in row.detail for row in missed.retrieval)
    assert any("no omission reason" in row.detail for row in missed.retrieval)

    kept = assess(
        case,
        Selection(
            (("paper", "essential"), ("copy", "redundant")), (), (("gap", "outside the pool"),)
        ),
        Synthesis("answered", (Sentence("The count rose.", "measured", "measurement"),)),
    )
    assert all(row.status != "fail" for row in kept.retrieval)
    assert any("missing missing-measurement" in row.detail for row in kept.synthesis)

    selected_gap = assess(
        case,
        Selection(
            (("paper", "essential"), ("copy", "redundant"), ("gap", "omitted")),
            (),
            (("gap", "outside the pool"),),
        ),
        Synthesis(
            "answered",
            (Sentence("not frozen", "unknown-anchor", "measurement"),),
        ),
    )
    assert any("gap was selected" in row.detail for row in selected_gap.retrieval)
    assert any("unknown anchor unknown-anchor" in row.detail for row in selected_gap.synthesis)


def test_pool_criteria_keep_a_stable_order():
    names = [row.criterion for row in _assessment("faros-full").retrieval]
    assert names == [
        "source_identity",
        "pool_essential",
        "pool_correction",
        "pool_later_material",
        "pool_redundant",
        "pool_derivative",
        "pool_later_immaterial",
        "pool_omitted",
        "pool_inaccessible",
    ]


@pytest.mark.parametrize(
    ("control_id", "anchor_id"),
    [
        ("faros-full", "faros-report-not-captured"),
        ("faros-concise", "faros-report-not-captured"),
        ("mature-selection", "pediatric-applicability-unknown"),
        ("fast-no-meaningful-change", "website-no-score-change"),
        ("correction-narrowing", "method-a-10-history"),
        ("correction-withdrawal", "method-a-10-history"),
        ("correction-zero-claim", "method-b-16"),
        ("correction-zero-claim", "zero-claim-unchanged"),
        ("correction-refused", "method-b-16"),
        ("correction-refused", "method-a-calibrated"),
    ],
)
def test_positive_briefs_cannot_drop_reviewed_material_context(control_id, anchor_id):
    control = _control(control_id)
    omitted = replace(
        control.synthesis,
        sentences=tuple(s for s in control.synthesis.sentences if s.anchor_id != anchor_id),
    )
    result = assess(CASES[control.case_id], control.selection, omitted)
    assert result.synthesis_status == "fail"
    assert any(f"missing {anchor_id}" in row.detail for row in result.synthesis)


@pytest.mark.parametrize("control_id", ["correction-narrowing", "correction-withdrawal"])
def test_history_cannot_be_presented_as_current_support(control_id):
    control = _control(control_id)
    historical = next(s for s in control.synthesis.sentences if s.presents_as == "history")
    assert "earlier" in historical.text and "not current support" in historical.text
    for bad_sentence in (
        replace(historical, presents_as="measurement"),
        replace(historical, text="Method A reports 10 under condition X."),
    ):
        changed = replace(
            control.synthesis,
            sentences=tuple(
                bad_sentence if s.anchor_id == historical.anchor_id else s
                for s in control.synthesis.sentences
            ),
        )
        result = assess(CASES[control.case_id], control.selection, changed)
        assert result.synthesis_status == "fail"
        assert any(
            row.criterion == "anchor_binding" and row.status == "fail" for row in result.synthesis
        )


@pytest.mark.parametrize(
    ("case_id", "event_id"),
    [
        ("correction-narrowing", "note-2026"),
        ("correction-withdrawal", "withdrawal-2026"),
        ("correction-zero-claim", "zero-extraction"),
        ("correction-refused", "verifier"),
        ("correction-homepage", "journal-site"),
    ],
)
def test_correction_episode_pools_exclude_other_events(case_id, event_id):
    case = CASES[case_id]
    assert {source.source_id for source in case.sources} == {"method-a", "method-b", event_id}
    control = next(c for c in CONTROLS if c.case_id == case_id and c.kind == "positive")
    events = {"note-2026", "withdrawal-2026", "zero-extraction", "verifier", "journal-site"}
    for unavailable in events - {event_id}:
        leaked = replace(
            control.selection,
            selected=(*control.selection.selected, (unavailable, "essential")),
        )
        result = assess(case, leaked, control.synthesis)
        assert result.retrieval_status == "fail"
        assert any(f"unknown source {unavailable}" in row.detail for row in result.retrieval)


def test_refusal_and_zero_claim_keep_prior_current_findings():
    for control_id in ("correction-refused", "correction-zero-claim"):
        control = _control(control_id)
        ids = {sentence.anchor_id for sentence in control.synthesis.sentences}
        assert {"method-a-10", "method-b-16", "method-a-calibrated"} <= ids
        assert "method-a-10-history" not in ids
        assert not any(
            sentence.presents_as == "measurement" for sentence in control.synthesis.sentences
        )
