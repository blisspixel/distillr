"""Tests for distill.eval.scoring (deterministic dimensions + composite blend)."""

from distill.eval.scoring import JUDGE_WEIGHT, extract_key_concepts, score_output

_GOOD = (
    "## Core Contribution\n- A continuous rotation over ICEWS with strong MRR.\n"
    "## Methods and Evidence\n- ChronoR baseline; GDELT gains.\n"
    "## Limits and Open Questions\n- No latency numbers.\n" + "word " * 200
)


def test_extract_key_concepts_finds_acronyms_and_caps():
    concepts = extract_key_concepts("We test ICEWS and the Semantic Speed Gate on GDELT.")
    assert "ICEWS" in concepts
    assert "GDELT" in concepts
    assert "Semantic Speed Gate" in concepts


def test_score_output_rewards_structure_depth_coverage_formatting():
    q = score_output(
        _GOOD,
        expected_sections=("contribution", "method", "limit"),
        golden_concepts=("ICEWS", "MRR", "ChronoR", "GDELT"),
        min_words=180,
    )
    assert {d.name for d in q.dimensions} == {
        "Structure",
        "Depth",
        "Concept coverage",
        "Formatting",
    }
    assert q.deterministic > 0.8
    # No judge supplied -> composite equals deterministic.
    assert q.judge is None
    assert q.composite == q.deterministic


def test_thin_output_scores_low():
    q = score_output(
        "nothing useful here",
        expected_sections=("contribution", "method", "limit"),
        golden_concepts=("ICEWS", "MRR"),
        min_words=180,
    )
    assert q.deterministic < 0.3


def test_judge_blends_at_capped_weight():
    base = score_output(_GOOD, expected_sections=("contribution",), golden_concepts=("ICEWS",))
    with_judge = score_output(
        _GOOD,
        expected_sections=("contribution",),
        golden_concepts=("ICEWS",),
        judge=0.0,
    )
    # A judge score of 0 pulls the composite down by exactly JUDGE_WEIGHT of the
    # deterministic score, never more (advisory, capped).
    assert with_judge.judge == 0.0
    expected = (1.0 - JUDGE_WEIGHT) * base.deterministic
    assert round(with_judge.composite, 6) == round(expected, 6)
    assert with_judge.composite < base.composite
