"""CLI test for `distill eval` (model cost x quality sweep), everything mocked."""

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import eval as _eval
from distill.config import DistillConfig
from distill.eval.harness import EvalRow
from distill.eval.scoring import QualityScore

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_eval, "get_config", lambda: config)
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

    return [row("grok-4.6", 0.95, 0.06, None), row("qwen3.5:27b", 0.91, 0.0, 0.6)]


def _patch_eval(monkeypatch):
    import distill.eval as eval_pkg

    monkeypatch.setattr(eval_pkg, "run_model_eval", lambda *a, **k: _rows())


def test_eval_runs_and_recommends(mock_config, monkeypatch):
    _patch_eval(monkeypatch)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "grok-4.6,qwen3.5:27b", "--yes"]
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
            "grok-4.6",
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
            "grok-4.6,qwen3.5:27b",
            "--judge",
            "grok-4.6",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "shares the anchor's family" in result.output


def _mock_gpu_24gb(monkeypatch):
    from distill.doctor import hardware

    profile = hardware.HardwareProfile(
        gpu_type="nvidia",
        gpu_name="NVIDIA 24GB Test GPU",
        vram_gb=24.0,
        system_ram_gb=64.0,
        is_container=False,
    )
    monkeypatch.setattr(hardware, "detect_hardware", lambda: profile)
    monkeypatch.setattr(_eval, "_ollama_model_sizes", lambda: {"huge:70b": 40.0})


def test_eval_skips_local_model_that_exceeds_vram(mock_config, monkeypatch):
    _mock_gpu_24gb(monkeypatch)
    captured = {}
    import distill.eval as eval_pkg

    def fake_run(workload, models, **k):
        captured["models"] = list(models)
        return _rows()

    monkeypatch.setattr(eval_pkg, "run_model_eval", fake_run)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "grok-4.6,huge:70b", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "exceeds your 24GB VRAM" in result.output
    assert "huge:70b" not in captured["models"]  # skipped — would spill to CPU
    assert "grok-4.6" in captured["models"]


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
            "grok-4.6,huge:70b",
            "--allow-oversized",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "huge:70b" in captured["models"]  # forced in


def _mock_no_gpu(monkeypatch):
    from distill.doctor import hardware

    profile = hardware.HardwareProfile(
        gpu_type="none", gpu_name="", vram_gb=0.0, system_ram_gb=16.0, is_container=False
    )
    monkeypatch.setattr(hardware, "detect_hardware", lambda: profile)


def test_eval_notes_cpu_when_no_gpu_and_local_requested(mock_config, monkeypatch):
    _mock_no_gpu(monkeypatch)
    _patch_eval(monkeypatch)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "grok-4.6,qwen3.5:27b", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "run on CPU" in result.output  # local requested, no GPU -> informed, not blocked


def test_eval_no_cpu_note_when_cloud_only(mock_config, monkeypatch):
    _mock_no_gpu(monkeypatch)
    _patch_eval(monkeypatch)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "grok-4.6", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert "run on CPU" not in result.output  # cloud-only is unaffected by GPU absence


def test_ollama_sizing_does_not_probe_untrusted_remote_endpoint(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://hosted.example/v1")

    def forbidden_provider():
        pytest.fail("untrusted remote endpoint must not be probed for local model sizing")

    monkeypatch.setattr(
        "distill.llm.providers.ollama.OllamaProvider",
        forbidden_provider,
    )

    assert _eval._ollama_model_sizes() == {}


def test_eval_local_only_works_without_cloud_key(tmp_path, monkeypatch):
    # No XAI key: a local-only user can still run the eval. But with only the two
    # local models under test and nothing else configured, there is no neutral
    # judge (the anchor's family can't grade its own replacement, and a candidate
    # can't grade itself) -> judge "auto" resolves to none, and the run fails
    # closed on migrations. The eval still runs; it just won't certify a switch.
    config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_eval, "get_config", lambda: config)
    _mock_no_gpu(monkeypatch)
    monkeypatch.setattr(_eval, "_best_local_model", lambda: "gemma4:26b")
    import distill.eval as eval_pkg

    captured = {}

    def fake_run(workload, models, *, anchor, judge_model, **k):
        captured.update(models=list(models), anchor=anchor, judge=judge_model)
        return _rows()

    monkeypatch.setattr(eval_pkg, "run_model_eval", fake_run)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "qwen3.5:27b,gemma4:26b", "--yes"]
    )
    assert result.exit_code == 0, result.output  # no XAI key required
    assert captured["anchor"] == "qwen3.5:27b"  # first listed model is the reference
    # Both candidates are local and under test; neither can impartially judge.
    assert captured["judge"] == ""  # no neutral judge -> fail closed on migrations
    assert "No neutral judge available" in result.output


def test_eval_auto_judge_picks_cross_family_local_non_candidate(tmp_path, monkeypatch):
    # A different-family local model that is NOT under test is a valid neutral judge.
    config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_eval, "get_config", lambda: config)
    _mock_no_gpu(monkeypatch)
    monkeypatch.setattr(_eval, "_best_local_model", lambda: "llama4:70b")
    import distill.eval as eval_pkg

    captured = {}

    def fake_run(workload, models, *, anchor, judge_model, **k):
        captured.update(anchor=anchor, judge=judge_model)
        return _rows()

    monkeypatch.setattr(eval_pkg, "run_model_eval", fake_run)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "qwen3.5:27b,gemma4:26b", "--yes"]
    )
    assert result.exit_code == 0, result.output
    # llama4 is a different family from the qwen anchor and isn't a candidate.
    assert captured["judge"] == "llama4:70b"


