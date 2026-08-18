"""CLI surface for `distill bench`.

Feature: local-speed
"""

from __future__ import annotations

import asyncio
import json

import pytest
from typer.testing import CliRunner

from distill import cli
from distill.commands import bench as bench_mod
from distill.config import DistillConfig
from distill.pipeline.speed_probe import ModelSpeed

runner = CliRunner()


@pytest.fixture
def library(tmp_path, monkeypatch):
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    config.library_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bench_mod, "get_config", lambda: config)
    monkeypatch.setattr(bench_mod, "run_preflight", lambda: None)
    return config


def _measured(model: str, *, decode_seconds: float = 4.0) -> ModelSpeed:
    return ModelSpeed(
        model=model,
        provider="ollama",
        prefill_tokens=1024,
        prefill_seconds=8.0,
        decode_tokens=64,
        decode_seconds=decode_seconds,
        cold_load_seconds=20.0,
        num_ctx=8192,
    )


def _async_probe(fn):
    """bench awaits _probe_one, so a fake must be a coroutine function."""

    async def probe(provider: str, model: str) -> ModelSpeed:
        return fn(provider, model)

    return probe


@pytest.fixture
def one_model(monkeypatch):
    monkeypatch.setattr("distill.commands.eval._ollama_model_sizes", lambda: {"m:8b": 4.9})
    monkeypatch.setattr(
        bench_mod, "_probe_one", _async_probe(lambda provider, model: _measured(model))
    )


def test_bench_reports_rates_and_a_projected_paper_duration(library, one_model):
    result = runner.invoke(cli.app, ["bench"])

    assert result.exit_code == 0, result.output
    assert "128.0 t/s" in result.output  # 1024 prefill tokens / 8s
    assert "16.0 t/s" in result.output  # 64 decode tokens / 4s
    # 20_000/128 + 3_000/16 = 156.25 + 187.5 = 343.75s, the projected paper duration.
    assert "5m44s" in result.output


def test_bench_refuses_to_imply_it_ranks_quality(library, one_model):
    """Speed must never read as a quality verdict on the model."""
    result = runner.invoke(cli.app, ["bench"])

    assert "distill eval" in result.output


def test_bench_persists_rows_with_comparability_fields(library, one_model):
    result = runner.invoke(cli.app, ["bench"])

    assert result.exit_code == 0, result.output
    rows = [
        json.loads(line)
        for line in (library.library_dir / ".distill" / "bench" / "results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    row = rows[0]
    # Without these, two numbers cannot honestly be compared later.
    for field in ("model", "num_ctx", "provider", "schema_version"):
        assert field in row
    assert row["machine"]["gpu_type"]


def test_stored_machine_facts_carry_no_personal_identifiers(library, one_model):
    """A shared benchmark must not leak who ran it or from where."""
    runner.invoke(cli.app, ["bench"])
    text = (library.library_dir / ".distill" / "bench" / "results.jsonl").read_text(
        encoding="utf-8"
    )

    import getpass
    import platform

    assert platform.node().lower() not in text.lower()
    assert getpass.getuser().lower() not in text.lower()
    assert "C:\\Users" not in text and "/home/" not in text


def test_bench_json_mode_emits_an_envelope(library, one_model):
    result = runner.invoke(cli.app, ["bench", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    models = payload.get("data", payload).get("models", [])
    assert models and models[0]["model"] == "m:8b"


def test_bench_exits_when_no_local_model_is_available(library, monkeypatch):
    monkeypatch.setattr("distill.commands.eval._ollama_model_sizes", dict)

    result = runner.invoke(cli.app, ["bench"])

    assert result.exit_code == 1
    assert "No completion-capable local models" in result.output


def test_a_reloaded_probe_is_reported_rather_than_published(library, monkeypatch):
    """A reload during measurement is not inference time, so publish no rate."""
    monkeypatch.setattr("distill.commands.eval._ollama_model_sizes", lambda: {"m:8b": 4.9})
    polluted = ModelSpeed(
        model="m:8b",
        provider="ollama",
        prefill_tokens=1024,
        prefill_seconds=8.0,
        decode_tokens=64,
        decode_seconds=4.0,
        reloaded_during_measure=True,
    )
    monkeypatch.setattr(bench_mod, "_probe_one", _async_probe(lambda provider, model: polluted))

    result = runner.invoke(cli.app, ["bench"])

    assert result.exit_code == 0, result.output
    assert "reloaded" in result.output
    assert "128.0 t/s" not in result.output


def test_a_failed_probe_does_not_end_the_sweep(library, monkeypatch):
    monkeypatch.setattr(
        "distill.commands.eval._ollama_model_sizes", lambda: {"bad:8b": 1.0, "good:8b": 2.0}
    )

    def probe(provider: str, model: str) -> ModelSpeed:
        if model == "bad:8b":
            return ModelSpeed(model=model, provider=provider, outcome="error", error="boom")
        return _measured(model)

    monkeypatch.setattr(bench_mod, "_probe_one", _async_probe(probe))

    result = runner.invoke(cli.app, ["bench"])

    assert result.exit_code == 0, result.output
    assert "boom" in result.output
    assert "16.0 t/s" in result.output  # the healthy model still measured


class TestStoredDecodeRates:
    def test_missing_file_yields_no_rates(self, library):
        assert bench_mod.stored_decode_rates() == {}

    def test_best_rate_per_model_wins(self, library):
        path = library.library_dir / ".distill" / "bench" / "results.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    json.dumps({"model": "m:8b", "decode_tokens_per_second": 9.0}),
                    json.dumps({"model": "m:8b", "decode_tokens_per_second": 12.5}),
                ]
            ),
            encoding="utf-8",
        )

        assert bench_mod.stored_decode_rates() == {"m:8b": 12.5}

    def test_malformed_and_unusable_rows_are_skipped(self, library):
        path = library.library_dir / ".distill" / "bench" / "results.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "not-json",
                    "[1, 2]",
                    json.dumps({"model": "", "decode_tokens_per_second": 5.0}),
                    json.dumps({"model": "z:8b", "decode_tokens_per_second": 0}),
                    json.dumps({"model": "z:8b", "decode_tokens_per_second": True}),
                    json.dumps({"model": "ok:8b", "decode_tokens_per_second": 7.5}),
                ]
            ),
            encoding="utf-8",
        )

        assert bench_mod.stored_decode_rates() == {"ok:8b": 7.5}


