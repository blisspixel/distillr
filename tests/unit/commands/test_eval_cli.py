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
    def row(model, comp, cost, winrate):
        return EvalRow(
            workload="paper",
            fixture_id="paper-tkg",
            model=model,
            quality=QualityScore(dimensions=[], composite=comp),
            cost=cost,
            input_tokens=0,
            output_tokens=0,
            pairwise_winrate=winrate,
        )

    return [row("grok-4.3", 0.95, 0.03, None), row("qwen3.5:27b", 0.91, 0.0, 0.6)]


def _patch_eval(monkeypatch):
    import distill.eval as eval_pkg

    monkeypatch.setattr(eval_pkg, "run_model_eval", lambda *a, **k: _rows())


def test_eval_runs_and_recommends(mock_config, monkeypatch):
    _patch_eval(monkeypatch)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "grok-4.3,qwen3.5:27b", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "Model eval" in result.output
    assert "recommended" in result.output.lower()
    assert "qwen3.5:27b" in result.output
    # Results log always appended for drift tracking.
    log = mock_config.library_dir / ".distill" / "eval" / "results.jsonl"
    assert log.exists()
    assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_eval_adds_anchor_to_models_and_writes_report(mock_config, monkeypatch):
    _patch_eval(monkeypatch)
    result = runner.invoke(
        cli.app,
        [
            "eval",
            "--workload",
            "paper",
            "--models",
            "qwen3.5:27b",
            "--anchor",
            "grok-4.3",
            "--yes",
            "--report",
        ],
    )
    assert result.exit_code == 0, result.output
    reports = list((mock_config.library_dir / ".distill" / "eval").glob("paper_*.md"))
    assert len(reports) == 1
    assert "anchor" in reports[0].read_text(encoding="utf-8").lower()


def test_eval_warns_when_judge_shares_anchor_family(mock_config, monkeypatch):
    _patch_eval(monkeypatch)
    result = runner.invoke(
        cli.app,
        [
            "eval",
            "--workload",
            "paper",
            "--models",
            "grok-4.3,qwen3.5:27b",
            "--judge",
            "grok-4.3",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "shares the anchor's family" in result.output


def _mock_gpu_24gb(monkeypatch):
    from distill.doctor import hardware

    profile = hardware.HardwareProfile(
        gpu_type="nvidia", gpu_name="RTX 4090", vram_gb=24.0, system_ram_gb=64.0, is_container=False
    )
    monkeypatch.setattr(hardware, "detect_hardware", lambda: profile)
    monkeypatch.setattr(_cli_impl, "_ollama_model_sizes", lambda: {"huge:70b": 40.0})


def test_eval_skips_local_model_that_exceeds_vram(mock_config, monkeypatch):
    _mock_gpu_24gb(monkeypatch)
    captured = {}
    import distill.eval as eval_pkg

    def fake_run(workload, models, **k):
        captured["models"] = list(models)
        return _rows()

    monkeypatch.setattr(eval_pkg, "run_model_eval", fake_run)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "grok-4.3,huge:70b", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "exceeds your 24GB VRAM" in result.output
    assert "huge:70b" not in captured["models"]  # skipped — would spill to CPU
    assert "grok-4.3" in captured["models"]


def test_eval_allow_oversized_keeps_the_model(mock_config, monkeypatch):
    _mock_gpu_24gb(monkeypatch)
    captured = {}
    import distill.eval as eval_pkg

    def fake_run(workload, models, **k):
        captured["models"] = list(models)
        return _rows()

    monkeypatch.setattr(eval_pkg, "run_model_eval", fake_run)
    result = runner.invoke(
        cli.app,
        [
            "eval",
            "--workload",
            "paper",
            "--models",
            "grok-4.3,huge:70b",
            "--allow-oversized",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "huge:70b" in captured["models"]  # forced in


def test_eval_rejects_unknown_workload(mock_config):
    result = runner.invoke(cli.app, ["eval", "--workload", "bogus", "--yes"])
    assert result.exit_code == 1
    assert "Unknown --workload" in result.output
