# pyright: strict
"""Recipe identity, cache separation, and the offline decision policy."""

from __future__ import annotations

from dataclasses import fields

from distill.eval.fixtures import Fixture
from distill.eval.harness import _analyze, run_model_eval
from distill.eval.recipe_contrast import (
    BASELINE_RECIPE,
    RECIPE_VARIANTS,
    SEPARATION_RECIPE,
    AttemptLedger,
    ResearchRecipe,
    can_reuse,
    contrast_identity,
    decide,
    recipe_digest,
)
from distill.pipeline.costs import CostTracker


def _fake(calls: list[str], text: str):
    def analyze(fixture: Fixture, _config: object, _tracker: object) -> str:
        calls.append(fixture.id)
        return text

    return analyze


def test_swapping_only_the_recipe_invalidates_analysis_reuse(tmp_path) -> None:
    calls: list[str] = []
    fake = _fake(calls, "baseline answer")
    ledger = AttemptLedger()
    first = 0
    for recipe in RECIPE_VARIANTS:
        digest = recipe.digest()
        ledger.add("planned", digest)
        before = len(calls)
        run_model_eval(
            "paper",
            ["grok-4.3"],
            anchor="grok-4.3",
            judge_model="",
            cache_dir=tmp_path,
            analyze=fake,
            recipe=recipe,
        )
        ran = len(calls) - before
        assert ran > 0
        if first == 0:
            first = ran
        assert ran == first
        ledger.add("completed", digest, detail="analyzed")
    assert len({recipe.digest() for recipe in RECIPE_VARIANTS}) == 4
    digest = recipe_digest(None)
    assert digest == BASELINE_RECIPE.digest()
    ledger.add("planned", digest, detail="retry")
    before = len(calls)
    cached = run_model_eval(
        "paper",
        ["grok-4.3"],
        anchor="grok-4.3",
        judge_model="",
        cache_dir=tmp_path,
        analyze=fake,
        recipe=None,
    )
    assert len(calls) == before
    assert cached
    assert all(row.cached for row in cached)
    ledger.add("completed", digest, detail="cache-hit")
    assert ledger.counts()["planned"] == 5
    assert ledger.counts()["completed"] == 5


def test_development_fixtures_bind_identity_and_do_not_splice_prompts(tmp_path) -> None:
    sources = (
        {
            "id": "qualification-extraction",
            "source": (
                "In 2024 the trial enrolled 40 adults. The result does not generalize to children."
            ),
            "question": "What population limit does the note state?",
            "required": ("40", "does not generalize"),
            "behavior": "answer",
        },
        {
            "id": "two-source-correction",
            "source": (
                "Note A says the build is safe. Note B, written later, withdraws that safety claim."
            ),
            "question": "Which safety claim is current?",
            "required": ("withdraws",),
            "behavior": "answer",
        },
        {
            "id": "unanswerable-price",
            "source": "The note lists battery sizes AA and AAA. It does not state a price.",
            "question": "What price does the note state?",
            "required": ("does not state a price",),
            "behavior": "abstain",
        },
        {
            "id": "answerable-size-control",
            "source": "The note lists battery sizes AA and AAA. It does not state a price.",
            "question": "Which battery sizes does the note list?",
            "required": ("AA", "AAA"),
            "behavior": "answer",
        },
    )
    mocked = {
        "qualification-extraction": (
            "The trial enrolled 40 adults. It does not generalize to children."
        ),
        "two-source-correction": "Note B withdraws the safety claim from Note A.",
        "unanswerable-price": "The note does not state a price.",
        "answerable-size-control": "The note lists battery sizes AA and AAA.",
    }
    calls: list[str] = []

    def analyze(fixture: Fixture, _config: object, _tracker: object) -> str:
        calls.append(fixture.id)
        assert SEPARATION_RECIPE.section_text not in fixture.source_text
        return mocked[fixture.id]

    ledger = AttemptLedger()
    tracker = CostTracker()
    for item in sources:
        fixture = Fixture(
            id=str(item["id"]),
            workload="ask",
            title=str(item["id"]),
            source_text=str(item["source"]),
            expected_sections=(),
            golden_concepts=(),
            min_words=1,
            question=str(item["question"]),
        )
        digest = SEPARATION_RECIPE.digest()
        identity = contrast_identity(
            recipe=SEPARATION_RECIPE,
            runner=analyze,
            fixture_id=fixture.id,
            source_text=fixture.source_text,
        )
        assert identity.runtime == "unknown"
        assert identity.rendered_production_prompt == "unknown"
        assert identity.configuration_digest == "unknown"
        assert identity.evaluator_version == "unknown"
        assert identity.source_digest
        ledger.add("planned", digest)
        if item["behavior"] == "abstain":
            ledger.add("abstained", digest, detail=fixture.id)
        analysis = _analyze("grok-4.3", fixture, analyze, tracker, tmp_path, digest)
        assert analysis.error == ""
        for needle in item["required"]:
            assert str(needle) in analysis.output
        ledger.add("completed", digest, detail="analyzed")
        again = _analyze("grok-4.3", fixture, analyze, tracker, tmp_path, digest)
        assert again.cached is True
        ledger.add("completed", digest, detail="cache-hit")
        other = recipe_digest(ResearchRecipe("other", ("version",), "different section"))
        missed = _analyze("grok-4.3", fixture, analyze, tracker, tmp_path, other)
        assert missed.cached is False
    assert ledger.counts()["abstained"] == 1
    assert ledger.counts()["rejected"] == 0
    assert calls.count("unanswerable-price") == 2


