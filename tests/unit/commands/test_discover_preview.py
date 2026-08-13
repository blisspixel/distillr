"""CLI tests for the discover preview-cache flow (--preview save, --from-preview replay)."""

import pytest
from typer.testing import CliRunner

from distill import _cli_impl, cli
from distill.commands import _discover_flow
from distill.commands import discover as _discover
from distill.commands import topic as _topic
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.youtube.discovery import VideoInfo
from distill.library.intent import load_intent
from distill.pipeline.costs import ProjectedBudgetExceededError
from distill.pipeline.discovery import RankedDiscoverItem
from distill.pipeline.goals import load_topic_goals
from distill.pipeline.preview_cache import preview_cache_dir, save_preview

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    config = DistillConfig(xai_api_key="test-key", distill_output_dir=tmp_path / "library")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    monkeypatch.setattr(_discover, "get_config", lambda: config)
    monkeypatch.setattr(_discover, "_require_model", lambda: None)
    monkeypatch.setattr(_topic, "get_config", lambda: config)
    return config


def _seed_preview(config) -> str:
    items = [
        RankedDiscoverItem(
            kind="paper",
            identifier="2601.1",
            title="P",
            subtitle="A",
            date="2026-01-01",
            final_score=0.9,
            goal_fit=0.9,
            depth_score=0.8,
            complementarity_score=0.7,
            rationale="r",
            paper=PaperRecord(paper_id="2601.1", title="P", abstract="a"),
        ),
        RankedDiscoverItem(
            kind="video",
            identifier="v1",
            title="V",
            subtitle="C",
            date="20260101",
            final_score=0.8,
            goal_fit=0.8,
            depth_score=0.7,
            complementarity_score=0.6,
            rationale="r",
            video=VideoInfo(
                video_id="v1", title="V", upload_date="20260101", duration=600, url="u"
            ),
        ),
    ]
    snap = save_preview(
        preview_cache_dir(config.library_dir),
        goal="learn things",
        model="",
        rigor="balanced",
        items=items,
        estimate={"expected": 0.02, "low": 0.01, "high": 0.04, "calibrated": False},
        now_iso="2026-06-01T00:00:00",
        settings={"video_limit": 4, "paper_limit": 3, "days": 14, "shorts": True},
    )
    return snap.id


