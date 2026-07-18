"""Tests for distill.pipeline.ask (grounded answering + verify-gated promotion)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from distill.config import DistillConfig
from distill.llm.router import LLM_Response
from distill.pipeline import ask as ask_mod
from distill.pipeline.costs import ProjectedBudgetExceededError, estimate_ask_workflow_cost


@pytest.fixture
def config(tmp_path):
    return DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")


class _SupportingChecker:
    model_name = "test-supporting-checker"

    def score(self, evidence: str, claim: str) -> float:
        return 1.0


@pytest.fixture(autouse=True)
def _semantic_checker(monkeypatch):
    import distill.pipeline.verify as verify_mod

    monkeypatch.setattr(verify_mod, "_checker", _SupportingChecker())
    monkeypatch.setattr(verify_mod, "_checker_loaded", True)


def _seed_corpus(config, topic: str = "t") -> None:
    d = config.topic_dir(topic) / "papers" / "checker-paper"
    d.mkdir(parents=True, exist_ok=True)
    (d / "checker_paper_Insights.md").write_text(
        '---\nsource_id: "p1"\n---\n\n## Core\n'
        "- HHEM reaches 0.878 ROC-AUC on grounding verification benchmarks.\n"
        "- The checker runs on CPU with 110 million parameters.\n",
        encoding="utf-8",
    )


def _llm(monkeypatch, text: str):
    monkeypatch.setattr(
        ask_mod,
        "llm_call",
        lambda rc, **kwargs: LLM_Response(
            text=text, input_tokens=10, output_tokens=10, model="grok-4.3"
        ),
    )


GROUNDED = (
    "HHEM reaches 0.878 ROC-AUC and runs on CPU [checker_paper_Insights].\n\n"
    "Caveats: single-source coverage."
)


class TestAsk:
    def test_oversized_model_answer_is_bounded_and_not_written(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(monkeypatch, "x" * 64_001)

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config)

        assert result.answer_path is None
        assert len(result.answer_text) == 64_000
        assert "artifact limit" in result.answer_refused_reason
        assert not (config.topic_dir("t") / "answers").exists()

    def test_answer_artifact_with_citations_and_sidecar(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(monkeypatch, GROUNDED)

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config)

        assert result.answer_path is not None and result.answer_path.exists()
        body = result.answer_path.read_text(encoding="utf-8")
        assert "[[checker_paper_Insights]]" in body
        assert 'prompt_id: "ask.v1"' in body
        assert result.sources == ["checker_paper_Insights"]
        sidecars = list(result.answer_path.parent.glob("*_Verify.json"))
        assert len(sidecars) == 1
        assert json.loads(sidecars[0].read_text(encoding="utf-8"))["unsupported"] == []

    def test_no_coverage_topic(self, config):
        result = ask_mod.ask_corpus("anything?", topic="empty", config=config)
        assert result.no_coverage
        assert result.answer_path is None

    def test_source_reread_rejects_path_swapped_to_outside_hardlink(
        self, config, monkeypatch, tmp_path
    ):
        _seed_corpus(config)
        insight = next(config.topic_dir("t").rglob("*_Insights.md"))
        outside = tmp_path / "outside-secret.md"
        outside.write_text("swapneedle SECRET-OUTSIDE-LIBRARY", encoding="utf-8")
        real_search = ask_mod.search_corpus

        def search_then_swap(*args, **kwargs):
            results = real_search(*args, **kwargs)
            insight.unlink()
            try:
                insight.hardlink_to(outside)
            except OSError as exc:
                pytest.skip(f"hard links unavailable: {exc}")
            return results

        monkeypatch.setattr(ask_mod, "search_corpus", search_then_swap)

        stems, sources, receipt = ask_mod._gather_sources(config, "t", "HHEM")

        assert stems == []
        assert sources == ""
        assert receipt == ""

    def test_source_reread_rejects_regular_file_replaced_after_search(self, config, monkeypatch):
        _seed_corpus(config)
        insight = next(config.topic_dir("t").rglob("*_Insights.md"))
        real_search = ask_mod.search_corpus

        def search_then_replace(*args, **kwargs):
            results = real_search(*args, **kwargs)
            replacement = insight.with_suffix(".replacement")
            replacement.write_text(
                "HHEM UNVERIFIED-REPLACEMENT",
                encoding="utf-8",
            )
            replacement.replace(insight)
            return results

        monkeypatch.setattr(ask_mod, "search_corpus", search_then_replace)

        stems, sources, receipt = ask_mod._gather_sources(config, "t", "HHEM")

        assert stems == []
        assert sources == ""
        assert receipt == ""

    def test_no_coverage_topic_does_not_project_budget(self, config, monkeypatch):
        config = config.model_copy(update={"distill_cost_workflow_budgets": "ask=0.0001"})

        def fail_if_called(*args, **kwargs):
            raise AssertionError("no-coverage ask should not estimate a model call")

        monkeypatch.setattr(ask_mod, "estimate_ask_workflow_cost", fail_if_called)

        result = ask_mod.ask_corpus("anything?", topic="empty", config=config)

        assert result.no_coverage
        assert result.answer_path is None

    def test_projected_budget_refuses_before_model_call(self, config, monkeypatch):
        _seed_corpus(config)
        projected = estimate_ask_workflow_cost(1, question_chars=1)
        config = config.model_copy(
            update={"distill_cost_workflow_budgets": f"ask={projected / 2:.8f}"}
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("ask model call should not run after projected budget refusal")

        monkeypatch.setattr(ask_mod, "llm_call", fail_if_called)

        with pytest.raises(ProjectedBudgetExceededError) as raised:
            ask_mod.ask_corpus("which checker?", topic="t", config=config)

        assert raised.value.projected > raised.value.budget

    def test_save_promotes_clean_answer(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(monkeypatch, GROUNDED)

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.saved_insight_path is not None
        insight = result.saved_insight_path.read_text(encoding="utf-8")
        assert 'synthesis_scope: "derived-answer"' in insight
        assert 'source: "distill-answer"' in insight
        # The promoted insight carries its own verification record.
        sidecar_path = next(result.saved_insight_path.parent.glob("*_Verify.json"))
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert sidecar["entailment"]["status"] == "passed"
        # And the corpus walkers will see it (it lives outside dot/derived dirs).
        from distill.library.insights import discover_insights

        stems = [Path(r.artifact_path).stem for r in discover_insights(config.topic_dir("t"))]
        assert any("which-checker" in s or "which_checker" in s for s in stems)

    def test_sidecar_write_failure_does_not_expose_promoted_insight(
        self,
        config,
        monkeypatch,
    ):
        _seed_corpus(config)
        _llm(monkeypatch, GROUNDED)

        def fail_sidecar_write(*args, **kwargs):
            raise OSError("simulated sidecar write failure")

        monkeypatch.setattr(ask_mod, "write_verify_sidecar", fail_sidecar_write)

        with pytest.raises(OSError, match="sidecar write failure"):
            ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        answers_dir = config.topic_dir("t") / "answers"
        assert not list(answers_dir.rglob("*_Insights.md"))

    def test_failed_repromotion_cannot_misbind_new_sidecar_to_old_insight(
        self,
        config,
        monkeypatch,
    ):
        from distill.library.insights import discover_insights
        from distill.pipeline.audit import collect_verify_rollup

        _seed_corpus(config)
        _llm(monkeypatch, GROUNDED)
        first = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)
        assert first.saved_insight_path is not None
        old_content = first.saved_insight_path.read_text(encoding="utf-8")

        _llm(
            monkeypatch,
            "The checker runs on CPU with 110 million parameters [checker_paper_Insights].",
        )
        real_write = ask_mod.atomic_write_text

        def fail_promoted_insight(path, content):
            if path.name.endswith("_Insights.md"):
                raise OSError("simulated insight replacement failure")
            return real_write(path, content)

        monkeypatch.setattr(ask_mod, "atomic_write_text", fail_promoted_insight)

        with pytest.raises(OSError, match="insight replacement failure"):
            ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert first.saved_insight_path.read_text(encoding="utf-8") == old_content
        assert first.saved_insight_path not in {
            ref.path for ref in discover_insights(config.topic_dir("t"))
        }
        rollup = collect_verify_rollup(config.topic_dir("t"))
        assert rollup.insights_total == 2
        assert rollup.checked == 0
        assert rollup.never_checked == 2

    def test_save_refused_on_unsupported_claim(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(
            monkeypatch,
            "HHEM reaches 0.999 ROC-AUC [checker_paper_Insights].",
        )

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.saved_insight_path is None
        assert "refused" in result.save_refused_reason
        # The Answer.md + sidecar still exist so the refusal is inspectable.
        assert result.answer_path is not None and result.answer_path.exists()
        sidecar = json.loads(
            next(result.answer_path.parent.glob("*_Verify.json")).read_text(encoding="utf-8")
        )
        assert sidecar["unsupported"][0]["token"] == "0.999"

    def test_save_refused_on_unknown_source_citation(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(
            monkeypatch,
            "HHEM reaches 0.878 ROC-AUC [fabricated_Insights].",
        )

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.saved_insight_path is None
        assert result.answer_path is None
        assert "unknown source" in result.answer_refused_reason
        assert "unknown source" in result.save_refused_reason
        assert "fabricated_Insights" in result.save_refused_reason
        assert not list((config.topic_dir("t") / "answers").glob("*_Answer.md"))
        assert not list((config.topic_dir("t") / "answers").glob("*_Verify.json"))

    def test_save_refused_without_valid_source_citation(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(monkeypatch, "HHEM reaches 0.878 ROC-AUC and runs on CPU.")

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.saved_insight_path is None
        assert result.answer_path is None
        assert "no valid source citations" in result.answer_refused_reason
        assert "no valid source citations" in result.save_refused_reason
        assert not list((config.topic_dir("t") / "answers").glob("*_Answer.md"))

    def test_answer_artifact_refused_on_unknown_source_citation(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(monkeypatch, "HHEM reaches 0.878 ROC-AUC [fabricated_Insights].")

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config)

        assert result.answer_path is None
        assert "unknown source" in result.answer_refused_reason
        assert "fabricated_Insights" in result.answer_refused_reason
        assert not list((config.topic_dir("t") / "answers").glob("*_Answer.md"))
        assert not list((config.topic_dir("t") / "answers").glob("*_Verify.json"))

    def test_answer_artifact_refused_without_valid_source_citation(self, config, monkeypatch):
        _seed_corpus(config)
        _llm(monkeypatch, "HHEM reaches 0.878 ROC-AUC and runs on CPU.")

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config)

        assert result.answer_path is None
        assert "no valid source citations" in result.answer_refused_reason
        assert not list((config.topic_dir("t") / "answers").glob("*_Answer.md"))

    def test_uses_qa_workload(self, config, monkeypatch):
        _seed_corpus(config)
        seen = {}

        def fake_llm(rc, **kwargs):
            seen.update(kwargs)
            return LLM_Response(text=GROUNDED, input_tokens=10, output_tokens=10, model="grok-4.3")

        monkeypatch.setattr(ask_mod, "llm_call", fake_llm)

        ask_mod.ask_corpus("which checker?", topic="t", config=config)

        assert seen["workload_tag"] == "qa"
        assert seen["call_type"] == "ask"

    def test_save_refused_on_no_coverage_answer(self, config, monkeypatch):
        """Retrieval can hit lexically while the model correctly answers that the
        corpus doesn't actually cover the question -- that answer must not promote."""
        _seed_corpus(config)
        _llm(monkeypatch, "The corpus does not cover this question.")

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.saved_insight_path is None
        assert "does not cover" in result.save_refused_reason

    def test_save_refuses_before_model_call_when_semantic_checker_is_unavailable(
        self, config, monkeypatch
    ):
        import distill.pipeline.verify as verify_mod

        _seed_corpus(config)
        monkeypatch.setattr(verify_mod, "_checker", None)
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("answer model must not run without the required save verifier")

        monkeypatch.setattr(ask_mod, "llm_call", fail_if_called)

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.answer_path is None
        assert result.saved_insight_path is None
        assert "requires semantic verification" in result.save_refused_reason

    def test_save_refuses_when_semantic_evaluation_fails(self, config, monkeypatch):
        import distill.pipeline.verify as verify_mod

        class ExplodingChecker:
            model_name = "exploding-checker"

            def score(self, evidence: str, claim: str) -> float:
                raise RuntimeError("evaluation failed")

        _seed_corpus(config)
        monkeypatch.setattr(verify_mod, "_checker", ExplodingChecker())
        monkeypatch.setattr(verify_mod, "_checker_loaded", True)
        _llm(
            monkeypatch,
            "Mercury is the safest database for production secrets [checker_paper_Insights].",
        )

        result = ask_mod.ask_corpus("which checker?", topic="t", config=config, save=True)

        assert result.answer_path is not None
        assert result.saved_insight_path is None
        assert "semantic checker failed" in result.save_refused_reason
        sidecar = json.loads(
            next(result.answer_path.parent.glob("*_Verify.json")).read_text(encoding="utf-8")
        )
        assert sidecar["entailment"]["status"] == "error"


