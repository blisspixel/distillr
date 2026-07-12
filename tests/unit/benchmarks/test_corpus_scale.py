"""Correctness tests for the deterministic corpus-scale harness."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from benchmarks.corpus_scale import (
    CORPUS_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    corpus_tree_digest,
    generated_corpus,
    run_corpus_scale,
    source_fingerprint,
)
from benchmarks.corpus_scale import runner as runner_module
from benchmarks.corpus_scale.__main__ import _parser, _result_exit_code
from benchmarks.corpus_scale.generator import load_worker_corpus
from distill.library.insights import discover_insights
from distill.library.links import check_links
from distill.pipeline.dashboard_data import dashboard_snapshot
from distill.pipeline.dedup import collect_near_duplicates
from distill.pipeline.search import search_corpus


def _sample(index: int) -> runner_module.BenchmarkSample:
    return {
        "wall_ns": index + 1,
        "cpu_ns": index + 1,
        "baseline_rss_bytes": 100,
        "peak_rss_bytes": 100 + index,
        "result_count": 1,
        "result_digest": "a" * 64,
        "worker_pid": 1000 + index,
    }


def test_same_seed_produces_identical_corpus_and_manifest_shape() -> None:
    with generated_corpus(scale=20, seed=1234) as first:
        first_manifest = first.manifest.to_dict()
        first_digest = corpus_tree_digest(first.library_root)
    with generated_corpus(scale=20, seed=1234) as second:
        second_manifest = second.manifest.to_dict()
        second_digest = corpus_tree_digest(second.library_root)

    assert first_manifest == second_manifest
    assert first_digest == second_digest
    assert first_manifest["schema_version"] == CORPUS_SCHEMA_VERSION
    assert first_manifest["source_counts"] == {"paper": 4, "site": 6, "video": 8, "x": 2}


def test_different_seed_changes_content_but_not_corpus_shape() -> None:
    with generated_corpus(scale=20, seed=1) as first:
        first_manifest = first.manifest
    with generated_corpus(scale=20, seed=2) as second:
        second_manifest = second.manifest

    assert first_manifest.digest_sha256 != second_manifest.digest_sha256
    assert first_manifest.files == second_manifest.files
    assert first_manifest.source_counts == second_manifest.source_counts
    assert first_manifest.duplicate_groups == second_manifest.duplicate_groups


def test_generated_corpus_exercises_read_surfaces_and_cleans_up() -> None:
    with generated_corpus(scale=20, seed=99) as corpus:
        workspace = corpus.workspace
        assert len(discover_insights(corpus.topic_dir)) == 20
        assert search_corpus(corpus.config, corpus.topic, "commonneedle")
        assert search_corpus(corpus.config, corpus.topic, "definitelyabsenttoken") == []

        links = check_links(corpus.library_root)
        assert links.total_links == corpus.manifest.total_links
        assert len(links.broken_links) == corpus.manifest.broken_links == 2

        duplicates = collect_near_duplicates(corpus.topic_dir)
        assert len(duplicates) == corpus.manifest.duplicate_groups == 1
        assert duplicates[0].members == 3

        dashboard = dashboard_snapshot(corpus.config)
        assert dashboard["total_videos"] == corpus.manifest.source_counts["video"]
        assert dashboard["page_count"] == corpus.manifest.source_counts["site"]
        assert dashboard["paper_count"] == corpus.manifest.source_counts["paper"]
        assert dashboard["synthesis_count"] == 1
    assert not workspace.exists()


def test_benchmark_result_is_json_serializable_stable_and_read_only(monkeypatch) -> None:
    identity = source_fingerprint()
    monkeypatch.setattr(runner_module, "source_fingerprint", lambda: identity)
    with generated_corpus(scale=20, seed=2026) as corpus:
        original_digest = corpus.manifest.digest_sha256
        result = run_corpus_scale(corpus, iterations=1, warmups=0)

        assert result["schema_version"] == RESULT_SCHEMA_VERSION
        assert result["integrity"]["unchanged"] is True
        assert result["source_integrity"]["unchanged"] is True
        assert result["execution"]["process_state"] == "fresh-child-per-sample"
        assert result["execution"]["filesystem_cache_state"] == "warm-generated"
        assert result["environment"]["source_fingerprint_sha256"]
        assert corpus_tree_digest(corpus.library_root) == original_digest
        assert json.loads(json.dumps(result))["suite"] == "corpus-scale"

        operations = {row["name"]: row for row in result["operations"]}
        assert set(operations) == {
            "check_links",
            "dashboard_snapshot",
            "discover_insights",
            "near_duplicates",
            "search_hit",
            "search_miss",
        }
        for operation in operations.values():
            assert operation["status"] == "ok", operation.get("error")
            assert operation["integrity"]["unchanged"] is True
            assert len(operation["samples"]) == 1
            assert len({sample["result_digest"] for sample in operation["samples"]}) == 1
            assert operation["summary"]["sample_count"] == 1
            assert "p95_wall_ns" not in operation["summary"]
            assert all(sample["wall_ns"] >= 0 for sample in operation["samples"])
            assert all(sample["cpu_ns"] >= 0 for sample in operation["samples"])
            assert all(sample["peak_rss_bytes"] >= 0 for sample in operation["samples"])
            assert all(sample["worker_pid"] > 0 for sample in operation["samples"])


def test_operation_result_digests_do_not_depend_on_temporary_root() -> None:
    digests: list[dict[str, str]] = []
    for _ in range(2):
        with generated_corpus(scale=20, seed=8080) as corpus:
            result = run_corpus_scale(
                corpus,
                iterations=1,
                warmups=0,
                operations=["discover_insights"],
            )
            operation = result["operations"][0]
            assert operation["status"] == "ok", operation.get("error")
            assert operation["samples"], operation.get("error")
            digests.append({operation["name"]: operation["samples"][0]["result_digest"]})

    assert digests[0] == digests[1]


def test_environment_reports_matching_source_and_installed_versions(monkeypatch) -> None:
    monkeypatch.setattr(runner_module, "source_fingerprint", lambda: ("a" * 64, 1))
    monkeypatch.setattr(runner_module, "_project_version", lambda: "1.2.3")
    monkeypatch.setattr(runner_module, "_installed_distill_version", lambda: "1.2.3")

    environment = runner_module._environment()

    assert environment["project_version"] == "1.2.3"
    assert environment["installed_distill_version"] == "1.2.3"
    assert environment["installed_distill_version_matches_project"] is True
    assert "distill_version" not in environment


def test_environment_exposes_stale_installed_distribution_version(monkeypatch) -> None:
    monkeypatch.setattr(runner_module, "source_fingerprint", lambda: ("a" * 64, 1))
    monkeypatch.setattr(runner_module, "_project_version", lambda: "1.2.4")
    monkeypatch.setattr(runner_module, "_installed_distill_version", lambda: "1.2.3")

    environment = runner_module._environment()

    assert environment["project_version"] == "1.2.4"
    assert environment["installed_distill_version"] == "1.2.3"
    assert environment["installed_distill_version_matches_project"] is False
    assert "distill_version" not in environment


def test_recorded_samples_use_distinct_fresh_worker_processes() -> None:
    with generated_corpus(scale=2, seed=90) as corpus:
        result = run_corpus_scale(
            corpus,
            iterations=2,
            warmups=0,
            operations=["discover_insights"],
        )

    samples = result["operations"][0]["samples"]
    assert len(samples) == 2
    assert len({sample["worker_pid"] for sample in samples}) == 2
    assert len({sample["result_digest"] for sample in samples}) == 1


def test_p95_is_suppressed_until_twenty_successful_samples() -> None:
    summary_19 = runner_module._summary([_sample(index) for index in range(19)])
    summary_20 = runner_module._summary([_sample(index) for index in range(20)])

    assert summary_19["sample_count"] == 19
    assert "p95_wall_ns" not in summary_19
    assert summary_20["sample_count"] == 20
    assert summary_20["p95_wall_ns"] == 19


def test_worker_rejects_missing_marker_and_wrong_token(tmp_path: Path) -> None:
    unmarked = tmp_path / "unmarked"
    (unmarked / "library").mkdir(parents=True)
    with pytest.raises(ValueError, match="disposable benchmark marker"):
        load_worker_corpus(unmarked, "token")

    with generated_corpus(scale=1, seed=4) as corpus:
        with pytest.raises(ValueError, match="worker token"):
            load_worker_corpus(corpus.workspace, "wrong-token")
        loaded = load_worker_corpus(corpus.workspace, corpus.worker_token)
        assert loaded.manifest == corpus.manifest
        assert loaded.library_root == corpus.library_root.resolve()


def test_source_fingerprint_includes_uncommitted_source_changes(tmp_path: Path) -> None:
    product = tmp_path / "distill" / "feature.py"
    harness = tmp_path / "benchmarks" / "corpus_scale" / "runner.py"
    product.parent.mkdir(parents=True)
    harness.parent.mkdir(parents=True)
    product.write_text("VALUE = 1\n", encoding="utf-8")
    harness.write_text("RUNNER = 1\n", encoding="utf-8")

    first, first_count = source_fingerprint(tmp_path)
    product.write_text("VALUE = 2\n", encoding="utf-8")
    second, second_count = source_fingerprint(tmp_path)

    assert first != second
    assert first_count == second_count == 2


def test_worker_timeout_invalidates_operation_without_partial_summary(monkeypatch) -> None:
    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="worker", timeout=0.01)

    monkeypatch.setattr(runner_module.subprocess, "run", time_out)
    with generated_corpus(scale=1, seed=8) as corpus:
        result = run_corpus_scale(
            corpus,
            iterations=1,
            warmups=0,
            operations=["discover_insights"],
            timeout_seconds=0.01,
        )

    operation = result["operations"][0]
    assert operation["status"] == "error"
    assert operation["samples"] == []
    assert operation["summary"] == {}
    error = operation.get("error")
    assert error is not None
    assert error["type"] == "WorkerTimeout"
    assert _result_exit_code(result) == 1


def test_worker_crash_invalidates_operation(monkeypatch) -> None:
    def crash(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["python"],
            returncode=9,
            stdout=json.dumps(
                {
                    "schema_version": runner_module.WORKER_RESULT_SCHEMA_VERSION,
                    "operation": "discover_insights",
                    "status": "ok",
                    "sample": _sample(1),
                }
            ),
            stderr="worker crashed",
        )

    monkeypatch.setattr(runner_module.subprocess, "run", crash)
    with generated_corpus(scale=1, seed=9) as corpus:
        result = run_corpus_scale(
            corpus,
            iterations=1,
            warmups=0,
            operations=["discover_insights"],
        )

    operation = result["operations"][0]
    assert operation["status"] == "error"
    assert operation.get("error") == {
        "type": "WorkerCrash",
        "message": "discover_insights worker exited with code 9",
    }
    assert _result_exit_code(result) == 1


def test_different_worker_results_invalidate_all_samples(monkeypatch) -> None:
    samples = [_sample(1), {**_sample(2), "result_digest": "b" * 64}]
    monkeypatch.setattr(
        runner_module,
        "_run_worker_sample",
        lambda *args, **kwargs: samples.pop(0),
    )
    with generated_corpus(scale=1, seed=10) as corpus:
        result = run_corpus_scale(
            corpus,
            iterations=2,
            warmups=0,
            operations=["discover_insights"],
        )

    operation = result["operations"][0]
    assert operation["status"] == "error"
    assert operation["summary"] == {}
    error = operation.get("error")
    assert error is not None
    assert error["type"] == "ResultDigestMismatch"
    assert _result_exit_code(result) == 1


def test_measure_stops_sampler_and_preserves_operation_error(monkeypatch) -> None:
    class Sampler:
        baseline = 1
        started = False
        stopped = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> int:
            self.stopped = True
            return 2

    sampler = Sampler()
    monkeypatch.setattr(runner_module, "_PeakRssSampler", lambda: sampler)

    def fail() -> tuple[object, int]:
        raise RuntimeError("original failure")

    with pytest.raises(RuntimeError, match="original failure"):
        runner_module.measure_operation(fail)

    assert sampler.started is True
    assert sampler.stopped is True


def test_benchmark_exit_code_tracks_correctness_not_timing(monkeypatch) -> None:
    identity = source_fingerprint()
    monkeypatch.setattr(runner_module, "source_fingerprint", lambda: identity)
    with generated_corpus(scale=2, seed=17) as corpus:
        result = run_corpus_scale(
            corpus,
            iterations=1,
            warmups=0,
            operations=["discover_insights"],
        )

    assert _result_exit_code(result) == 0
    result["operations"][0]["status"] = "error"
    assert _result_exit_code(result) == 1
    result["operations"][0]["status"] = "ok"
    result["integrity"]["unchanged"] = False
    assert _result_exit_code(result) == 1
    result["integrity"]["unchanged"] = True
    result["source_integrity"]["unchanged"] = False
    assert _result_exit_code(result) == 1


def test_cli_selects_operations_and_timeout() -> None:
    args = _parser().parse_args(
        [
            "--operation",
            "search_hit",
            "--operation",
            "check_links",
            "--timeout-seconds",
            "12.5",
        ]
    )

    assert args.operation == ["search_hit", "check_links"]
    assert args.timeout_seconds == 12.5


@pytest.mark.parametrize(
    ("scale", "iterations", "warmups", "timeout_seconds"),
    [(0, 1, 0, 1.0), (1, 0, 0, 1.0), (1, 1, -1, 1.0), (1, 1, 0, 0.0)],
)
def test_invalid_generation_and_run_controls_are_rejected(
    scale: int, iterations: int, warmups: int, timeout_seconds: float
) -> None:
    if scale == 0:
        with pytest.raises(ValueError, match="scale"), generated_corpus(scale=scale):
            pass
        return
    with generated_corpus(scale=scale) as corpus, pytest.raises(ValueError):
        run_corpus_scale(
            corpus,
            iterations=iterations,
            warmups=warmups,
            timeout_seconds=timeout_seconds,
        )