def test_eval_rejects_unknown_workload(mock_config):
    result = runner.invoke(cli.app, ["eval", "--workload", "bogus", "--yes"])
    assert result.exit_code == 1
    assert "Unknown --workload" in result.output


def test_eval_auto_models_defaults_to_cloud(mock_config, monkeypatch):
    # No --models: with an XAI key the default resolves to grok-4.6.
    _patch_eval(monkeypatch)
    captured = {}
    import distill.eval as eval_pkg

    def fake_run(workload, models, **k):
        captured["models"] = list(models)
        return _rows()

    monkeypatch.setattr(eval_pkg, "run_model_eval", fake_run)
    result = runner.invoke(cli.app, ["eval", "--workload", "paper", "--yes"])
    assert result.exit_code == 0, result.output
    assert "grok-4.6" in captured["models"]


def test_eval_no_models_available_errors(tmp_path, monkeypatch):
    # No XAI key and no installed local model -> nothing to eval.
    config = DistillConfig(xai_api_key="", distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(_eval, "get_config", lambda: config)
    monkeypatch.setattr(_eval, "_best_local_model", lambda: None)
    result = runner.invoke(cli.app, ["eval", "--workload", "paper", "--yes"])
    assert result.exit_code == 1
    assert "No models to eval" in result.output


def test_eval_auto_judge_picks_cross_family_cloud(mock_config, monkeypatch):
    # Anchor is a gemini model; the neutral auto-judge is the cross-family grok.
    import distill.eval as eval_pkg

    captured = {}

    def fake_run(workload, models, *, anchor, judge_model, **k):
        captured.update(anchor=anchor, judge=judge_model)
        return _rows()

    monkeypatch.setattr(eval_pkg, "run_model_eval", fake_run)
    result = runner.invoke(
        cli.app,
        [
            "eval",
            "--workload",
            "paper",
            "--models",
            "gemini-3.6-flash",
            "--anchor",
            "gemini-3.6-flash",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["judge"] == "grok-4.6"


def test_eval_errors_when_no_fixtures(mock_config, monkeypatch):
    import distill.eval as eval_pkg

    monkeypatch.setattr(eval_pkg, "load_fixtures", lambda _w: [])
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "grok-4.6", "--yes"]
    )
    assert result.exit_code == 1
    assert "No fixtures" in result.output


def test_eval_unpriced_route_human(mock_config, monkeypatch):
    import distill.eval as eval_pkg
    from distill.eval import UnpricedEvalRouteError

    def _raise(*_a, **_k):
        raise UnpricedEvalRouteError("no price for route")

    monkeypatch.setattr(eval_pkg, "estimate_eval_cost", _raise)
    result = runner.invoke(
        cli.app, ["eval", "--workload", "paper", "--models", "grok-4.6", "--yes"]
    )
    assert result.exit_code == 3
    assert "no price for route" in result.output


def test_eval_unpriced_route_json(mock_config, monkeypatch):
    import json

    import distill.eval as eval_pkg
    from distill.eval import UnpricedEvalRouteError

    def _raise(*_a, **_k):
        raise UnpricedEvalRouteError("no price for route")

    monkeypatch.setattr(eval_pkg, "estimate_eval_cost", _raise)
    result = runner.invoke(
        cli.app, ["--json", "eval", "--workload", "paper", "--models", "grok-4.6", "--yes"]
    )
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "external_cost_unavailable"


def test_eval_aborts_when_confirm_declined(mock_config, monkeypatch):
    _patch_eval(monkeypatch)
    monkeypatch.setattr(_eval, "_tty_confirm", lambda *_a, **_k: False)
    result = runner.invoke(cli.app, ["eval", "--workload", "paper", "--models", "grok-4.6"])
    assert result.exit_code == 0
    assert "Aborted" in result.output


def test_best_local_model_none_when_no_sizes(monkeypatch):
    monkeypatch.setattr(_eval, "_ollama_model_sizes", lambda: {})
    assert _eval._best_local_model() is None


def test_ollama_model_sizes_reads_local_inventory(monkeypatch):
    class _FakeOllama:
        async def list_models(self):
            return [{"name": "qwen3.5:27b", "size": 2e9}, {"name": "", "size": 1}]

    monkeypatch.setattr("distill.llm.providers.ollama.OllamaProvider", lambda: _FakeOllama())
    sizes = _eval._ollama_model_sizes()
    assert sizes == {"qwen3.5:27b": 2.0}  # blank-name entry filtered out


def test_ollama_model_sizes_swallows_probe_failure(monkeypatch):
    def _raise():
        raise ConnectionError("ollama down")

    monkeypatch.setattr("distill.llm.providers.ollama.OllamaProvider", _raise)
    assert _eval._ollama_model_sizes() == {}


def test_eval_refuses_projected_spend_before_model_run(mock_config, monkeypatch):
    import distill.eval as eval_pkg
    from distill.pipeline.costs import ProjectedBudgetExceededError

    mock_config.distill_cost_workflow_budgets = "eval=0.05"
    monkeypatch.setattr(eval_pkg, "estimate_eval_cost", lambda *a, **k: 0.12)
    called = {"run": False}

    def fake_run(*_args, **_kwargs):
        called["run"] = True
        return _rows()

    monkeypatch.setattr(eval_pkg, "run_model_eval", fake_run)

    with pytest.raises(ProjectedBudgetExceededError) as raised:
        runner.invoke(
            cli.app,
            ["eval", "--workload", "paper", "--models", "grok-4.6", "--yes"],
            catch_exceptions=False,
        )

    assert raised.value.projected == 0.12
    assert called["run"] is False
