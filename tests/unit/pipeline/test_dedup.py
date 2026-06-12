"""Tests for near-duplicate insight detection (shingle Jaccard, union-find groups)."""

from __future__ import annotations

from pathlib import Path

from distill.pipeline.dedup import collect_near_duplicates, shingle_similarity

_BASE = (
    "The vendor announced a new agent runtime with checkpoint support and a "
    "pricing change effective next quarter. Early benchmarks show a thirty "
    "percent latency reduction on long-context workloads, and the migration "
    "path requires no code changes for existing deployments according to the "
    "launch blog post and the accompanying technical documentation pages."
)


def _insight(topic_dir: Path, name: str, body: str) -> None:
    d = topic_dir / "sites" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}_Insights.md").write_text(f"---\ntitle: {name}\n---\n\n{body}\n", encoding="utf-8")


class TestShingleSimilarity:
    def test_identical_is_one(self):
        assert shingle_similarity(_BASE, _BASE) == 1.0

    def test_unrelated_is_near_zero(self):
        other = (
            "Quarterly hurricane forecasts improved when ensemble members were "
            "weighted by sea-surface temperature anomalies, a meteorological "
            "result with no relation to software, runtimes, or pricing at all. "
            "The study covered four decades of Atlantic storm-track records and "
            "validated against reanalysis data from two independent archives."
        )
        assert shingle_similarity(_BASE, other) < 0.05

    def test_short_stubs_never_match(self):
        assert shingle_similarity("too short to mean anything", "too short to mean anything") == 0.0


class TestCollectNearDuplicates:
    def test_near_duplicates_grouped(self, tmp_path):
        topic = tmp_path / "t"
        # Same press release, lightly reworded tail -> high overlap.
        _insight(topic, "video-coverage", _BASE + " The host walked through the demo flow.")
        _insight(topic, "newsletter-coverage", _BASE + " The author added brief commentary.")
        _insight(
            topic,
            "unrelated",
            "Entirely different subject matter about marine biology and reef restoration "
            "methods using coral fragment seeding across twelve experimental sites with "
            "survival tracked over five years against a control lagoon, plus genetic "
            "diversity sampling from donor colonies and temperature-stress assays.",
        )

        groups = collect_near_duplicates(topic)

        assert len(groups) == 1
        assert groups[0].members == 2
        assert groups[0].similarity > 0.55
        assert all("coverage" in p for p in groups[0].paths)

    def test_transitive_grouping(self, tmp_path):
        topic = tmp_path / "t"
        _insight(topic, "a", _BASE + " extra alpha sentence one here now.")
        _insight(topic, "b", _BASE)
        _insight(topic, "c", _BASE + " different beta closing line entirely instead.")

        groups = collect_near_duplicates(topic)

        assert len(groups) == 1
        assert groups[0].members == 3

    def test_empty_and_distinct_topics(self, tmp_path):
        assert collect_near_duplicates(tmp_path / "none") == []
