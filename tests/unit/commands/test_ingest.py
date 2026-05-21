"""Tests for distill.commands.ingest."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from distill.commands.ingest import _host
from distill.ingestors.x.syndication import TweetRecord
from distill.pipeline.analysis.tweet import IngestedTweet


def test_host_strips_www() -> None:
    assert _host("https://www.x.com/x") == "x.com"
    assert _host("https://x.com/x") == "x.com"
    assert _host("https://twitter.com/x") == "twitter.com"


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


def test_ingest_cmd_invalid_tweet_url_exits_with_code_2(tmp_path: Path) -> None:
    from distill.cli import app

    with patch("distill.commands.ingest.get_config") as get_config_mock:
        from distill.config import DistillConfig

        get_config_mock.return_value = DistillConfig(
            xai_api_key="x", distill_output_dir=tmp_path / "lib"
        )
        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "https://x.com/alice/profile"])

    assert result.exit_code == 2
    assert "tweet id" in result.stdout.lower()


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
