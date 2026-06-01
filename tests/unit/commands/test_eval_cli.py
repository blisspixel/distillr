"""CLI test for `distill eval` (model cost x quality sweep), everything mocked."""

import pytest
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.config import DistillConfig
from distill.eval.harness import EvalRow
from distill.eval.scoring import QualityScore

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    return config


def _rows():
    def row(model, comp, cost):
        return EvalRow(
            workload="paper",
            fixture_id="paper-tkg",
            model=model,
            quality=QualityScore(dimensions=[], deterministic=comp, judge=None, composite=comp),
            cost=cost,
            input_tokens=0,
            output_tokens=0,
        )

    return [row("grok-4.3", 0.95, 0.03), row("qwen3.5:27b", 0.90, 0.0)]


def test_eval_runs_and_recommends(mock_config, monkeypatch):
    import distill.eval as eval_pkg

    monkeypatch.setattr(eval_pkg, "run_model_eval", lambda *a, **k: _rows())

    result = runner.invoke(
        cli.app,
        ["eval", "--workload", "paper", "--models", "grok-4.3,qwen3.5:27b", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert "Model eval" in result.output
    assert "recommended" in result.output.lower()
    assert "qwen3.5:27b" in result.output


def test_eval_writes_report_artifact(mock_config, monkeypatch):
    import distill.eval as eval_pkg

    monkeypatch.setattr(eval_pkg, "run_model_eval", lambda *a, **k: _rows())

    result = runner.invoke(
        cli.app,
        ["eval", "--workload", "paper", "--models", "grok-4.3,qwen3.5:27b", "--yes", "--report"],
    )
    assert result.exit_code == 0, result.output
    reports = list((mock_config.library_dir / ".distill" / "eval").glob("paper_*.md"))
    assert len(reports) == 1
    assert "Recommended" in reports[0].read_text(encoding="utf-8")


def test_eval_rejects_unknown_workload(mock_config):
    result = runner.invoke(cli.app, ["eval", "--workload", "bogus", "--yes"])
    assert result.exit_code == 1
    assert "Unknown --workload" in result.output
