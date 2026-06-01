"""Tests for distill.eval.scoring (deterministic dimensions, verbosity-resistant)."""

from distill.eval.scoring import extract_key_concepts, score_output

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
    assert q.composite > 0.8


def test_thin_output_scores_low():
    q = score_output(
        "nothing useful here",
        expected_sections=("contribution", "method", "limit"),
        golden_concepts=("ICEWS", "MRR"),
        min_words=180,
    )
    assert q.composite < 0.3


def test_depth_is_verbosity_resistant():
    # Same content; one padded far past the sane ceiling. Padding must NOT score
    # higher on depth — a longer answer can't win on length alone.
    base = "## A\n- " + "alpha " * 200
    padded = "## A\n- " + "alpha " * 2000
    d_base = next(d for d in score_output(base, min_words=180).dimensions if d.name == "Depth")
    d_padded = next(d for d in score_output(padded, min_words=180).dimensions if d.name == "Depth")
    assert d_base.score == 1.0
    assert d_padded.score < d_base.score  # decays for padding


def test_depth_ramps_below_target():
    short = "one two three four five"  # 5 words
    d = next(dim for dim in score_output(short, min_words=100).dimensions if dim.name == "Depth")
    assert 0.0 < d.score < 0.1