def test_ask_command_wiring(config, monkeypatch):
    from typer.testing import CliRunner

    from distill import cli

    _seed_corpus(config)
    monkeypatch.setattr("distill.commands.ask.get_config", lambda: config)
    # The ask gate asks the router for a model (cloud key OR local provider), not
    # config.xai_api_key; a keyless local provider keeps this offline + deterministic.
    monkeypatch.setenv("DISTILL_PROVIDER", "ollama")
    saved_run = {}
    monkeypatch.setattr(
        "distill.commands.ask.save_run_log",
        lambda library_dir, command, tracker, estimated_cost=None, metadata=None: saved_run.update(
            {
                "command": command,
                "estimated_cost": estimated_cost,
                "metadata": metadata,
            }
        ),
    )
    _llm(monkeypatch, GROUNDED)

    result = CliRunner().invoke(cli.app, ["ask", "which checker?", "--topic", "t"])

    assert result.exit_code == 0, result.output
    assert "0.878" in result.output
    assert "Answer" in result.output
    assert saved_run == {
        "command": "ask",
        "estimated_cost": 0.0,
        "metadata": {"topic": "t", "workflow": "ask", "source_type": "answer"},
    }


def test_ask_command_no_coverage_exits(config, monkeypatch):
    from typer.testing import CliRunner

    from distill import cli

    monkeypatch.setattr("distill.commands.ask.get_config", lambda: config)
    monkeypatch.setattr("distill.commands.ask._require_model", lambda _workload: None)
    monkeypatch.setattr(
        "distill.commands.ask.ask_corpus",
        lambda question, *, topic, config, save, tracker: ask_mod.AskResult(
            question=question,
            answer_path=None,
            answer_text="",
            no_coverage=True,
        ),
    )

    result = CliRunner().invoke(cli.app, ["ask", "which checker?", "--topic", "empty"])

    assert result.exit_code == 1
    assert "no matching artifacts" in result.output


