"""Tests for distill.research."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from distill.config import DistillConfig
from distill.library.paths import artifact_path, strip_frontmatter
from distill.llm.cost_policy import CostPolicyError
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.report.deep_research import (
    _get_report_path,
    run_deep_research,
)


def _completed(text):
    """A completed interaction in the real google-genai 2.7+ steps shape."""
    return SimpleNamespace(
        status="completed",
        steps=[
            SimpleNamespace(
                type="model_output",
                content=[SimpleNamespace(type="text", text=text)],
            )
        ],
    )


def _in_progress():
    return SimpleNamespace(status="in_progress", steps=[])


def test_get_report_path_respects_scope(tmp_path):
    config = DistillConfig(distill_output_dir=tmp_path / "lib")

    assert _get_report_path("ai", config, "topic", None) == artifact_path(
        config.topic_dir("ai"), "report", identity="ai"
    )
    assert _get_report_path("ai", config, "channel", "Creator") == artifact_path(
        config.channel_dir("ai", "Creator"), "report", identity="ai_Creator"
    )
    assert _get_report_path("all", config, "all", None) == artifact_path(
        config.library_dir, "report", identity="library"
    )


@pytest.mark.parametrize("cost_mode", ["auto", "paid-ok"])
def test_run_deep_research_returns_none_when_no_files(tmp_path, monkeypatch, cost_mode):
    config = DistillConfig(
        gemini_api_key="test-key",
        distill_cost_mode=cost_mode,
        distill_output_dir=tmp_path / "lib",
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = SimpleNamespace()

    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 0),
    )
    deleted = []
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.delete_store",
        lambda client, name: deleted.append(name),
    )

    result = run_deep_research("ai", config)

    assert result is None
    assert deleted == ["store-1"]


def test_run_deep_research_no_metered_refuses_before_client_or_store(tmp_path, monkeypatch):
    config = DistillConfig(
        gemini_api_key="test-key",
        distill_cost_mode="no-metered",
        distill_output_dir=tmp_path / "lib",
    )
    client = MagicMock(side_effect=AssertionError("client constructed"))
    create_store = MagicMock(side_effect=AssertionError("store created"))
    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", client)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        create_store,
    )

    with pytest.raises(CostPolicyError, match="Route blocked by no-metered cost policy"):
        run_deep_research("ai", config)

    client.assert_not_called()
    create_store.assert_not_called()


def test_run_deep_research_saves_completed_output(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    interaction_states = [
        _in_progress(),
        _completed("final report"),
    ]

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return interaction_states.pop(0)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 2),
    )
    deleted = []
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.delete_store",
        lambda client, name: deleted.append(name),
    )
    monkeypatch.setattr("distill.pipeline.report._interactions.time.sleep", lambda seconds: None)

    tracker = CostTracker()

    result = run_deep_research("ai", config, tracker=tracker)

    assert result == "final report"
    assert tracker.gemini_queries == 1
    report_path = artifact_path(config.topic_dir("ai"), "report", identity="ai")
    assert strip_frontmatter(report_path.read_text(encoding="utf-8")) == "final report"
    assert deleted == ["store-1"]


def test_run_deep_research_refuses_unresolved_numbered_citation(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return _completed("Unsupported report claim [cite: 1].")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 2),
    )
    deleted = []
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.delete_store",
        lambda client, name: deleted.append(name),
    )
    tracker = CostTracker()

    result = run_deep_research("ai", config, tracker=tracker)

    assert result is None
    assert tracker.gemini_queries == 1
    report_path = artifact_path(config.topic_dir("ai"), "report", identity="ai")
    assert not report_path.exists()
    assert deleted == ["store-1"]


def test_run_deep_research_handles_failed_interaction(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return SimpleNamespace(status="failed", steps=[])

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 2),
    )
    deleted = []
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.delete_store",
        lambda client, name: deleted.append(name),
    )

    result = run_deep_research("ai", config)

    assert result is None
    assert deleted == ["store-1"]


def test_run_deep_research_records_submitted_failed_interaction(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return SimpleNamespace(status="failed", steps=[])

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 2),
    )
    monkeypatch.setattr("distill.pipeline.report.deep_research.delete_store", lambda *_args: None)

    tracker = CostTracker()

    assert run_deep_research("ai", config, tracker=tracker) is None
    assert tracker.gemini_queries == 1


def test_run_deep_research_budget_crossing_stops_before_polling(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    deleted = []
    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 2),
    )
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.delete_store",
        lambda client, name: deleted.append(name),
    )
    poll = MagicMock(side_effect=AssertionError("polling continued after budget crossing"))
    monkeypatch.setattr("distill.pipeline.report.deep_research.await_interaction", poll)
    tracker = CostTracker(budget=0.0)

    with pytest.raises(BudgetExceededError):
        run_deep_research("ai", config, tracker=tracker)

    assert tracker.gemini_queries == 1
    poll.assert_not_called()
    assert deleted == ["store-1"]


def test_run_deep_research_returns_none_when_completed_without_output(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return SimpleNamespace(status="completed", steps=[])

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 2),
    )
    deleted = []
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.delete_store",
        lambda client, name: deleted.append(name),
    )

    result = run_deep_research("ai", config)

    assert result is None
    assert deleted == ["store-1"]


def test_run_deep_research_returns_none_on_interaction_exception(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    class FakeInteractions:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 2),
    )
    deleted = []
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.delete_store",
        lambda client, name: deleted.append(name),
    )

    assert run_deep_research("ai", config) is None
    assert deleted == ["store-1"]


def test_run_deep_research_logs_long_running_status(tmp_path, monkeypatch):
    config = DistillConfig(gemini_api_key="test-key", distill_output_dir=tmp_path / "lib")

    interaction_states = [
        _in_progress(),
        _in_progress(),
        _in_progress(),
        _in_progress(),
        _completed("done"),
    ]

    class FakeInteractions:
        def create(self, **kwargs):
            return SimpleNamespace(id="job-1")

        def get(self, interaction_id):
            return interaction_states.pop(0)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.interactions = FakeInteractions()

    monkeypatch.setattr("distill.pipeline.report.deep_research.genai.Client", FakeClient)
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.create_research_store",
        lambda *args, **kwargs: ("store-1", 2),
    )
    monkeypatch.setattr("distill.pipeline.report._interactions.time.sleep", lambda seconds: None)
    deleted = []
    monkeypatch.setattr(
        "distill.pipeline.report.deep_research.delete_store",
        lambda client, name: deleted.append(name),
    )

    assert run_deep_research("ai", config) == "done"
    assert deleted == ["store-1"]
