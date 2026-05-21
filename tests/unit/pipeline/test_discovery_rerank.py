"""Tests for curated-seed retention in distill.pipeline.discovery.discover_rerank."""

import json
from unittest.mock import patch

from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SiteSeed
from distill.llm.router import LLM_Response
from distill.pipeline.discovery import discover_rerank


def _llm_returning(payload: dict):
    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(
            text=json.dumps(payload), input_tokens=10, output_tokens=20, model="grok-4.3"
        )

    return _call


def test_discover_rerank_retains_curated_seeds_dropped_by_llm(tmp_path):
    """Regression: a curated seed the LLM omits from ranked_items must still be
    returned (with a floor score) so a comparison sweep cannot silently lose
    entire competitor sources."""
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    seeds = [
        SiteSeed(url="https://vendor-a.com/page", topic="t"),
        SiteSeed(url="https://vendor-b.com/page", topic="t"),
        SiteSeed(url="https://vendor-c.com/page", topic="t"),
    ]
    # The LLM ranks only the first seed, silently dropping the other two.
    payload = {
        "ranked_items": [
            {
                "kind": "site",
                "identifier": "https://vendor-a.com/page",
                "final_score": 0.91,
                "goal_fit": 0.9,
                "depth_score": 0.9,
                "complementarity_score": 0.9,
                "rationale": "directly on point",
            }
        ]
    }

    with patch("distill.pipeline.discovery.llm_call", _llm_returning(payload)):
        ranked = discover_rerank("some goal", [], [], seeds, config, None)

    by_url = {r.identifier: r for r in ranked if r.kind == "site"}
    assert set(by_url) == {
        "https://vendor-a.com/page",
        "https://vendor-b.com/page",
        "https://vendor-c.com/page",
    }
    # LLM-scored seed keeps its score; retained seeds get the floor score.
    assert by_url["https://vendor-a.com/page"].final_score == 0.91
    assert by_url["https://vendor-b.com/page"].final_score == 0.4
    assert by_url["https://vendor-c.com/page"].final_score == 0.4


def test_discover_rerank_does_not_duplicate_ranked_seeds(tmp_path):
    """A seed the LLM already ranked must not be appended a second time."""
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    seeds = [SiteSeed(url="https://vendor-a.com/page", topic="t")]
    payload = {
        "ranked_items": [
            {
                "kind": "site",
                "identifier": "https://vendor-a.com/page",
                "final_score": 0.8,
                "goal_fit": 0.8,
                "depth_score": 0.8,
                "complementarity_score": 0.8,
                "rationale": "on point",
            }
        ]
    }

    with patch("distill.pipeline.discovery.llm_call", _llm_returning(payload)):
        ranked = discover_rerank("goal", [], [], seeds, config, None)

    sites = [r for r in ranked if r.kind == "site"]
    assert len(sites) == 1
    assert sites[0].final_score == 0.8