def test_from_preview_replays_exact_saved_set(mock_config, monkeypatch):
    preview_id = _seed_preview(mock_config)
    captured = {}

    def fake_ingest(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(_discover, "_discover_ingest_set", fake_ingest)

    result = runner.invoke(
        cli.app, ["discover", "--from-preview", preview_id, "--topic", "t", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert f"Replaying previewed set {preview_id}" in result.output
    assert captured["topic_name"] == "t"
    assert len(captured["ranked_papers"]) == 1
    assert len(captured["ranked_videos"]) == 1
    assert captured["ranked_papers"][0].paper.paper_id == "2601.1"
    assert captured["ranked_videos"][0].video.video_id == "v1"
    assert captured["summary"].estimated_cost == 0.0
    intent = load_intent(mock_config.topic_dir("t"))
    assert intent is not None
    assert intent.goal == "learn things"
    assert intent.rigor == "balanced"
    assert load_topic_goals(mock_config.library_dir)["t"]["goal"] == "learn things"


def test_topic_create_replays_saved_set_and_saves_exact_profile(mock_config, monkeypatch):
    preview_id = _seed_preview(mock_config)
    captured = {}
    monkeypatch.setattr(_discover, "_discover_ingest_set", lambda **kwargs: captured.update(kwargs))

    result = runner.invoke(
        cli.app,
        [
            "topic",
            "create",
            "--from-preview",
            preview_id,
            "--topic",
            "memory",
            "--videos",
            "0",
            "--papers",
            "1",
            "--days",
            "2",
            "--no-shorts",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["topic_name"] == "memory"
    assert len(captured["ranked_papers"]) == 1
    assert len(captured["ranked_videos"]) == 1
    profile = _topic._load_topic_profile(mock_config, "memory")
    assert profile is not None
    assert profile["goal"] == "learn things"
    assert profile["videos"] == 4
    assert profile["papers"] == 3
    assert profile["days"] == 14
    assert profile["shorts"] is True


def test_from_preview_unknown_id_errors(mock_config):
    result = runner.invoke(cli.app, ["discover", "--from-preview", "abcabc1234", "--topic", "t"])
    assert result.exit_code == 1
    assert "No previewed set" in result.output


def test_from_preview_rejects_combination_with_preview(mock_config):
    result = runner.invoke(cli.app, ["discover", "--from-preview", "abcabc1234", "--preview"])
    assert result.exit_code == 1
    assert "can't combine" in result.output


def test_from_preview_refuses_projected_spend_before_ingest(mock_config, monkeypatch):
    monkeypatch.setenv("DISTILL_PROVIDER", "xai")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    mock_config.distill_cost_workflow_budgets = "discover=0.01"
    preview_id = _seed_preview(mock_config)
    called = {"ingest": False}
    monkeypatch.setattr(
        _discover,
        "_discover_ingest_set",
        lambda **_kwargs: called.__setitem__("ingest", True),
    )

    with pytest.raises(ProjectedBudgetExceededError) as raised:
        runner.invoke(
            cli.app,
            ["discover", "--from-preview", preview_id, "--topic", "t", "--yes"],
            catch_exceptions=False,
        )

    assert raised.value.projected == pytest.approx(0.09933333333333333)
    assert called["ingest"] is False


# ---- preview-as-default sizing flow (0.9.3) --------------------------------


def _patch_discover_pipeline(monkeypatch):
    """Stub query-gen / fan-out / rerank so a fresh-topic discover reaches the menu."""
    ranked = [
        RankedDiscoverItem(
            kind="paper",
            identifier="p1",
            title="P1",
            subtitle="A",
            date="2026-01-01",
            final_score=0.95,
            goal_fit=0.95,
            depth_score=0.9,
            complementarity_score=0.8,
            rationale="r",
            paper=PaperRecord(paper_id="p1", title="P1", abstract="a"),
        ),
        RankedDiscoverItem(
            kind="video",
            identifier="v1",
            title="V1",
            subtitle="C",
            date="20260101",
            final_score=0.45,
            goal_fit=0.45,
            depth_score=0.4,
            complementarity_score=0.4,
            rationale="r",
            video=VideoInfo(
                video_id="v1", title="V1", upload_date="20260101", duration=600, url="u"
            ),
        ),
    ]
    monkeypatch.setattr(_discover, "_discover_generate_queries", lambda *a, **k: (["q"], ["q"]))
    monkeypatch.setattr(_discover, "search_arxiv_multi", lambda *a, **k: [object()])
    monkeypatch.setattr(_discover, "_discover_fetch_videos", lambda *a, **k: [object()])
    monkeypatch.setattr(_discover, "_discover_rerank", lambda *a, **k: ranked)
    return ranked


def test_fresh_topic_defaults_to_sizing_menu(mock_config, monkeypatch):
    _patch_discover_pipeline(monkeypatch)
    captured = {}
    monkeypatch.setattr(_discover_flow, "_discover_ingest_set", lambda **k: captured.update(k))
    # The sizing menu is interactive; force the TTY path so CliRunner's input is read.
    monkeypatch.setattr("distill.commands._helpers.isatty", lambda: True)

    # Fresh topic (no artifacts) -> menu; pick option 1 (the excellent/cliff cut).
    result = runner.invoke(cli.app, ["discover", "compose music", "--topic", "fresh"], input="1\n")

    assert result.exit_code == 0, result.output
    assert "How much of this should I ingest?" in result.output
    # Option 1 is the smallest cut: the single high-scoring paper, not the 0.45 video.
    assert len(captured["ranked_papers"]) == 1
    assert len(captured["ranked_videos"]) == 0


def test_fresh_topic_cancel_aborts(mock_config, monkeypatch):
    _patch_discover_pipeline(monkeypatch)
    called = {"ingest": False}
    monkeypatch.setattr(
        _discover,
        "_discover_ingest_set",
        lambda **k: called.__setitem__("ingest", True),
    )
    # Interactive cancel: force the TTY path so the typed "n" is read.
    monkeypatch.setattr("distill.commands._helpers.isatty", lambda: True)

    result = runner.invoke(cli.app, ["discover", "compose music", "--topic", "fresh"], input="n\n")
    assert result.exit_code == 0
    assert called["ingest"] is False
    assert "Aborted" in result.output


def test_fresh_topic_non_tty_does_not_ingest_without_yes(mock_config, monkeypatch):
    """Loop-safety: a fresh-topic discover with no TTY and no --yes resolves the
    sizing menu to its default but the ingest confirm declines, so nothing is
    ingested and the run exits cleanly rather than hanging on the prompt."""
    _patch_discover_pipeline(monkeypatch)
    called = {"ingest": False}
    monkeypatch.setattr(
        _discover,
        "_discover_ingest_set",
        lambda **k: called.__setitem__("ingest", True),
    )
    # No isatty override -> CliRunner's stdin reports non-TTY (the loop case).
    result = runner.invoke(cli.app, ["discover", "compose music", "--topic", "fresh"])
    assert result.exit_code == 0
    assert called["ingest"] is False
    assert "Aborted" in result.output


def test_yes_bypasses_sizing_menu_on_fresh_topic(mock_config, monkeypatch):
    _patch_discover_pipeline(monkeypatch)
    captured = {}
    monkeypatch.setattr(_discover, "_discover_ingest_set", lambda **k: captured.update(k))

    # --yes -> skip the menu, take the rigor path (balanced=0.5 keeps only the paper).
    result = runner.invoke(cli.app, ["discover", "compose music", "--topic", "fresh", "--yes"])
    assert result.exit_code == 0, result.output
    assert "How much of this should I ingest?" not in result.output
    assert captured["yes"] is True


def test_discover_refuses_projected_ingest_spend_before_ingest(mock_config, monkeypatch):
    monkeypatch.setenv("DISTILL_PROVIDER", "xai")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    mock_config.distill_cost_workflow_budgets = "discover=0.0001"
    _patch_discover_pipeline(monkeypatch)
    called = {"ingest": False}
    monkeypatch.setattr(
        _discover,
        "_discover_ingest_set",
        lambda **_kwargs: called.__setitem__("ingest", True),
    )

    with pytest.raises(ProjectedBudgetExceededError) as raised:
        runner.invoke(
            cli.app,
            ["discover", "compose music", "--topic", "fresh", "--yes"],
            catch_exceptions=False,
        )

    assert raised.value.projected > raised.value.budget
    assert called["ingest"] is False


def test_topic_create_drives_real_discover_wiring(mock_config, monkeypatch):
    """`topic create` (mixed sources) must run the REAL discover() end to end.

    Regression for the OptionInfo-leak bug: topic_create dispatches to discover as
    a plain function via _invoke_command. The original test mocked discover itself,
    which hid a broken dispatch that made every mixed-source `topic create` exit on
    discover's from_preview/from_gaps guard. Here we mock ONLY the external boundary
    (query-gen, fan-out, rerank, final ingest) so the real command-to-command wiring
    is exercised -- this fails if discover's guards see leaked sentinels again.
    """
    _patch_discover_pipeline(monkeypatch)
    captured = {}
    monkeypatch.setattr(_discover, "_discover_ingest_set", lambda **k: captured.update(k))

    result = runner.invoke(
        cli.app,
        ["topic", "create", "compose music", "--topic", "wired", "--videos", "2", "--papers", "2"],
    )

    assert result.exit_code == 0, result.output
    # The real discover() ran (no from_preview guard misfire) and reached ingestion
    # through the topic_create -> _invoke_command -> discover wiring.
    assert captured["topic_name"] == "wired"