class TestProbeExecution:
    """The probe drives the real provider; both calls must match in shape."""

    @staticmethod
    def _provider(calls: list[dict[str, object]], *, fail: bool = False):
        from distill.llm.types import LLM_Response

        class _Provider:
            @staticmethod
            async def call(model: str, prompt: str, **kwargs: object) -> LLM_Response:
                if fail:
                    raise RuntimeError("ollama unreachable")
                calls.append({"model": model, "prompt": prompt, **kwargs})
                return LLM_Response(
                    text="x",
                    input_tokens=1024,
                    output_tokens=64,
                    model=model,
                    load_seconds=20.0 if len(calls) == 1 else 0.2,
                    prefill_seconds=8.0,
                    decode_seconds=4.0,
                    num_ctx=8192,
                )

        return _Provider

    def test_warmup_and_measure_use_an_identical_prompt_size(self, monkeypatch):
        """Differing sizes would resize the context and force a weight reload."""
        calls: list[dict[str, object]] = []
        monkeypatch.setattr("distill.llm.providers.ollama.OllamaProvider", self._provider(calls))

        speed = asyncio.run(bench_mod._probe_one("ollama", "m:8b"))

        assert len(calls) == 2
        assert len(str(calls[0]["prompt"])) == len(str(calls[1]["prompt"]))
        assert calls[0]["max_tokens"] == calls[1]["max_tokens"]
        # Cold load comes from the warm-up; rates from the warm measured call.
        assert speed.cold_load_seconds == 20.0
        assert speed.usable is True

    def test_the_probe_defeats_the_prefix_cache_between_calls(self, monkeypatch):
        calls: list[dict[str, object]] = []
        monkeypatch.setattr("distill.llm.providers.ollama.OllamaProvider", self._provider(calls))

        asyncio.run(bench_mod._probe_one("ollama", "m:8b"))

        assert calls[0]["prompt"] != calls[1]["prompt"]

    def test_a_provider_failure_becomes_a_recorded_error_not_a_crash(self, monkeypatch):
        monkeypatch.setattr(
            "distill.llm.providers.ollama.OllamaProvider", self._provider([], fail=True)
        )

        speed = asyncio.run(bench_mod._probe_one("ollama", "m:8b"))

        assert speed.outcome == "error"
        assert "unreachable" in speed.error
        assert speed.usable is False


class TestStoredRatesDegradeSafely:
    """Reading history must never raise into a caller that only wants a hint."""

    def test_unreadable_config_yields_no_rates(self, monkeypatch):
        def boom() -> None:
            raise RuntimeError("no config")

        monkeypatch.setattr(bench_mod, "get_config", boom)

        assert bench_mod.stored_decode_rates() == {}

    def test_an_unreadable_results_file_yields_no_rates(self, library, monkeypatch):
        path = library.library_dir / ".distill" / "bench" / "results.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

        def deny(*args: object, **kwargs: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr("pathlib.Path.open", deny)

        assert bench_mod.stored_decode_rates() == {}

    def test_an_oversized_row_is_skipped_not_fatal(self, library):
        path = library.library_dir / ".distill" / "bench" / "results.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        huge = json.dumps({"model": "x" * 70_000, "decode_tokens_per_second": 5.0})
        path.write_text(
            huge + "\n" + json.dumps({"model": "ok:8b", "decode_tokens_per_second": 3.0}),
            encoding="utf-8",
        )

        assert bench_mod.stored_decode_rates() == {"ok:8b": 3.0}
