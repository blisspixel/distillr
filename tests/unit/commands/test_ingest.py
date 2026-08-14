"""Tests for distill.commands.ingest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from distill.commands import ingest as _ingest
from distill.commands.ingest import _host
from distill.config import DistillConfig
from distill.ingestors.github import GitHubFetchError, RepoRecord
from distill.ingestors.local import LocalExtractionError
from distill.ingestors.podcasts import (
    PodcastEpisode,
    PodcastFeed,
    PodcastFetchError,
    feed_episode_identity,
)
from distill.ingestors.x.syndication import TweetRecord
from distill.pipeline.analysis.local import LocalIngestResult
from distill.pipeline.analysis.media import MediaIngestResult
from distill.pipeline.analysis.newsletter import NewsletterIngestResult
from distill.pipeline.analysis.podcast import PodcastIngestResult
from distill.pipeline.analysis.repo import RepoIngestResult
from distill.pipeline.analysis.tweet import IngestedTweet
from distill.pipeline.costs import BudgetExceededError, CostTracker, TokenUsage


def test_host_strips_www() -> None:
    assert _host("https://www.x.com/x") == "x.com"
    assert _host("https://x.com/x") == "x.com"
    assert _host("https://twitter.com/x") == "twitter.com"
    assert _host("https://alice:password@www.x.com/status/1?token=canary") == "x.com"


def _tweet() -> TweetRecord:
    return TweetRecord(
        tweet_id="12345",
        url="https://x.com/alice/status/12345",
        author_name="Alice",
        author_handle="alice",
        author_verified=True,
        created_at="2026-05-16T12:00:00.000Z",
        text="hi",
        language="en",
        like_count=0,
        reply_count=0,
    )


def _ingested(tmp_path: Path) -> IngestedTweet:
    post_dir = tmp_path / "lib" / "topics" / "t" / "x" / "alice" / "posts" / "p"
    post_dir.mkdir(parents=True, exist_ok=True)
    tweet_path = post_dir / "alice_12345_Tweet.md"
    tweet_path.write_text("---\n---\nbody\n", encoding="utf-8")
    insights_path = post_dir / "alice_12345_Insights.md"
    insights_path.write_text("---\n---\ninsights\n", encoding="utf-8")
    transcript_path = post_dir / "alice_12345_Transcript.txt"
    transcript_path.write_text("transcript words here", encoding="utf-8")
    return IngestedTweet(
        tweet=_tweet(),
        post_dir=post_dir,
        tweet_path=tweet_path,
        transcript_path=transcript_path,
        insights_path=insights_path,
        transcript_text="transcript words here",
        insights_text="insights",
    )


def _config(tmp_path: Path) -> DistillConfig:
    return DistillConfig(xai_api_key="x", distill_output_dir=tmp_path / "lib")


def _artifact(config: DistillConfig, relative: str, text: str = "x") -> Path:
    path = config.library_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _cost_rows(config: DistillConfig) -> list[dict[str, Any]]:
    log_path = config.library_dir / ".distill" / "cost_log.jsonl"
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


def test_ingest_cmd_routes_x_url_through_x_adapter(tmp_path: Path) -> None:
    from distill.cli import app

    captured: dict[str, Any] = {}

    def _fake_ingest(url: str, *, topic: str, config: Any, **kwargs: Any) -> IngestedTweet:
        captured["url"] = url
        captured["topic"] = topic
        captured["kwargs"] = kwargs
        return _ingested(tmp_path)

    with (
        patch("distill.commands.ingest.ingest_tweet", side_effect=_fake_ingest),
        patch("distill.commands.ingest.get_config") as get_config_mock,
    ):
        from distill.config import DistillConfig

        get_config_mock.return_value = DistillConfig(
            xai_api_key="x", distill_output_dir=tmp_path / "lib"
        )
        runner = CliRunner()
        result = runner.invoke(
            app, ["ingest", "https://x.com/alice/status/12345", "--topic", "mytopic"]
        )

    assert result.exit_code == 0
    assert captured["url"] == "https://x.com/alice/status/12345"
    assert captured["topic"] == "mytopic"
    assert captured["kwargs"]["transcribe"] is True
    assert captured["kwargs"]["analyze"] is True


def test_ingest_cmd_persists_metered_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from distill.cli import app

    config = _config(tmp_path)

    def _fake_ingest(url: str, *, tracker: CostTracker, **kwargs: Any) -> IngestedTweet:
        tracker.record(
            TokenUsage(
                prompt_tokens=1_000,
                completion_tokens=500,
                model="grok-4.3",
                call_type="tweet_analysis",
                provider_name="xai",
                provider_type="cloud",
            )
        )
        return _ingested(tmp_path)

    monkeypatch.setattr(_ingest, "get_config", lambda: config)
    monkeypatch.setattr(_ingest, "ingest_tweet", _fake_ingest)

    result = CliRunner().invoke(
        app, ["ingest", "https://x.com/alice/status/12345", "--topic", "agents"]
    )

    assert result.exit_code == 0, result.output
    [row] = _cost_rows(config)
    assert row["command"] == "ingest"
    assert row["actual_cost"] == pytest.approx(0.0025)
    assert row["usage_ledger"]["metered_llm_calls"] == 1
    assert row["metadata"] == {
        "topic": "agents",
        "workflow": "ingest",
        "source_type": "x",
    }


def test_exact_completed_x_replay_has_no_second_model_write_or_ledger_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from distill.cli import app

    config = _config(tmp_path)
    tweet = _tweet()
    analysis_calls = 0

    def _fake_analysis(*args: Any, tracker: CostTracker, **kwargs: Any) -> str:
        nonlocal analysis_calls
        analysis_calls += 1
        tracker.record(
            TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                model="qwen3:8b",
                call_type="x_tweet",
                provider_name="ollama",
                provider_type="local",
            )
        )
        return "## Key Claims\n\nThe post says hi."

    monkeypatch.setattr(_ingest, "get_config", lambda: config)
    monkeypatch.setattr("distill.pipeline.analysis.tweet.fetch_tweet", lambda target: tweet)
    monkeypatch.setattr("distill.pipeline.analysis.tweet.analyze_tweet", _fake_analysis)
    args = ["ingest", tweet.url, "--topic", "agents", "--no-transcribe"]

    first = CliRunner().invoke(app, args)

    assert first.exit_code == 0, first.output
    tweet_path = next((config.topic_dir("agents") / "x").rglob("*_Tweet.md"))
    insights_path = next((config.topic_dir("agents") / "x").rglob("*_Insights.md"))
    cost_log = config.library_dir / ".distill" / "cost_log.jsonl"
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (tweet_path, insights_path, cost_log)
    }

    second = CliRunner().invoke(app, args)

    assert second.exit_code == 0, second.output
    assert "unchanged completed requested artifacts" in second.output
    assert "--force" in second.output
    assert analysis_calls == 1
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (tweet_path, insights_path, cost_log)
    } == before


def test_raw_only_x_replay_is_write_and_ledger_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from distill.cli import app

    config = _config(tmp_path)
    tweet = _tweet()
    monkeypatch.setattr(_ingest, "get_config", lambda: config)
    monkeypatch.setattr("distill.pipeline.analysis.tweet.fetch_tweet", lambda target: tweet)
    args = [
        "ingest",
        tweet.url,
        "--topic",
        "raw-agents",
        "--no-transcribe",
        "--no-analyze",
    ]

    first = CliRunner().invoke(app, args)

    assert first.exit_code == 0, first.output
    receipt = next((config.topic_dir("raw-agents") / "x").rglob("*_Tweet.md"))
    before = (receipt.read_bytes(), receipt.stat().st_mtime_ns)
    with monkeypatch.context() as replay_patch:
        model_call = MagicMock(side_effect=AssertionError("raw replay called a model"))
        replay_patch.setattr("distill.pipeline.analysis.tweet.llm_call", model_call)
        second = CliRunner().invoke(app, args)

    assert second.exit_code == 0, second.output
    assert "unchanged completed requested artifacts" in second.output
    model_call.assert_not_called()
    assert (receipt.read_bytes(), receipt.stat().st_mtime_ns) == before
    assert not (config.library_dir / ".distill" / "cost_log.jsonl").exists()


def test_ingest_cmd_persists_zero_dollar_local_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from distill.cli import app

    config = _config(tmp_path)
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"audio")

    def _fake_media(
        local_path: Path,
        topic: str,
        config: DistillConfig,
        tracker: CostTracker,
        *,
        analyze: bool,
    ) -> None:
        tracker.record(
            TokenUsage(
                prompt_tokens=800,
                completion_tokens=200,
                model="qwen3:8b",
                call_type="media_analysis",
                provider_name="ollama",
                provider_type="local",
            )
        )
        tracker.record_transcription("faster-whisper", 90.0, model="large-v3")

    monkeypatch.setattr(_ingest, "get_config", lambda: config)
    monkeypatch.setattr(_ingest, "_ingest_media", _fake_media)

    result = CliRunner().invoke(app, ["ingest", str(media), "--topic", "agents"])

    assert result.exit_code == 0, result.output
    [row] = _cost_rows(config)
    assert row["actual_cost"] == 0
    assert row["usage_ledger"]["no_metered_llm_calls"] == 1
    assert row["usage_ledger"]["no_metered_transcription_calls"] == 1
    assert row["by_route_class"]["local"]["calls"] == 1
    assert row["metadata"]["source_type"] == "media"


def test_ingest_cmd_persists_budget_crossing_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from distill.cli import app

    config = DistillConfig(
        xai_api_key="x",
        distill_output_dir=tmp_path / "lib",
        distill_cost_workflow_budgets="ingest=0.001",
    )

    def _budget_stop(
        url: str,
        topic: str,
        config: DistillConfig,
        tracker: CostTracker,
        *,
        transcribe: bool,
        analyze: bool,
    ) -> None:
        tracker.record(
            TokenUsage(
                prompt_tokens=1_000_000,
                model="grok-4.3",
                call_type="tweet_analysis",
                provider_name="xai",
                provider_type="cloud",
            )
        )

    monkeypatch.setattr(_ingest, "get_config", lambda: config)
    monkeypatch.setattr(_ingest, "_ingest_tweet_url", _budget_stop)

    result = CliRunner().invoke(app, ["ingest", "https://x.com/alice/status/12345"])

    assert result.exit_code == 1
    assert isinstance(result.exception, BudgetExceededError)
    [row] = _cost_rows(config)
    assert row["actual_cost"] == pytest.approx(2.50)
    assert row["usage_ledger"]["metered_llm_calls"] == 1
    assert row["metadata"]["source_type"] == "x"


def test_ingest_cmd_invalid_tweet_url_exits_with_code_2(tmp_path: Path) -> None:
    from distill.cli import app

    with patch("distill.commands.ingest.get_config") as get_config_mock:
        from distill.config import DistillConfig

        get_config_mock.return_value = DistillConfig(
            xai_api_key="x", distill_output_dir=tmp_path / "lib"
        )
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["ingest", "https://x.com/alice/profile?access_token=X-CANARY"],
        )

    assert result.exit_code == 2
    assert "tweet id" in result.stdout.lower()
    assert "X-CANARY" not in result.stdout


def test_ingest_cmd_invalid_tweet_url_json_is_loop_readable(tmp_path: Path) -> None:
    from distill.cli import app

    with patch("distill.commands.ingest.get_config") as get_config_mock:
        get_config_mock.return_value = DistillConfig(
            xai_api_key="x", distill_output_dir=tmp_path / "lib"
        )
        result = CliRunner().invoke(
            app,
            ["--json", "ingest", "https://x.com/alice/profile?access_token=X-CANARY"],
        )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "usage_error"
    assert payload["data"]["action"] == "ingest"
    assert "X-CANARY" not in result.stdout


def test_ingest_tweet_preserves_raw_fetch_url_but_omits_it_from_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = "https://x.com/alice/status/12345?access_token=FETCH-CANARY"
    captured: dict[str, str] = {}

    def fake_ingest(url: str, **_kwargs: object) -> IngestedTweet:
        captured["url"] = url
        return _ingested(tmp_path)

    monkeypatch.setattr(_ingest, "ingest_tweet", fake_ingest)

    _ingest._ingest_tweet_url(
        raw,
        "t",
        _config(tmp_path),
        CostTracker(),
        transcribe=False,
        analyze=False,
    )

    assert captured["url"] == raw
    assert "FETCH-CANARY" not in capsys.readouterr().out


def test_ingest_cmd_unknown_host_exits_with_code_2(tmp_path: Path) -> None:
    from distill.cli import app

    with patch("distill.commands.ingest.get_config") as get_config_mock:
        from distill.config import DistillConfig

        get_config_mock.return_value = DistillConfig(
            xai_api_key="x", distill_output_dir=tmp_path / "lib"
        )
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "https://example.com/random"])

    assert result.exit_code == 2
    assert "no dedicated adapter" in result.stdout.lower()
    assert not (tmp_path / "lib" / ".distill" / "cost_log.jsonl").exists()


def test_ingest_cmd_unknown_host_json_is_loop_readable(tmp_path: Path) -> None:
    from distill.cli import app

    with patch("distill.commands.ingest.get_config") as get_config_mock:
        get_config_mock.return_value = DistillConfig(
            xai_api_key="x", distill_output_dir=tmp_path / "lib"
        )
        result = CliRunner().invoke(app, ["--json", "ingest", "https://example.com/random"])

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "usage_error"
    assert payload["data"]["action"] == "ingest"
    assert payload["data"]["limit"]["value"] == "example.com"


def test_ingest_cmd_reports_missing_local_file_before_url_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from distill.cli import app

    config = _config(tmp_path)
    missing = tmp_path / "missing [draft] research.pdf"
    monkeypatch.setattr(_ingest, "get_config", lambda: config)

    result = CliRunner().invoke(app, ["ingest", str(missing)])

    assert result.exit_code == 5
    assert f"Local file not found: {missing.name}" in result.output
    assert str(missing) not in result.output
    assert "No dedicated adapter" not in result.output
    assert not (config.library_dir / ".distill" / "cost_log.jsonl").exists()


def test_ingest_cmd_missing_local_file_json_is_loop_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from distill.cli import app

    config = _config(tmp_path)
    missing = tmp_path / "missing [draft] research.pdf"
    monkeypatch.setattr(_ingest, "get_config", lambda: config)

    result = CliRunner().invoke(app, ["--json", "ingest", str(missing)])

    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["data"]["reason"] == "not_found"
    assert payload["data"]["phase"] == "gate.not_found"
    assert payload["data"]["action"] == "ingest"
    assert payload["data"]["limit"]["name"] == missing.name
    assert str(missing) not in payload["error"]


def test_ingest_cmd_rejects_unc_before_filesystem_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from distill.cli import app

    monkeypatch.setattr(_ingest, "get_config", lambda: _config(tmp_path))
    monkeypatch.setattr(
        _ingest,
        "Path",
        lambda _target: (_ for _ in ()).throw(
            AssertionError("remote target reached filesystem I/O")
        ),
    )

    result = CliRunner().invoke(
        app,
        ["ingest", r"\\127.0.0.1@65535\DavWWWRoot\payload.md"],
    )

    assert result.exit_code == 2
    assert "remote filesystem targets are not supported" in result.output


def test_ingest_cmd_no_transcribe_flag_passes_through(tmp_path: Path) -> None:
    from distill.cli import app

    captured: dict[str, Any] = {}

    def _fake_ingest(url: str, *, topic: str, config: Any, **kwargs: Any) -> IngestedTweet:
        captured["kwargs"] = kwargs
        return _ingested(tmp_path)

    with (
        patch("distill.commands.ingest.ingest_tweet", side_effect=_fake_ingest),
        patch("distill.commands.ingest.get_config") as get_config_mock,
    ):
        from distill.config import DistillConfig

        get_config_mock.return_value = DistillConfig(
            xai_api_key="x", distill_output_dir=tmp_path / "lib"
        )
        runner = CliRunner()
        result = runner.invoke(
            app, ["ingest", "https://x.com/alice/status/12345", "--no-transcribe", "--no-analyze"]
        )

    assert result.exit_code == 0
    assert captured["kwargs"]["transcribe"] is False
    assert captured["kwargs"]["analyze"] is False


def test_ingest_cmd_routes_local_file_path(tmp_path: Path) -> None:
    from distill.cli import app
    from distill.config import DistillConfig

    src = tmp_path / "My Note.md"
    src.write_text("# Note\n\nA local clipped article about agents.", encoding="utf-8")

    with patch("distill.commands.ingest.get_config") as get_config_mock:
        get_config_mock.return_value = DistillConfig(
            xai_api_key="x", distill_output_dir=tmp_path / "lib"
        )
        runner = CliRunner()
        # --no-analyze keeps it offline (no LLM call); just capture + write the document.
        result = runner.invoke(app, ["ingest", str(src), "--topic", "t", "--no-analyze"])

    assert result.exit_code == 0, result.output
    assert "Document" in result.output
    docs = list((tmp_path / "lib" / "topics" / "t" / "local").glob("*/*_Content.md"))
    assert docs and "clipped article" in docs[0].read_text(encoding="utf-8")


def test_ingest_cmd_routes_media_github_and_feed_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from distill.cli import app

    config = _config(tmp_path)
    media = tmp_path / "clip.mp3"
    media.write_bytes(b"audio")
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(_ingest, "get_config", lambda: config)
    monkeypatch.setattr(
        _ingest,
        "_ingest_media",
        lambda *args, **kwargs: calls.append(("media", kwargs)),
    )
    monkeypatch.setattr(
        _ingest,
        "_ingest_github",
        lambda *args, **kwargs: calls.append(("github", kwargs)),
    )
    monkeypatch.setattr(
        _ingest,
        "_ingest_feed",
        lambda *args, **kwargs: calls.append(("feed", kwargs)),
    )
    runner = CliRunner()

    media_result = runner.invoke(app, ["ingest", str(media), "--no-analyze"])
    github_result = runner.invoke(
        app, ["ingest", "https://github.com/acme/project", "--no-analyze"]
    )
    feed_result = runner.invoke(
        app,
        [
            "ingest",
            "https://example.com/feed.xml",
            "--rss",
            "--episodes",
            "3",
            "--no-transcribe",
            "--no-analyze",
        ],
    )

    assert media_result.exit_code == 0, media_result.output
    assert github_result.exit_code == 0, github_result.output
    assert feed_result.exit_code == 0, feed_result.output
    assert calls == [
        ("media", {"analyze": False}),
        ("github", {"analyze": False}),
        (
            "feed",
            {"episodes": 3, "episode_id": "", "transcribe": False, "analyze": False},
        ),
    ]


def test_ingest_local_reports_insights_and_extraction_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    document = _artifact(config, "topics/t/local/doc/doc_Content.md")
    insights = _artifact(config, "topics/t/local/doc/doc_Insights.md")
    monkeypatch.setattr(
        _ingest,
        "ingest_local_file",
        lambda *args, **kwargs: LocalIngestResult(
            document_path=document,
            insights_path=insights,
            kind="markdown",
            title="Doc",
            slug="doc",
        ),
    )

    _ingest._ingest_local(tmp_path / "doc.md", "t", config, CostTracker(), analyze=True)

    output = capsys.readouterr().out
    assert "Document" in output
    assert "Insights" in output

    monkeypatch.setattr(
        _ingest,
        "ingest_local_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(LocalExtractionError("cannot extract")),
    )

    with pytest.raises(typer.Exit) as exc_info:
        _ingest._ingest_local(tmp_path / "broken.pdf", "t", config, CostTracker(), analyze=True)

    assert exc_info.value.exit_code == 2
    assert "cannot extract" in capsys.readouterr().out


def test_ingest_tweet_url_reports_skipped_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    tweet_path = _artifact(config, "topics/t/x/alice/posts/p/alice_12345_Tweet.md")
    result = IngestedTweet(
        tweet=_tweet(),
        post_dir=tweet_path.parent,
        tweet_path=tweet_path,
        skipped_reasons=["video transcript unavailable"],
    )
    monkeypatch.setattr(_ingest, "ingest_tweet", lambda *args, **kwargs: result)

    _ingest._ingest_tweet_url(
        "https://x.com/alice/status/12345",
        "t",
        config,
        CostTracker(),
        transcribe=True,
        analyze=True,
    )

    assert "video transcript unavailable" in capsys.readouterr().out


def test_ingest_media_reports_skipped_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    transcript = _artifact(config, "topics/t/media/clip/clip_Transcript.txt")
    insights = _artifact(config, "topics/t/media/clip/clip_Insights.md")
    monkeypatch.setattr(
        _ingest,
        "ingest_media_file",
        lambda *args, **kwargs: MediaIngestResult(
            transcript_path=transcript,
            insights_path=insights,
            title="Media",
            skipped_reasons=["transcription produced no text"],
        ),
    )

    _ingest._ingest_media(tmp_path / "clip.mp3", "t", config, CostTracker(), analyze=True)

    output = capsys.readouterr().out
    assert "Transcript" in output
    assert "Insights" in output
    assert "transcription produced no text" in output

    monkeypatch.setattr(
        _ingest,
        "ingest_media_file",
        lambda *args, **kwargs: MediaIngestResult(
            transcript_path=None,
            insights_path=None,
            title="Media",
            skipped_reasons=[],
        ),
    )

    _ingest._ingest_media(tmp_path / "silent.mp3", "t", config, CostTracker(), analyze=False)

    empty_output = capsys.readouterr().out
    assert "Transcript" not in empty_output
    assert "Insights" not in empty_output


def test_ingest_feed_routes_newsletter_and_podcast_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    feed = PodcastFeed(title="Feed", link="https://example.com/feed", description="")
    content = _artifact(config, "topics/t/newsletters/feed/post/post_Content.md")
    newsletter_insights = _artifact(config, "topics/t/newsletters/feed/post/post_Insights.md")
    episode = _artifact(config, "topics/t/podcasts/show/episode/episode_Episode.md")
    podcast_insights = _artifact(config, "topics/t/podcasts/show/episode/episode_Insights.md")
    monkeypatch.setattr(_ingest, "fetch_feed", lambda url: feed)
    monkeypatch.setattr(_ingest, "feed_is_newsletter", lambda parsed_feed: True)
    monkeypatch.setattr(
        _ingest,
        "ingest_newsletter",
        lambda *args, **kwargs: NewsletterIngestResult(
            feed_title="Newsletter",
            content_paths=[content],
            insight_paths=[newsletter_insights],
            skipped_reasons=["post had no body"],
        ),
    )

    _ingest._ingest_feed(
        "https://example.com/feed.xml",
        "t",
        config,
        CostTracker(),
        episodes=2,
        transcribe=True,
        analyze=True,
    )

    newsletter_output = capsys.readouterr().out
    assert "Publication" in newsletter_output
    assert "post had no body" in newsletter_output

    monkeypatch.setattr(_ingest, "feed_is_newsletter", lambda parsed_feed: False)
    monkeypatch.setattr(
        _ingest,
        "ingest_podcast",
        lambda *args, **kwargs: PodcastIngestResult(
            feed_title="Podcast",
            episode_paths=[episode],
            insight_paths=[podcast_insights],
            skipped_reasons=["episode skipped"],
        ),
    )

    _ingest._ingest_feed(
        "https://example.com/feed.xml",
        "t",
        config,
        CostTracker(),
        episodes=1,
        transcribe=False,
        analyze=False,
    )

    podcast_output = capsys.readouterr().out
    assert "Show" in podcast_output
    assert "episode skipped" in podcast_output


def test_ingest_feed_reports_fetch_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        _ingest,
        "fetch_feed",
        lambda url: (_ for _ in ()).throw(PodcastFetchError("feed unavailable")),
    )

    with pytest.raises(typer.Exit) as exc_info:
        _ingest._ingest_feed(
            "https://example.com/feed.xml",
            "t",
            config,
            CostTracker(),
            episodes=1,
            transcribe=True,
            analyze=True,
        )

    assert exc_info.value.exit_code == 2
    assert "feed unavailable" in capsys.readouterr().out


def test_ingest_feed_selects_exact_episode_before_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    newest = PodcastEpisode(
        title="Newest",
        guid="newest",
        published="",
        audio_url="https://example.com/newest.mp3",
        audio_type="audio/mpeg",
        duration_s=60,
        description="",
    )
    older = PodcastEpisode(
        title="Older",
        guid="older",
        published="",
        audio_url="https://example.com/older.mp3",
        audio_type="audio/mpeg",
        duration_s=60,
        description="",
    )
    url = "https://example.com/feed.xml"
    feed = PodcastFeed(title="Feed", link="", description="", episodes=[newest, older])
    captured: dict[str, object] = {}
    monkeypatch.setattr(_ingest, "fetch_feed", lambda _url: feed)
    monkeypatch.setattr(_ingest, "feed_is_newsletter", lambda _feed: False)

    def fake_ingest_podcast(*args: object, **kwargs: object) -> PodcastIngestResult:
        captured.update(kwargs)
        return PodcastIngestResult(feed_title="Feed")

    monkeypatch.setattr(_ingest, "ingest_podcast", fake_ingest_podcast)

    _ingest._ingest_feed(
        url,
        "t",
        config,
        CostTracker(),
        episodes=9,
        transcribe=False,
        analyze=False,
        episode_id=feed_episode_identity(url, older),
    )

    selected_feed = captured["feed"]
    assert isinstance(selected_feed, PodcastFeed)
    assert [episode.guid for episode in selected_feed.episodes] == ["older"]
    assert captured["episodes"] == 1


def test_ingest_github_reports_invalid_fetch_errors_and_skipped_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)

    with pytest.raises(typer.Exit) as invalid_exc:
        _ingest._ingest_github(
            "https://github.com/settings?access_token=GITHUB-CANARY",
            "t",
            config,
            CostTracker(),
            analyze=True,
        )

    assert invalid_exc.value.exit_code == 2
    invalid_output = capsys.readouterr().out
    assert "owner/repo" in invalid_output
    assert "GITHUB-CANARY" not in invalid_output

    monkeypatch.setattr(
        _ingest,
        "ingest_repo",
        lambda *args, **kwargs: (_ for _ in ()).throw(GitHubFetchError("rate limited")),
    )

    with pytest.raises(typer.Exit) as fetch_exc:
        _ingest._ingest_github(
            "https://github.com/acme/project", "t", config, CostTracker(), analyze=True
        )

    assert fetch_exc.value.exit_code == 2
    assert "rate limited" in capsys.readouterr().out

    repo_path = _artifact(config, "topics/t/repos/acme-project/acme-project_Repo.md")
    insights = _artifact(config, "topics/t/repos/acme-project/acme-project_Insights.md")
    record = RepoRecord(
        full_name="acme/project",
        url="https://github.com/acme/project",
        description="Project",
        stars=1234,
        forks=12,
        open_issues=3,
        language="Python",
        license_name="MIT",
    )
    monkeypatch.setattr(
        _ingest,
        "ingest_repo",
        lambda *args, **kwargs: RepoIngestResult(
            repo_path=repo_path,
            insights_path=insights,
            record=record,
            skipped_reasons=["no releases found"],
        ),
    )

    _ingest._ingest_github(
        "https://github.com/acme/project", "t", config, CostTracker(), analyze=True
    )

    success_output = capsys.readouterr().out
    assert "Repo" in success_output
    assert "Insights" in success_output
    assert "no releases found" in success_output

    monkeypatch.setattr(
        _ingest,
        "ingest_repo",
        lambda *args, **kwargs: RepoIngestResult(
            repo_path=repo_path,
            insights_path=None,
            record=record,
            skipped_reasons=[],
        ),
    )

    _ingest._ingest_github(
        "https://github.com/acme/project", "t", config, CostTracker(), analyze=False
    )

    no_insights_output = capsys.readouterr().out
    assert "Repo" in no_insights_output
    assert "Insights" not in no_insights_output
