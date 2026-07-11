"""Unit tests for ``distill.commands.learn`` preview and learning CLI commands."""

from __future__ import annotations

from unittest.mock import MagicMock

import typer
from typer.testing import CliRunner

from distill import cli
from distill.commands import learn as learn_mod
from distill.config import DistillConfig
from distill.llm.cost_policy import CostPolicyError
from distill.pipeline.costs import CostTracker, ProjectedBudgetExceededError

runner = CliRunner()


def _config(tmp_path) -> DistillConfig:
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="gemini-key",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _preview_return(config: DistillConfig):
    return config, CostTracker(), []


class TestSearchAndExplore:
    def _patch_preview(self, monkeypatch, config):
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        monkeypatch.setattr(learn_mod, "_preflight", lambda: None)
        monkeypatch.setattr(
            learn_mod, "_preview_learning_selection", lambda *a, **k: _preview_return(config)
        )
        monkeypatch.setattr(learn_mod, "log_preview_cost", lambda *a, **k: None)

    def test_search_preview_happy_path(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_preview(monkeypatch, config)
        monkeypatch.setattr(learn_mod, "model_available", lambda _workload: True)

        result = runner.invoke(cli.app, ["search", "agent memory"])

        assert result.exit_code == 0
        assert 'distill learn "..."' in result.output

    def test_search_shows_rerank_fallback_warning(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_preview(monkeypatch, config)
        monkeypatch.setattr(learn_mod, "model_available", lambda _workload: False)

        result = runner.invoke(cli.app, ["search", "agent memory"])

        assert result.exit_code == 0
        assert "deterministic ranking fallback" in result.output

    def test_explore_preview_happy_path(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_preview(monkeypatch, config)
        monkeypatch.setattr(learn_mod, "model_available", lambda _workload: True)

        result = runner.invoke(cli.app, ["explore", "vector databases"])

        assert result.exit_code == 0
        assert "distill latest" in result.output

    def test_explore_shows_rerank_fallback_warning(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_preview(monkeypatch, config)
        monkeypatch.setattr(learn_mod, "model_available", lambda _workload: False)

        result = runner.invoke(cli.app, ["explore", "vector databases"])

        assert result.exit_code == 0
        assert "deterministic ranking fallback" in result.output


class TestResearchBrief:
    def _patch_common(self, monkeypatch, config):
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        monkeypatch.setattr(learn_mod, "display_summary", lambda *args, **kwargs: None)

    def test_requires_topic_entries(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(
            cli.app,
            ["research-brief", "--topic", " , ", "--name", "demo", "--context", "Brief me"],
        )

        assert result.exit_code == 1
        assert "At least one --topic is required" in result.output

    def test_expands_comma_separated_topics(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)
        seen: list[str] = []

        def capture(**kwargs):
            seen.extend(kwargs["topics"])
            return tmp_path / "output" / "briefing-demo.md"

        monkeypatch.setattr(learn_mod, "run_research_brief", capture)

        result = runner.invoke(
            cli.app,
            [
                "research-brief",
                "--topic",
                "ai,rag",
                "--name",
                "demo",
                "--context",
                "Compare approaches",
            ],
        )

        assert result.exit_code == 0
        assert seen == ["ai", "rag"]

    def test_context_file_not_found(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(
            cli.app,
            [
                "research-brief",
                "--topic",
                "ai",
                "--name",
                "demo",
                "--context-file",
                str(tmp_path / "missing.md"),
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_requires_context_instructions(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["research-brief", "--topic", "ai", "--name", "demo"])

        assert result.exit_code == 1
        assert "needs instructions" in result.output

    def test_requires_gemini_api_key(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        config.gemini_api_key = ""
        self._patch_common(monkeypatch, config)

        result = runner.invoke(
            cli.app,
            ["research-brief", "--topic", "ai", "--name", "demo", "--context", "Brief me"],
        )

        assert result.exit_code == 1
        assert "GEMINI_API_KEY" in result.output

    def test_refuses_projected_research_brief_budget_before_deep_research(
        self, tmp_path, monkeypatch
    ):
        config = _config(tmp_path)
        config.distill_cost_workflow_budgets = "research-brief=0.0001"
        self._patch_common(monkeypatch, config)
        run_brief = MagicMock(return_value=tmp_path / "output" / "briefing-demo.md")
        monkeypatch.setattr(learn_mod, "run_research_brief", run_brief)

        result = runner.invoke(
            cli.app,
            ["research-brief", "--topic", "ai", "--name", "demo", "--context", "Brief me"],
        )

        assert result.exit_code == 1
        assert isinstance(result.exception, ProjectedBudgetExceededError)
        run_brief.assert_not_called()

    def test_no_metered_refuses_before_research_brief_pipeline(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        config.distill_cost_mode = "no-metered"
        self._patch_common(monkeypatch, config)
        run_brief = MagicMock(return_value=tmp_path / "output" / "briefing-demo.md")
        monkeypatch.setattr(learn_mod, "run_research_brief", run_brief)

        result = runner.invoke(
            cli.app,
            ["research-brief", "--topic", "ai", "--name", "demo", "--context", "Brief me"],
        )

        assert result.exit_code == 1
        assert isinstance(result.exception, CostPolicyError)
        assert "Route blocked by no-metered cost policy" in str(result.exception)
        run_brief.assert_not_called()

    def test_success_writes_output(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)
        out = tmp_path / "output" / "briefing-demo.md"
        out.parent.mkdir(parents=True)
        out.write_text("# Brief", encoding="utf-8")
        monkeypatch.setattr(learn_mod, "run_research_brief", lambda **kwargs: out)

        result = runner.invoke(
            cli.app,
            ["research-brief", "--topic", "ai", "--name", "demo", "--context", "Brief me"],
        )

        assert result.exit_code == 0

    def test_context_file_merges_with_inline_context(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)
        context_file = tmp_path / "ctx.md"
        context_file.write_text("File body", encoding="utf-8")
        captured: dict[str, str] = {}

        def capture(**kwargs):
            captured["context"] = kwargs["context"]
            return tmp_path / "output" / "briefing-demo.md"

        monkeypatch.setattr(learn_mod, "run_research_brief", capture)

        runner.invoke(
            cli.app,
            [
                "research-brief",
                "--topic",
                "ai",
                "--name",
                "demo",
                "--context",
                "Inline",
                "--context-file",
                str(context_file),
            ],
        )

        assert "Inline" in captured["context"]
        assert "File body" in captured["context"]

    def test_failure_without_output_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(learn_mod, "run_research_brief", lambda **kwargs: None)

        result = runner.invoke(
            cli.app,
            ["research-brief", "--topic", "ai", "--name", "demo", "--context", "Brief me"],
        )

        assert result.exit_code == 1

    def test_propagates_research_brief_errors(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)

        def boom(**kwargs):
            raise RuntimeError("deep research fail")

        monkeypatch.setattr(learn_mod, "run_research_brief", boom)

        result = runner.invoke(
            cli.app,
            ["research-brief", "--topic", "ai", "--name", "demo", "--context", "Brief me"],
        )

        assert result.exit_code != 0


class TestLearnAndBrief:
    def test_learn_delegates_to_run_learning_command(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        captured: dict = {}

        def capture(*args, **kwargs):
            captured.update(kwargs)
            captured["query"] = args[0]

        monkeypatch.setattr(learn_mod, "_run_learning_command", capture)

        result = runner.invoke(cli.app, ["learn", "agent loops", "--topic", "ai", "--limit", "3"])

        assert result.exit_code == 0
        assert captured["query"] == "agent loops"
        assert captured["topic"] == "ai"
        assert captured["limit"] == 3
        assert captured["generate_brief"] is False
        assert captured["header"] == "Learning"

    def test_brief_delegates_with_generate_brief(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        captured: dict = {}

        def capture(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(learn_mod, "_run_learning_command", capture)

        result = runner.invoke(cli.app, ["brief", "agent loops", "--report"])

        assert result.exit_code == 0
        assert captured["generate_brief"] is True
        assert captured["report"] is True
        assert captured["header"] == "Briefing"


class TestLatest:
    def test_rejects_unknown_rigor(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)

        result = runner.invoke(cli.app, ["latest", "ai news", "--rigor", "bogus"])

        assert result.exit_code == 1
        assert "Unknown --rigor" in result.output

    def test_preview_mode(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        monkeypatch.setattr(
            learn_mod, "_preview_learning_selection", lambda *a, **k: _preview_return(config)
        )
        monkeypatch.setattr(learn_mod, "log_preview_cost", lambda *a, **k: None)
        monkeypatch.setattr(learn_mod, "model_available", lambda _workload: True)

        result = runner.invoke(cli.app, ["latest", "ai news", "--preview"])

        assert result.exit_code == 0
        assert "without `--preview`" in result.output

    def test_preview_rerank_fallback(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        monkeypatch.setattr(
            learn_mod, "_preview_learning_selection", lambda *a, **k: _preview_return(config)
        )
        monkeypatch.setattr(learn_mod, "log_preview_cost", lambda *a, **k: None)
        monkeypatch.setattr(learn_mod, "model_available", lambda _workload: False)

        result = runner.invoke(cli.app, ["latest", "ai news", "--preview"])

        assert result.exit_code == 0
        assert "deterministic ranking fallback" in result.output

    def test_top_by_date_disables_rerank(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        captured: dict = {}

        def capture(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(learn_mod, "_run_learning_command", capture)

        result = runner.invoke(cli.app, ["latest", "ai news", "--top-by-date"])

        assert result.exit_code == 0
        assert captured["top_by_date"] is True
        assert captured["rerank"] is False
        assert captured["expand"] is False

    def test_concepts_flag_sets_post_ingest_callback(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        captured: dict = {}

        def capture(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(learn_mod, "_run_learning_command", capture)

        result = runner.invoke(cli.app, ["latest", "ai news", "--concepts"])

        assert result.exit_code == 0
        assert captured["post_ingest_callback"] is not None

    def test_lens_and_verify_hooks(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        verify_calls: list[str] = []
        persist_calls: list[tuple] = []
        monkeypatch.setattr(
            learn_mod, "_apply_verify_override", lambda mode: verify_calls.append(mode)
        )
        monkeypatch.setattr(
            learn_mod,
            "_persist_lens",
            lambda cfg, topic, query, lens: persist_calls.append((topic, query, lens)),
        )
        monkeypatch.setattr(learn_mod, "_run_learning_command", lambda *a, **k: None)

        result = runner.invoke(
            cli.app,
            ["latest", "ai news", "--topic", "ai", "--lens", "research", "--verify", "strict"],
        )

        assert result.exit_code == 0
        assert verify_calls == ["strict"]
        assert persist_calls == [("ai", "ai news", "research")]

    def test_latest_delegates_processing(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        monkeypatch.setattr(learn_mod, "get_config", lambda: config)
        captured: dict = {}

        def capture(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(learn_mod, "_run_learning_command", capture)

        result = runner.invoke(
            cli.app,
            ["latest", "ai news", "--brief", "--rigor", "balanced", "--shorts"],
        )

        assert result.exit_code == 0
        assert captured["generate_brief"] is True
        assert captured["rigor"] == "balanced"
        assert captured["shorts"] is True
        assert captured["header"] == "Latest"


class TestRegister:
    def test_register_adds_learning_commands(self):
        app = typer.Typer()
        learn_mod.register(app)
        names = {cmd.name for cmd in app.registered_commands}
        assert names == {
            "search",
            "explore",
            "research-brief",
            "learn",
            "brief",
            "latest",
        }
