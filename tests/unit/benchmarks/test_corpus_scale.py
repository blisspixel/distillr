"""Correctness tests for the deterministic corpus-scale harness."""

from __future__ import annotations

import json

import pytest

from benchmarks.corpus_scale import (
    CORPUS_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    corpus_tree_digest,
    generated_corpus,
    run_corpus_scale,
)
from benchmarks.corpus_scale import runner as runner_module
from benchmarks.corpus_scale.__main__ import _result_exit_code
from distill.library.insights import discover_insights
from distill.library.links import check_links
from distill.pipeline.dashboard_data import dashboard_snapshot
from distill.pipeline.dedup import collect_near_duplicates
from distill.pipeline.search import search_corpus


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


def test_benchmark_result_is_json_serializable_stable_and_read_only() -> None:
    with generated_corpus(scale=20, seed=2026) as corpus:
        original_digest = corpus.manifest.digest_sha256
        result = run_corpus_scale(corpus, iterations=2, warmups=0)

        assert result["schema_version"] == RESULT_SCHEMA_VERSION
        assert result["integrity"]["unchanged"] is True
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
            assert operation["status"] == "ok"
            assert operation["integrity"]["unchanged"] is True
            assert len(operation["samples"]) == 2
            assert len({sample["result_digest"] for sample in operation["samples"]}) == 1
            assert all(sample["wall_ns"] >= 0 for sample in operation["samples"])
            assert all(sample["cpu_ns"] >= 0 for sample in operation["samples"])
            assert all(sample["peak_rss_bytes"] >= 0 for sample in operation["samples"])


def test_operation_result_digests_do_not_depend_on_temporary_root() -> None:
    digests: list[dict[str, str]] = []
    for _ in range(2):
        with generated_corpus(scale=20, seed=8080) as corpus:
            result = run_corpus_scale(corpus, iterations=1, warmups=0)
            digests.append(
                {
                    operation["name"]: operation["samples"][0]["result_digest"]
                    for operation in result["operations"]
                }
            )

    assert digests[0] == digests[1]


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
        runner_module._measure(fail)

    assert sampler.started is True
    assert sampler.stopped is True


def test_benchmark_exit_code_tracks_correctness_not_timing() -> None:
    with generated_corpus(scale=2, seed=17) as corpus:
        result = run_corpus_scale(corpus, iterations=1, warmups=0)

    assert _result_exit_code(result) == 0
    result["operations"][0]["status"] = "error"
    assert _result_exit_code(result) == 1
    result["operations"][0]["status"] = "ok"
    result["integrity"]["unchanged"] = False
    assert _result_exit_code(result) == 1


@pytest.mark.parametrize(("scale", "iterations", "warmups"), [(0, 1, 0), (1, 0, 0), (1, 1, -1)])
def test_invalid_generation_and_run_controls_are_rejected(
    scale: int, iterations: int, warmups: int
) -> None:
    if scale == 0:
        with pytest.raises(ValueError, match="scale"), generated_corpus(scale=scale):
            pass
        return
    with generated_corpus(scale=scale) as corpus, pytest.raises(ValueError):
        run_corpus_scale(corpus, iterations=iterations, warmups=warmups)
