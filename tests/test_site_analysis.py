from types import SimpleNamespace

import pytest

from distill.config import DistillConfig
from distill.costs import CostTracker
from distill.site_analysis import (
    _call_grok,
    analyze_site_page,
    synthesize_site,
    synthesize_site_topic,
)
from distill.site_scraper import SitePage


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _response(content: str, prompt_tokens: int = 10, completion_tokens: int = 20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


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


def test_call_grok_tracks_usage():
    tracker = CostTracker()
    client = FakeClient([_response("analysis")])

    result = _call_grok(
        client,
        "prompt",
        model="grok-4.20",
        tracker=tracker,
        call_type="site_page",
    )

    assert result == "analysis"
    assert len(tracker.entries) == 1
    assert tracker.entries[0].model == "grok-4.20"


def test_call_grok_retries_then_succeeds(monkeypatch):
    waits = []
    monkeypatch.setattr("distill.site_analysis.time.sleep", lambda seconds: waits.append(seconds))
    client = FakeClient([Exception("rate limit"), _response("recovered")])

    result = _call_grok(client, "prompt", model="grok-4.20", retries=1)

    assert result == "recovered"
    assert waits == [5]


def test_call_grok_raises_after_final_failure(monkeypatch):
    monkeypatch.setattr("distill.site_analysis.time.sleep", lambda seconds: None)
    client = FakeClient([Exception("boom"), Exception("boom")])

    with pytest.raises(Exception, match="boom"):
        _call_grok(client, "prompt", model="grok-4.20", retries=1)


def test_analyze_site_page_builds_frontmatter(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    tracker = CostTracker()
    monkeypatch.setattr("distill.site_analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.site_analysis._call_grok",
        lambda client, prompt, model, tracker=None, call_type="", max_tokens=8192, retries=2: (
            "site body"
        ),
    )

    result = analyze_site_page(_page(), config, tracker=tracker)

    assert 'page_title: "Agent \\"Overview\\""' in result
    assert "site: example.com" in result
    assert "analyzed_by: grok-4.20" in result
    assert result.rstrip().endswith("site body")


def test_synthesize_site_writes_output(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    page_dir = config.site_page_dir("web", "example.com", "Agent Overview", "page1")
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    monkeypatch.setattr("distill.site_analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.site_analysis._call_grok",
        lambda client, prompt, model, tracker=None, call_type="", max_tokens=8192, retries=2: (
            "site synthesis"
        ),
    )

    result = synthesize_site("web", "example.com", config)

    assert result == "site synthesis"
    assert (config.site_dir("web", "example.com") / "synthesis.md").read_text(
        encoding="utf-8"
    ) == "site synthesis"


def test_synthesize_site_returns_empty_without_pages(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    assert synthesize_site("web", "example.com", config) == ""


def test_synthesize_site_topic_writes_output(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")
    site_dir = config.site_dir("web", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "synthesis.md").write_text("# Site synthesis", encoding="utf-8")

    monkeypatch.setattr("distill.site_analysis._get_client", lambda config: object())
    monkeypatch.setattr(
        "distill.site_analysis._call_grok",
        lambda client, prompt, model, tracker=None, call_type="", max_tokens=8192, retries=2: (
            "topic synthesis"
        ),
    )

    result = synthesize_site_topic("web", config)

    assert result == "topic synthesis"
    assert (config.topic_dir("web") / "topic_synthesis.md").read_text(
        encoding="utf-8"
    ) == "topic synthesis"


def test_synthesize_site_topic_returns_empty_without_sites(tmp_path):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "lib")

    assert synthesize_site_topic("web", config) == ""
