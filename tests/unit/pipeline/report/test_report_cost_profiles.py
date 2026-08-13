"""Tests for profile-aware report cost projections."""

import pytest

from distill.llm.cost import deep_research_query_cost
from distill.llm.router import RouterConfig
from distill.pipeline.cost_estimates import (
    ACCORDION_GROK_ESTIMATE,
    CORPUS_REPORT_ESTIMATE,
    report_profile_estimate,
)


def test_report_generation_estimates_are_not_legacy_placeholders():
    assert ACCORDION_GROK_ESTIMATE > 0.5
    assert 0.5 < CORPUS_REPORT_ESTIMATE < 1.5


def test_corpus_report_estimate_and_no_qa_discount():
    assert report_profile_estimate("corpus-report") == CORPUS_REPORT_ESTIMATE
    assert report_profile_estimate("corpus", skip_qa=True) == pytest.approx(
        CORPUS_REPORT_ESTIMATE * 0.85
    )
    with pytest.raises(ValueError, match="research_only"):
        report_profile_estimate("corpus-report", research_only=True)


def test_local_corpus_report_estimate_has_no_incremental_api_cost():
    router = RouterConfig(provider="ollama", model="qwen3:8b", cost_mode="no-metered")

    assert report_profile_estimate("corpus-report", router_config=router) == 0.0


def test_accordion_profile_estimates_research_and_writing():
    assert report_profile_estimate("accordion", research_only=True) == deep_research_query_cost()
    assert report_profile_estimate("accordion") == (
        deep_research_query_cost() + ACCORDION_GROK_ESTIMATE
    )
    assert report_profile_estimate("accordion", skip_qa=True) == pytest.approx(
        deep_research_query_cost() + ACCORDION_GROK_ESTIMATE * 0.85
    )


def test_deep_research_and_unknown_profile_estimates():
    assert report_profile_estimate("legacy") == deep_research_query_cost()
    assert report_profile_estimate("deep_research") == deep_research_query_cost()
    with pytest.raises(ValueError, match="unknown report profile"):
        report_profile_estimate("unknown")
