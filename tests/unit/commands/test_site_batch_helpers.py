"""Tests for site-batch helper boundaries."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from distill.commands import _site_batch
from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SiteSeed
from distill.llm.cost_policy import CostPolicyError
from distill.llm.errors import ProviderBusyTimeoutError
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.summary import BatchProgress, RunSummary


def _config(tmp_path):
    return DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "lib")


def test_site_batch_plan_boundary_defaults_to_same_host():
    seed = SiteSeed(
        url="https://example.com/docs/start",
        topic="web",
        discover_crawl=True,
        max_depth=1,
        max_pages=4,
    )

    row = _site_batch.site_batch_plan_rows([seed])[0]

    assert row.mode == "shallow-crawl"
    assert row.boundary == "same-host"


def test_site_batch_plan_estimate_counts_each_site_and_topic_tails(monkeypatch):
    captured = {}
    seeds = [
        SiteSeed(url="https://a.example", topic="web", max_pages=2),
        SiteSeed(url="https://b.example", topic="web", max_pages=3),
    ]

    def estimate(page_count, **kwargs):
        captured.update({"page_count": page_count, **kwargs})
        return 1.0

    monkeypatch.setattr(_site_batch, "estimate_site_batch_workflow_cost", estimate)

    assert _site_batch.estimate_site_batch_plan_cost(seeds) == 1.0
    assert captured["page_count"] == 5
    assert captured["synthesis_calls"] == 4


def test_process_site_batch_seed_budget_exceeded_is_hard_stop(tmp_path):
    seed = SiteSeed(url="https://example.com/docs/start", topic="web")
    summary = RunSummary(command="site-batch")
    progress = BatchProgress("site", 1, CostTracker())

    def process_site_seed(*args, **kwargs):
        raise BudgetExceededError(0.6, 0.5)

    with pytest.raises(BudgetExceededError):
        _site_batch.process_site_batch_seed(
            seed,
            config=_config(tmp_path),
            tracker=CostTracker(),
            summary=summary,
            progress=progress,
            scrape_only=False,
            ingest_attachments=False,
            process_site_seed=process_site_seed,
        )


def test_run_site_batch_syntheses_records_outputs(tmp_path, monkeypatch):
    config = _config(tmp_path)
    summary = RunSummary(command="site-batch")
    topic_output = tmp_path / "topic_synthesis.md"
    corpus_output = tmp_path / "corpus_synthesis.md"
    topic_output.write_text("# Topic", encoding="utf-8")
    corpus_output.write_text("# Corpus", encoding="utf-8")
    outputs = iter([topic_output, corpus_output])

    monkeypatch.setattr(_site_batch, "synthesize_site_topic", lambda *args, **kwargs: True)
    monkeypatch.setattr(_site_batch, "synthesize_corpus", lambda *args, **kwargs: True)
    monkeypatch.setattr(_site_batch, "find_artifact", lambda *args, **kwargs: next(outputs))

    _site_batch.run_site_batch_syntheses("web", config, CostTracker(), summary)

    assert summary.output_files == [topic_output.resolve(), corpus_output.resolve()]


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(BudgetExceededError(0.6, 0.5), id="budget"),
        pytest.param(CostPolicyError("route blocked"), id="cost-policy"),
        pytest.param(
            ProviderBusyTimeoutError(
                provider="ollama",
                requested_model="qwen3.5:27b",
                active_models=("other:latest",),
                timeout_seconds=1,
            ),
            id="provider-busy",
        ),
    ],
)
def test_run_site_batch_syntheses_operational_failure_stops_tail(tmp_path, monkeypatch, error):
    config = _config(tmp_path)
    summary = RunSummary(command="site-batch")
    corpus_synthesis = MagicMock()

    def raise_operational(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(_site_batch, "synthesize_site_topic", raise_operational)
    monkeypatch.setattr(_site_batch, "synthesize_corpus", corpus_synthesis)

    with pytest.raises(type(error)):
        _site_batch.run_site_batch_syntheses("web", config, CostTracker(), summary)

    corpus_synthesis.assert_not_called()
    assert summary.issues == []


def test_run_site_batch_syntheses_records_failure(tmp_path, monkeypatch):
    config = _config(tmp_path)
    summary = RunSummary(command="site-batch")

    monkeypatch.setattr(
        _site_batch,
        "synthesize_site_topic",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthesis exploded")),
    )

    _site_batch.run_site_batch_syntheses("web", config, CostTracker(), summary)

    issues = [issue for issue in summary.issues if issue.stage == "site-topic-synthesis"]
    assert len(issues) == 1
    assert issues[0].context == "web"
