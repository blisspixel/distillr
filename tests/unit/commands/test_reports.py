"""Unit tests for ``distill.commands.reports`` report and export commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from distill import cli
from distill.commands import reports as reports_mod
from distill.config import DistillConfig
from distill.library import Library
from distill.library.citations import CitationRecord
from distill.library.okf import OkfExportResult, OkfIssue, OkfValidationResult
from distill.library.paths import artifact_path
from distill.llm.cost_policy import CostPolicyError
from distill.pipeline.costs import BudgetExceededError, CostTracker, ProjectedBudgetExceededError

runner = CliRunner()


def _config(tmp_path) -> DistillConfig:
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="gemini-key",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


def _seed_topic(config: DistillConfig, topic: str = "ai", channel: str = "TestCh") -> None:
    lib = Library(config)
    lib.add_channel(topic, f"https://www.youtube.com/@{channel}", channel)


def _okf_result(
    tmp_path: Path,
    *,
    ok: bool = True,
    warnings: bool = False,
) -> OkfExportResult:
    validation = OkfValidationResult(
        root=tmp_path / "okf-ai",
        files_checked=3,
        errors=() if ok else (OkfIssue("error", "index.md", "missing type"),),
        warnings=((OkfIssue("warning", "log.md", "broken link"),) if warnings else ()),
    )
    return OkfExportResult(
        output_dir=tmp_path / "okf-ai",
        source_root=tmp_path / "library",
        topic="ai",
        files_written=4,
        validation=validation,
    )


class TestReportCommand:
    def _patch_common(self, monkeypatch, config):
        monkeypatch.setattr(reports_mod, "get_config", lambda: config)
        monkeypatch.setattr(reports_mod, "display_summary", lambda *args, **kwargs: None)

    def test_requires_topic_or_all(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["report"])

        assert result.exit_code == 1
        assert "Specify a topic or use --all" in result.output

    def test_requires_gemini_key(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        config.gemini_api_key = ""
        self._patch_common(monkeypatch, config)

        result = runner.invoke(cli.app, ["report", "ai"])

        assert result.exit_code == 1
        assert "GEMINI_API_KEY" in result.output

    def test_refuses_projected_report_budget_before_deep_research(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        config.distill_cost_workflow_budgets = "report=0.0001"
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        run_report = MagicMock(return_value="# Should not run")
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            run_report,
        )

        result = runner.invoke(cli.app, ["report", "ai"])

        assert result.exit_code == 1
        assert isinstance(result.exception, ProjectedBudgetExceededError)
        run_report.assert_not_called()

    @pytest.mark.parametrize("extra_args", [(), ("--legacy",)])
    def test_no_metered_refuses_before_report_pipeline_or_client(
        self, tmp_path, monkeypatch, extra_args
    ):
        config = _config(tmp_path)
        config.distill_cost_mode = "no-metered"
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        accordion_report = MagicMock(return_value="# Should not run")
        legacy_report = MagicMock(return_value="# Should not run")
        accordion_client = MagicMock(side_effect=AssertionError("client constructed"))
        legacy_client = MagicMock(side_effect=AssertionError("client constructed"))
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            accordion_report,
        )
        monkeypatch.setattr(reports_mod, "run_deep_research", legacy_report)
        monkeypatch.setattr("distill.pipeline.report.accordion.genai.Client", accordion_client)
        monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", legacy_client)

        result = runner.invoke(cli.app, ["report", "ai", *extra_args])

        assert result.exit_code == 1
        assert isinstance(result.exception, CostPolicyError)
        assert "Route blocked by no-metered cost policy" in str(result.exception)
        accordion_report.assert_not_called()
        legacy_report.assert_not_called()
        accordion_client.assert_not_called()
        legacy_client.assert_not_called()

    @pytest.mark.parametrize("cost_mode", ["auto", "paid-ok"])
    def test_metered_cost_modes_reach_report_pipeline(self, tmp_path, monkeypatch, cost_mode):
        config = _config(tmp_path)
        config.distill_cost_mode = cost_mode
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        run_report = MagicMock(return_value=None)
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            run_report,
        )

        result = runner.invoke(cli.app, ["report", "ai"])

        assert result.exit_code == 1
        run_report.assert_called_once()

    def test_budget_failure_persists_submitted_report_cost(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        tracker = CostTracker(budget=0.0)
        monkeypatch.setattr(reports_mod, "budgeted_cost_tracker", lambda *args: tracker)

        def cross_budget(**kwargs):
            kwargs["tracker"].record_gemini_query("deep-research-preview-04-2026")
            raise AssertionError("record_gemini_query should have raised")

        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            cross_budget,
        )

        result = runner.invoke(cli.app, ["report", "ai"])

        assert result.exit_code == 1
        assert isinstance(result.exception, BudgetExceededError)
        log_path = config.library_dir / ".distill" / "cost_log.jsonl"
        rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["command"] == "report"
        assert rows[0]["gemini_queries"] == 1
        assert rows[0]["metadata"] == {
            "topic": "ai",
            "workflow": "report",
            "scope": "topic",
        }

    def test_accordion_report_success(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        report_md = artifact_path(config.topic_dir("ai"), "report", identity="ai")
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text("# Strategic report", encoding="utf-8")
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            lambda **kwargs: "# Strategic report\n\nBody",
        )
        monkeypatch.setattr(reports_mod, "markdown_to_docx", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            "distill.library.export.export_report",
            MagicMock(side_effect=RuntimeError("fancy docx fail")),
        )

        result = runner.invoke(
            cli.app,
            ["report", "ai", "--focus", "risks", "--test", "--no-qa", "--sections", "exec,risks"],
        )

        assert result.exit_code == 0
        assert "Report complete" in result.output
        assert "What's next" in result.output
        assert (config.library_dir.parent / "output" / "report-ai.md").exists()

    def test_legacy_report_success(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        report_md = artifact_path(config.topic_dir("ai"), "report", identity="ai")
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text("# Legacy report", encoding="utf-8")
        monkeypatch.setattr(
            reports_mod,
            "run_deep_research",
            lambda **kwargs: "# Legacy report\n\nBody",
        )
        monkeypatch.setattr("distill.library.export.export_report", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["report", "ai", "--legacy"])

        assert result.exit_code == 0
        assert "Legacy (single-shot)" in result.output

    def test_research_only_skips_docx_export(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        report_md = artifact_path(config.topic_dir("ai"), "report", identity="ai")
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text("# Research only", encoding="utf-8")
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            lambda **kwargs: "# Research only\n",
        )
        docx_called = {"value": False}
        monkeypatch.setattr(
            reports_mod,
            "markdown_to_docx",
            lambda *args, **kwargs: docx_called.__setitem__("value", True),
        )

        result = runner.invoke(cli.app, ["report", "ai", "--research-only"])

        assert result.exit_code == 0
        assert docx_called["value"] is False

    def test_report_all_topics_metadata(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            lambda **kwargs: None,
        )

        result = runner.invoke(cli.app, ["report", "--all"])

        assert result.exit_code == 1
        assert "entire library" in result.output

    def test_report_channel_scope_names_output(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        report_md = artifact_path(
            config.channel_dir("ai", "TestCh"), "report", identity="ai_TestCh"
        )
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text("# Channel report", encoding="utf-8")
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            lambda **kwargs: "# Channel report\n",
        )
        monkeypatch.setattr(reports_mod, "markdown_to_docx", lambda *args, **kwargs: None)
        monkeypatch.setattr("distill.library.export.export_report", lambda *args, **kwargs: None)

        result = runner.invoke(cli.app, ["report", "ai", "--channel", "TestCh"])

        assert result.exit_code == 0
        assert "channel: TestCh" in result.output
        assert (config.library_dir.parent / "output" / "report-ai-TestCh.md").exists()

    def test_docx_export_failure_falls_back_and_warns(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        report_md = artifact_path(config.topic_dir("ai"), "report", identity="ai")
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text("# Strategic report", encoding="utf-8")
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            lambda **kwargs: "# Strategic report\n",
        )
        monkeypatch.setattr(
            "distill.library.export.export_report",
            MagicMock(side_effect=RuntimeError("fancy docx fail")),
        )
        monkeypatch.setattr(
            reports_mod,
            "markdown_to_docx",
            MagicMock(side_effect=RuntimeError("basic docx fail")),
        )

        result = runner.invoke(cli.app, ["report", "ai"])

        assert result.exit_code == 0
        assert "DOCX export failed" in result.output

    def test_empty_result_exits(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_common(monkeypatch, config)
        monkeypatch.setattr(
            "distill.pipeline.report.accordion.run_accordion_research",
            lambda **kwargs: None,
        )

        result = runner.invoke(cli.app, ["report", "ai"])

        assert result.exit_code == 1


class TestExportCommand:
    def _patch_config(self, monkeypatch, config):
        monkeypatch.setattr(reports_mod, "get_config", lambda: config)

    def test_okf_topic_missing(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_config(monkeypatch, config)
        monkeypatch.setattr(
            reports_mod,
            "export_okf_bundle",
            MagicMock(side_effect=FileNotFoundError("missing topic")),
        )

        result = runner.invoke(cli.app, ["export", "ai", "--what", "bundle", "--format", "okf"])

        assert result.exit_code == 1
        assert "Topic not found" in result.output

    def test_okf_validation_failure(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_config(monkeypatch, config)
        monkeypatch.setattr(
            reports_mod,
            "export_okf_bundle",
            lambda *args, **kwargs: _okf_result(tmp_path, ok=False),
        )

        result = runner.invoke(cli.app, ["export", "ai", "--what", "bundle", "--format", "okf"])

        assert result.exit_code == 1
        assert "failed validation" in result.output

    def test_okf_success_with_warnings(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_config(monkeypatch, config)
        monkeypatch.setattr(
            reports_mod,
            "export_okf_bundle",
            lambda *args, **kwargs: _okf_result(tmp_path, warnings=True),
        )

        result = runner.invoke(cli.app, ["export", "ai", "--what", "bundle", "--format", "okf"])

        assert result.exit_code == 0
        assert "Exported OKF bundle" in result.output
        assert "OKF warning" in result.output

    def test_zip_bundle_topic_missing(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_config(monkeypatch, config)

        result = runner.invoke(cli.app, ["export", "missing", "--what", "bundle"])

        assert result.exit_code == 1
        assert "Topic not found" in result.output

    def test_zip_bundle_success(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)
        zip_path = tmp_path / "output" / "corpus-ai-bundle.zip"
        zip_path.parent.mkdir(parents=True)
        zip_path.write_bytes(b"zip-bytes")
        monkeypatch.setattr(
            reports_mod,
            "_collect_topic_bundle_files",
            lambda *args, **kwargs: [config.topic_dir("ai") / "topic_synthesis.md"],
        )
        monkeypatch.setattr(reports_mod, "_export_topic_bundle", lambda *args, **kwargs: zip_path)

        result = runner.invoke(cli.app, ["export", "ai", "--what", "bundle"])

        assert result.exit_code == 0
        assert "Exported bundle" in result.output

    def test_zip_bundle_no_files(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        config.topic_dir("ai").mkdir(parents=True, exist_ok=True)
        self._patch_config(monkeypatch, config)
        monkeypatch.setattr(reports_mod, "_collect_topic_bundle_files", lambda *args, **kwargs: [])

        result = runner.invoke(cli.app, ["export", "ai", "--what", "bundle"])

        assert result.exit_code == 1
        assert "No exportable corpus files" in result.output

    def test_citations_rejects_channel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)

        result = runner.invoke(
            cli.app, ["export", "ai", "--what", "citations", "--channel", "TestCh"]
        )

        assert result.exit_code == 1
        assert "topic-level" in result.output

    def test_citations_value_error(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)
        monkeypatch.setattr(
            reports_mod,
            "render_citations",
            MagicMock(side_effect=ValueError("unsupported format")),
        )
        monkeypatch.setattr(reports_mod, "collect_paper_citations", lambda *args, **kwargs: [])

        result = runner.invoke(
            cli.app, ["export", "ai", "--what", "citations", "--format", "bogus"]
        )

        assert result.exit_code == 1
        assert "unsupported format" in result.output

    def test_citations_refuses_missing_record_path(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)
        missing_path = config.topic_dir("ai") / "papers" / "missing" / "metadata.json"
        record = CitationRecord(
            topic="ai",
            title="Missing Evidence",
            authors=("Alice Example",),
            year="2026",
            published_at="2026-02-17T00:00:00Z",
            updated_at="",
            paper_id="2602.12670v1",
            doi="",
            url="https://arxiv.org/abs/2602.12670v1",
            pdf_url="",
            categories=(),
            abstract="",
            path=missing_path,
        )
        monkeypatch.setattr(
            reports_mod, "collect_paper_citations", lambda *args, **kwargs: [record]
        )

        result = runner.invoke(cli.app, ["export", "ai", "--what", "citations"])

        assert result.exit_code == 1
        assert "citation record path does not exist" in result.output
        assert not (config.library_dir.parent / "output" / "citations-ai.bib").exists()

    def test_citations_success_writes_file(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)
        monkeypatch.setattr(
            reports_mod, "collect_paper_citations", lambda *args, **kwargs: ["cite"]
        )
        monkeypatch.setattr(
            reports_mod, "render_citations", lambda *args, **kwargs: "@article{demo}"
        )

        result = runner.invoke(cli.app, ["export", "ai", "--what", "citations"])

        assert result.exit_code == 0
        assert (config.library_dir.parent / "output" / "citations-ai.bib").exists()

    def test_citations_empty_content(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)
        monkeypatch.setattr(reports_mod, "collect_paper_citations", lambda *args, **kwargs: [])
        monkeypatch.setattr(reports_mod, "render_citations", lambda *args, **kwargs: "")

        result = runner.invoke(cli.app, ["export", "ai", "--what", "citations"])

        assert result.exit_code == 1
        assert "No paper citations" in result.output

    def test_export_topic_synthesis(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)
        topic_dir = config.topic_dir("ai")
        topic_dir.mkdir(parents=True, exist_ok=True)
        (topic_dir / "topic_synthesis.md").write_text("# Topic synth", encoding="utf-8")
        monkeypatch.setattr(
            reports_mod,
            "markdown_to_docx",
            lambda md_path, docx_path, title: docx_path.write_text("docx", encoding="utf-8"),
        )

        result = runner.invoke(cli.app, ["export", "ai", "--what", "synthesis"])

        assert result.exit_code == 0

    def test_unknown_export_type(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)

        result = runner.invoke(cli.app, ["export", "ai", "--what", "unknown"])

        assert result.exit_code == 1
        assert "Unknown export type" in result.output

    def test_export_synthesis_channel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)
        ch_dir = config.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "synthesis.md").write_text("# Channel synth", encoding="utf-8")
        monkeypatch.setattr(
            reports_mod,
            "markdown_to_docx",
            lambda md_path, docx_path, title: docx_path.write_text("docx", encoding="utf-8"),
        )

        result = runner.invoke(
            cli.app, ["export", "ai", "--what", "synthesis", "--channel", "TestCh"]
        )

        assert result.exit_code == 0
        assert "Exported:" in result.output

    def test_export_report_channel(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)
        ch_dir = config.channel_dir("ai", "TestCh")
        ch_dir.mkdir(parents=True, exist_ok=True)
        (ch_dir / "report.md").write_text("# Channel report", encoding="utf-8")
        monkeypatch.setattr(
            reports_mod,
            "markdown_to_docx",
            lambda md_path, docx_path, title: docx_path.write_text("docx", encoding="utf-8"),
        )

        result = runner.invoke(cli.app, ["export", "TestCh", "--what", "report"])

        assert result.exit_code == 0

    def test_export_missing_markdown_source(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        _seed_topic(config)
        self._patch_config(monkeypatch, config)

        result = runner.invoke(cli.app, ["export", "ai", "--what", "synthesis"])

        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_report_format_okf_rewrites_what_to_bundle(self, tmp_path, monkeypatch):
        config = _config(tmp_path)
        self._patch_config(monkeypatch, config)
        monkeypatch.setattr(
            reports_mod,
            "export_okf_bundle",
            lambda *args, **kwargs: _okf_result(tmp_path),
        )

        result = runner.invoke(cli.app, ["export", "ai", "--format", "okf"])

        assert result.exit_code == 0
        assert "Exported OKF bundle" in result.output


class TestRegister:
    def test_register_adds_report_commands(self):
        app = typer.Typer()
        reports_mod.register(app)
        callbacks = {cmd.callback for cmd in app.registered_commands}
        assert reports_mod.report in callbacks
        assert reports_mod.export in callbacks
