"""Tests for distill.site_analysis."""

import json
from unittest.mock import patch

from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SitePage
from distill.library.paths import find_artifact, strip_frontmatter
from distill.llm.router import LLM_Response
from distill.pipeline.analysis.site import (
    analyze_site_page,
    synthesize_site,
    synthesize_site_topic,
)
from distill.pipeline.costs import CostTracker


def _fake_llm_call(text: str = "body", model: str = "grok-4.3"):
    def _call(config, workload_tag, prompt, **kwargs):
        return LLM_Response(text=text, input_tokens=10, output_tokens=20, model=model)

    return _call


def _page() -> SitePage:
    return SitePage(
        url="https://example.com/agent",
        title='Agent "Overview"',
        site_name="example.com",
        page_type="article",
        text="Main content",
        description="Desc",
        has_video=True,
        transcript="Transcript text",
    )


def test_analyze_site_page_builds_frontmatter(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()

    with patch("distill.pipeline.analysis.site.llm_call", _fake_llm_call("site body")):
        result = analyze_site_page(_page(), config, tracker=tracker)

    assert 'page_title: "Agent \\"Overview\\""' in result
    assert 'site: "example.com"' in result
    assert "analyzed_by: grok-4.3" in result
    assert result.rstrip().endswith("site body")
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "site_page"


def test_synthesize_site_writes_output(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    page_dir = config.site_page_dir("web", "example.com", "Agent Overview", "page1")
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    with patch("distill.pipeline.analysis.site.llm_call", _fake_llm_call("site synthesis")):
        result = synthesize_site("web", "example.com", config)

    assert result == "site synthesis"
    output = find_artifact(
        config.site_dir("web", "example.com"),
        "site_synthesis",
        identity="web_example.com",
    )
    assert output.name == "web_example_com_Site_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "site synthesis"


def test_synthesize_site_returns_empty_without_pages(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    assert synthesize_site("web", "example.com", config) == ""


def test_synthesize_site_topic_writes_output(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    site_dir = config.site_dir("web", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("# Site synthesis", encoding="utf-8")

    with patch("distill.pipeline.analysis.site.llm_call", _fake_llm_call("topic synthesis")):
        result = synthesize_site_topic("web", config)

    assert result == "topic synthesis"
    output = find_artifact(config.topic_dir("web"), "topic_synthesis", identity="web")
    assert output.name == "web_Topic_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "topic synthesis"


def test_synthesize_site_topic_returns_empty_without_sites(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    assert synthesize_site_topic("web", config) == ""


def test_synthesize_site_writes_verify_sidecar(tmp_path):
    """0.13.1: site synthesis is verified against its per-page insights."""
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    page_dir = config.site_page_dir("web", "example.com", "Agent Overview", "page1")
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "insights.md").write_text("# Insight\nObserved 12 items.", encoding="utf-8")

    with patch(
        "distill.pipeline.analysis.site.llm_call",
        _fake_llm_call("Site synthesis cites 99.1, in no page."),
    ):
        result = synthesize_site("web", "example.com", config)

    assert result
    sidecar = config.site_dir("web", "example.com") / "web_example_com_Verify.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(c["token"] == "99.1" for c in data["unsupported"])


def test_synthesize_site_topic_writes_verify_sidecar(tmp_path):
    """0.13.1: site-topic synthesis is verified against its site syntheses; it
    shares the topic_synthesis sidecar identity with the video producer."""
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    site_dir = config.site_dir("web", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("Site synthesis, baseline 20.", encoding="utf-8")

    with patch(
        "distill.pipeline.analysis.site.llm_call",
        _fake_llm_call("Topic synthesis asserts 73.3, unsupported."),
    ):
        result = synthesize_site_topic("web", config)

    assert result
    sidecar = config.topic_dir("web") / "web_topic_synthesis_Verify.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(c["token"] == "73.3" for c in data["unsupported"])
