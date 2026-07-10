"""Hermetic boundary tests for report generation and budget handling."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from distill.commands import _helpers
from distill.commands import _report_helpers as report_helpers
from distill.config import DistillConfig
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.summary import RunSummary


@pytest.fixture
def config(tmp_path: Path) -> DistillConfig:
    return DistillConfig(
        gemini_api_key=SecretStr("test-key"),
        distill_output_dir=tmp_path / "library",
    )


def _install_report_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: str | None,
    report_path: Path,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "distill.pipeline.report.accordion",
        SimpleNamespace(run_accordion_research=lambda **_kwargs: result),
    )
    monkeypatch.setitem(
        sys.modules,
        "distill.pipeline.report.deep_research",
        SimpleNamespace(_get_report_path=lambda *_args, **_kwargs: report_path),
    )


def test_missing_gemini_key_stops_before_report_without_summary(
    config: DistillConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.gemini_api_key = SecretStr("")
    calls: list[str] = []
    monkeypatch.setattr(
        report_helpers,
        "_run_accordion_report_with_budget_log",
        lambda **_kwargs: calls.append("report"),
    )

    report_helpers.run_scope_report("ai", config, CostTracker(), scope="topic")

    assert calls == []


def test_empty_report_without_summary_logs_cost_delta(
    config: DistillConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_report_modules(monkeypatch, result="", report_path=tmp_path / "missing.md")
    logged: list[dict[str, str]] = []
    monkeypatch.setattr(
        report_helpers,
        "_log_report_cost_delta",
        lambda _config, _tracker, **kwargs: logged.append(kwargs["metadata"]),
    )

    report_helpers.run_scope_report("ai", config, CostTracker(), scope="topic")

    assert logged == [{"topic": "ai", "workflow": "report", "scope": "topic", "channel": ""}]


def test_success_without_summary_copies_markdown_and_exports_docx(
    config: DistillConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "source.md"
    report_path.write_text("# Report\n\nVerified body.\n", encoding="utf-8")
    _install_report_modules(monkeypatch, result="verified report body", report_path=report_path)
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    monkeypatch.setattr(_helpers, "output_path", lambda _config, name: output_dir / name)
    exports: list[tuple[Path, Path, str]] = []

    def export_report(source: Path, *, docx_path: Path, title: str) -> None:
        exports.append((source, docx_path, title))
        docx_path.write_bytes(b"docx")

    monkeypatch.setattr("distill.library.export.export_report", export_report)

    report_helpers.run_scope_report(
        "ai",
        config,
        CostTracker(),
        scope="channel",
        channel_name="Research Lab",
    )

    markdown_output = output_dir / "report-ai-Research Lab.md"
    docx_output = output_dir / "report-ai-Research Lab.docx"
    assert markdown_output.read_text(encoding="utf-8") == report_path.read_text(encoding="utf-8")
    assert docx_output.read_bytes() == b"docx"
    assert exports == [(report_path, docx_output, "Strategic Intelligence: Research Lab")]


def test_missing_report_artifact_logs_delta_without_copy(
    config: DistillConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing_path = tmp_path / "missing.md"
    _install_report_modules(monkeypatch, result="reported words", report_path=missing_path)
    logged: list[dict[str, str]] = []
    output_calls: list[str] = []
    monkeypatch.setattr(
        report_helpers,
        "_log_report_cost_delta",
        lambda _config, _tracker, **kwargs: logged.append(kwargs["metadata"]),
    )
    monkeypatch.setattr(
        _helpers,
        "output_path",
        lambda _config, name: output_calls.append(name),
    )

    report_helpers.run_scope_report("ai", config, CostTracker(), scope="topic")

    assert len(logged) == 1
    assert logged[0]["workflow"] == "report"
    assert output_calls == []


@pytest.mark.parametrize("with_summary", [False, True], ids=["without-summary", "with-summary"])
def test_budget_error_is_logged_and_reraised(
    config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
    with_summary: bool,
) -> None:
    summary = RunSummary(command="report") if with_summary else None
    logged: list[dict[str, str]] = []
    monkeypatch.setattr(
        report_helpers,
        "_log_report_cost_delta",
        lambda _config, _tracker, **kwargs: logged.append(kwargs["metadata"]),
    )

    def exceed_budget(**_kwargs) -> str:
        raise BudgetExceededError(0.61, 0.5)

    metadata = {"workflow": "report"}
    with pytest.raises(BudgetExceededError):
        report_helpers._run_accordion_report_with_budget_log(
            topic="ai",
            config=config,
            scope="topic",
            channel_name=None,
            test=False,
            tracker=CostTracker(),
            focus=None,
            summary=summary,
            start_entry_count=0,
            start_gemini_queries=0,
            metadata=metadata,
            run_accordion_research=exceed_budget,
        )

    assert logged == [metadata]
    if summary is not None:
        assert summary.issue_count == 1
        assert summary.issues[0].stage == "report-budget"