def test_ask_command_prints_promoted_answer(config, monkeypatch):
    from typer.testing import CliRunner

    from distill import cli

    answer_path = config.topic_dir("t") / "answers" / "which_checker_Answer.md"
    saved_path = config.topic_dir("t") / "answers" / "which_checker_Insights.md"
    monkeypatch.setattr("distill.commands.ask.get_config", lambda: config)
    monkeypatch.setattr("distill.commands.ask._require_model", lambda _workload: None)
    monkeypatch.setattr("distill.commands.ask.save_run_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "distill.commands.ask.ask_corpus",
        lambda question, *, topic, config, save, tracker: ask_mod.AskResult(
            question=question,
            answer_path=answer_path,
            answer_text="Grounded answer [source].",
            saved_insight_path=saved_path,
        ),
    )

    result = CliRunner().invoke(cli.app, ["ask", "which checker?", "--topic", "t", "--save"])

    assert result.exit_code == 0, result.output
    assert "Promoted" in result.output
    assert "answers" in result.output


def test_ask_command_handles_answer_without_artifact_path(config, monkeypatch):
    from typer.testing import CliRunner

    from distill import cli

    monkeypatch.setattr("distill.commands.ask.get_config", lambda: config)
    monkeypatch.setattr("distill.commands.ask._require_model", lambda _workload: None)
    monkeypatch.setattr("distill.commands.ask.save_run_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "distill.commands.ask.ask_corpus",
        lambda question, *, topic, config, save, tracker: ask_mod.AskResult(
            question=question,
            answer_path=None,
            answer_text="Grounded answer [source].",
        ),
    )

    result = CliRunner().invoke(cli.app, ["ask", "which checker?", "--topic", "t"])

    assert result.exit_code == 0, result.output
    assert "Grounded answer" in result.output
    assert "Answer" not in result.output