def test_partial_output_and_manifest_mismatch_cannot_be_reused() -> None:
    digest = recipe_digest(BASELINE_RECIPE)
    required = frozenset({"answer"})
    assert (
        can_reuse(
            output="",
            expected_digest=digest,
            actual_digest=digest,
            required_artifacts=required,
            present_artifacts=required,
        )
        is False
    )
    assert (
        can_reuse(
            output="answer text",
            expected_digest=digest,
            actual_digest="other",
            required_artifacts=required,
            present_artifacts=required,
        )
        is False
    )
    assert (
        can_reuse(
            output="answer text",
            expected_digest=digest,
            actual_digest=digest,
            required_artifacts=required,
            present_artifacts=frozenset(),
        )
        is False
    )
    assert (
        can_reuse(
            output="answer text",
            expected_digest=digest,
            actual_digest=digest,
            required_artifacts=required,
            present_artifacts=required,
            stage="interrupted",
        )
        is False
    )
    ledger = AttemptLedger()
    ledger.add("failed", digest, detail="blank-output")
    ledger.add("cancelled", digest, detail="interrupted-stage")
    ledger.add("rejected", digest, detail="candidate")
    assert ledger.counts()["failed"] == 1
    assert ledger.counts()["cancelled"] == 1
    assert ledger.counts()["abstained"] == 0


def test_missing_judgments_cannot_pass_and_reject_all_is_reachable() -> None:
    assert {field.name for field in fields(ResearchRecipe)} == {
        "recipe_id",
        "components",
        "section_text",
    }
    assert (
        decide(
            baseline_available=True,
            missing_judgments=1,
            candidate_rejected=False,
        )
        == "inconclusive"
    )
    assert (
        decide(
            baseline_available=True,
            missing_judgments=0,
            candidate_rejected=True,
        )
        == "keep-baseline"
    )
    assert (
        decide(
            baseline_available=False,
            missing_judgments=0,
            candidate_rejected=False,
        )
        == "inconclusive"
    )
    assert (
        decide(
            baseline_available=False,
            missing_judgments=0,
            candidate_rejected=True,
            baseline_rejected=True,
        )
        == "reject-all"
    )
    assert (
        decide(
            baseline_available=False,
            missing_judgments=0,
            candidate_rejected=False,
            baseline_rejected=True,
        )
        == "inconclusive"
    )


def test_harness_retry_after_failure_is_not_a_cache_hit(tmp_path) -> None:
    fixture = Fixture(
        id="qualification-extraction",
        workload="ask",
        title="qualification-extraction",
        source_text="In 2024 the trial enrolled 40 adults.",
        expected_sections=(),
        golden_concepts=(),
        min_words=1,
    )
    state = {"n": 0}

    def analyze(_fixture: Fixture, _config: object, _tracker: object) -> str:
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("interrupted")
        return "The trial enrolled 40 adults."

    digest = BASELINE_RECIPE.digest()
    ledger = AttemptLedger()
    tracker = CostTracker()
    ledger.add("planned", digest)
    failed = _analyze("grok-4.3", fixture, analyze, tracker, tmp_path, digest)
    assert failed.error
    assert failed.cached is False
    ledger.add("failed", digest, detail="retry")
    ledger.add("planned", digest, detail="retry")
    completed = _analyze("grok-4.3", fixture, analyze, tracker, tmp_path, digest)
    assert completed.error == ""
    assert completed.cached is False
    ledger.add("completed", digest, detail="analyzed")
    assert ledger.counts()["failed"] == 1
    assert ledger.counts()["completed"] == 1
