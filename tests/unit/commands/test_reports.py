"""Unit tests for ``distill.commands.reports`` report and export commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import typer
from typer.testing import CliRunner

from distill import cli
from distill.commands import reports as reports_mod
from distill.config import DistillConfig
from distill.library import Library
from distill.library.okf import OkfExportResult, OkfIssue, OkfValidationResult
from distill.library.paths import artifact_path

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