def test_ask_command_prints_answer_refusal(config, monkeypatch):
    from typer.testing import CliRunner

    from distill import cli

    monkeypatch.setattr("distill.commands.ask.get_config", lambda: config)
    monkeypatch.setattr("distill.commands.ask._require_model", lambda _workload: None)
    monkeypatch.setattr("distill.commands.ask.save_run_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "distill.commands.ask.ask_corpus",
        lambda question, *, topic, config, save, tracker: ask_mod.AskResult(
            question=question,
            answer_path=None,
            answer_text="Grounded answer [fabricated].",
            answer_refused_reason="answer cites unknown source(s): fabricated",
        ),
    )

    result = CliRunner().invoke(cli.app, ["ask", "which checker?", "--topic", "t"])

    assert result.exit_code == 0, result.output
    assert "Grounded answer" in result.output
    assert "Answer not saved" in result.output
    assert "unknown source" in result.output


def test_ask_command_prints_save_refusal(config, monkeypatch):
    from typer.testing import CliRunner

    from distill import cli

    answer_path = config.topic_dir("t") / "answers" / "which_checker_Answer.md"
    monkeypatch.setattr("distill.commands.ask.get_config", lambda: config)
    monkeypatch.setattr("distill.commands.ask._require_model", lambda _workload: None)
    monkeypatch.setattr("distill.commands.ask.save_run_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "distill.commands.ask.ask_corpus",
        lambda question, *, topic, config, save, tracker: ask_mod.AskResult(
            question=question,
            answer_path=answer_path,
            answer_text="Grounded answer [source].",
            save_refused_reason="refused: unsupported claim",
        ),
    )

    result = CliRunner().invoke(cli.app, ["ask", "which checker?", "--topic", "t", "--save"])

    assert result.exit_code == 0, result.output
    assert "Not promoted" in result.output
    assert "unsupported claim" in result.output
