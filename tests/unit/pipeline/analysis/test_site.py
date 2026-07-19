"""Tests for distill.site_analysis."""

import json
from unittest.mock import patch

from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SitePage
from distill.library.insights import insight_content_sha256
from distill.library.paths import find_artifact, strip_frontmatter
from distill.llm.router import LLM_Response
from distill.pipeline.analysis.site import (
    analyze_site_page,
    synthesize_site,
    synthesize_site_topic,
)
from distill.pipeline.costs import CostTracker
from distill.pipeline.synthesis.topic import synthesize_topic


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


def test_analyze_site_page_allows_no_tracker(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    with patch("distill.pipeline.analysis.site.llm_call", _fake_llm_call("site body")):
        result = analyze_site_page(_page(), config)

    assert result.rstrip().endswith("site body")


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


def test_synthesize_site_skips_non_page_dirs_and_missing_insights(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    pages_dir = config.site_pages_dir("web", "example.com")
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "not-a-page.md").write_text("ignored", encoding="utf-8")
    (pages_dir / "empty-page").mkdir()

    assert synthesize_site("web", "example.com", config) == ""


def test_synthesize_site_records_tracker_and_refuses_strict_verify(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    page_dir = config.site_page_dir("web", "example.com", "Agent Overview", "page1")
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    with (
        patch("distill.pipeline.analysis.site.llm_call", _fake_llm_call("site synthesis")),
        patch("distill.pipeline.verify.run_synthesis_verify", return_value=True),
    ):
        result = synthesize_site("web", "example.com", config, tracker=tracker)

    assert result == ""
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "site_synthesis"
    output = find_artifact(
        config.site_dir("web", "example.com"),
        "site_synthesis",
        identity="web_example.com",
    )
    assert not output.exists()


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
    output = find_artifact(config.topic_dir("web"), "site_synthesis", identity="web")
    assert output.name == "web_Site_Synthesis.md"
    assert strip_frontmatter(output.read_text(encoding="utf-8")) == "topic synthesis"


def test_synthesize_site_topic_skips_non_site_dirs_and_missing_syntheses(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    sites_dir = config.sites_dir("web")
    sites_dir.mkdir(parents=True, exist_ok=True)
    (sites_dir / "not-a-site.md").write_text("ignored", encoding="utf-8")
    config.site_dir("web", "example.com").mkdir(parents=True, exist_ok=True)

    assert synthesize_site_topic("web", config) == ""


def test_synthesize_site_topic_records_tracker_and_refuses_strict_verify(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    site_dir = config.site_dir("web", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("# Site synthesis", encoding="utf-8")

    with (
        patch("distill.pipeline.analysis.site.llm_call", _fake_llm_call("topic synthesis")),
        patch("distill.pipeline.verify.run_synthesis_verify", return_value=True),
    ):
        result = synthesize_site_topic("web", config, tracker=tracker)

    assert result == ""
    assert len(tracker.entries) == 1
    assert tracker.entries[0].call_type == "site_topic_synthesis"
    output = find_artifact(config.topic_dir("web"), "site_synthesis", identity="web")
    assert not output.exists()


def test_synthesize_site_topic_returns_empty_without_sites(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    assert synthesize_site_topic("web", config) == ""


def test_synthesize_site_writes_verify_sidecar(tmp_path):
    """0.13.1: site synthesis is verified against its per-page insights."""
    config = DistillConfig(
        xai_api_key="test-key",
        distill_output_dir=tmp_path / "lib",
        distill_verify="warn",
    )
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
    output = find_artifact(
        config.site_dir("web", "example.com"),
        "site_synthesis",
        identity="web_example_com",
    )
    assert data["insight"] == output.name
    assert data["insight_sha256"] == insight_content_sha256(output.read_text(encoding="utf-8"))


def test_synthesize_site_topic_writes_verify_sidecar(tmp_path):
    """Site-topic synthesis has a receipt distinct from video topic synthesis."""
    config = DistillConfig(
        xai_api_key="test-key",
        distill_output_dir=tmp_path / "lib",
        distill_verify="warn",
    )
    site_dir = config.site_dir("web", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("Site synthesis, baseline 20.", encoding="utf-8")

    with patch(
        "distill.pipeline.analysis.site.llm_call",
        _fake_llm_call("Topic synthesis asserts 73.3, unsupported."),
    ):
        result = synthesize_site_topic("web", config)

    assert result
    sidecar = config.topic_dir("web") / "web_site_topic_synthesis_Verify.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert any(c["token"] == "73.3" for c in data["unsupported"])
    output = find_artifact(config.topic_dir("web"), "site_synthesis", identity="web")
    assert data["insight"] == output.name
    assert data["insight_sha256"] == insight_content_sha256(output.read_text(encoding="utf-8"))


def test_site_and_video_topic_syntheses_coexist_with_distinct_receipts(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    topic = "mixed"
    for channel, body in (("one", "Channel one."), ("two", "Channel two.")):
        channel_dir = config.channel_dir(topic, channel)
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "synthesis.md").write_text(body, encoding="utf-8")
    site_dir = config.site_dir(topic, "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("Site evidence.", encoding="utf-8")

    with patch(
        "distill.pipeline.synthesis.topic.llm_call",
        _fake_llm_call("VIDEO_TOPIC_SYNTHESIS"),
    ):
        assert synthesize_topic(topic, config) == "VIDEO_TOPIC_SYNTHESIS"
    with patch(
        "distill.pipeline.analysis.site.llm_call",
        _fake_llm_call("SITE_TOPIC_SYNTHESIS"),
    ):
        assert synthesize_site_topic(topic, config) == "SITE_TOPIC_SYNTHESIS"

    video_output = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
    site_output = find_artifact(config.topic_dir(topic), "site_synthesis", identity=topic)
    assert video_output != site_output
    assert strip_frontmatter(video_output.read_text(encoding="utf-8")) == "VIDEO_TOPIC_SYNTHESIS"
    assert strip_frontmatter(site_output.read_text(encoding="utf-8")) == "SITE_TOPIC_SYNTHESIS"
    assert (config.topic_dir(topic) / "mixed_topic_synthesis_Verify.json").exists()
    assert (config.topic_dir(topic) / "mixed_site_topic_synthesis_Verify.json").exists()
