"""Tests for distill.pipeline.analysis.repo (GitHub repo ingest orchestration)."""

from __future__ import annotations

import pytest

from distill.config import DistillConfig
from distill.ingestors.github import RepoRecord
from distill.llm.router import LLM_Response
from distill.pipeline.analysis import repo as repo_mod
from distill.pipeline.costs import CostTracker


def _record(**overrides) -> RepoRecord:
    base = {
        "full_name": "o/r",
        "url": "https://github.com/o/r",
        "description": "A research tool",
        "stars": 1234,
        "forks": 56,
        "open_issues": 7,
        "language": "Python",
        "license_name": "MIT",
        "topics": ["ai"],
        "created_at": "2025-01-02T00:00:00Z",
        "pushed_at": "2026-06-10T00:00:00Z",
        "archived": False,
        "default_branch": "main",
        "readme": "Reaches 72.6 accuracy on the benchmark with 1,234 users.",
        "releases": [{"tag": "v1.0", "name": "", "published_at": "2026-01-01", "body": ""}],
    }
    base.update(overrides)
    return RepoRecord(**base)


@pytest.fixture
def config(tmp_path):
    return DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "library")


def _patch(monkeypatch, *, insight_text: str):
    monkeypatch.setattr(repo_mod, "fetch_repo", lambda owner, repo: _record())
    monkeypatch.setattr(
        repo_mod,
        "llm_call",
        lambda rc, **kwargs: LLM_Response(
            text=insight_text, input_tokens=10, output_tokens=5, model="grok-4.3"
        ),
    )


def test_ingest_repo_writes_receipt_and_verified_insight(config, monkeypatch):
    _patch(monkeypatch, insight_text="## Summary\nReaches 72.6 accuracy; 1,234 users.")
    tracker = CostTracker()

    result = repo_mod.ingest_repo(
        "https://github.com/o/r", topic="tkg", config=config, tracker=tracker
    )

    assert result.repo_path.exists()
    receipt = result.repo_path.read_text(encoding="utf-8")
    assert "Stars: 1,234" in receipt and "README" in receipt
    assert result.insights_path is not None and result.insights_path.exists()
    insight = result.insights_path.read_text(encoding="utf-8")
    assert 'source_id: "o/r"' in insight
    assert 'prompt_id: "analysis.github_repo.v1"' in insight
    # Verify hook ran and the claims ground in the receipt.
    sidecars = list(result.repo_path.parent.glob("*_Verify.json"))
    assert len(sidecars) == 1
    assert tracker.entries[0].call_type == "repo_analysis"


def test_ingest_repo_strict_refuses_unsupported_insight(config, monkeypatch):
    _patch(monkeypatch, insight_text="## Summary\nClaims 99.99 accuracy.")
    config.distill_verify = "strict"

    result = repo_mod.ingest_repo("https://github.com/o/r", topic="tkg", config=config)

    assert result.insights_path is None
    assert result.skipped_reasons and "refused" in result.skipped_reasons[0]
    assert result.repo_path.exists()  # receipt kept


def test_ingest_repo_no_analyze_captures_only(config, monkeypatch):
    monkeypatch.setattr(repo_mod, "fetch_repo", lambda owner, repo: _record())

    result = repo_mod.ingest_repo(
        "https://github.com/o/r", topic="tkg", config=config, analyze=False
    )

    assert result.repo_path.exists()
    assert result.insights_path is None


def test_ingest_repo_rejects_bad_url(config):
    with pytest.raises(ValueError, match="GitHub repository URL"):
        repo_mod.ingest_repo("https://example.com/x", topic="tkg", config=config)


def test_ingest_command_routes_github(config, monkeypatch, tmp_path):
    """Dispatcher wiring: `distill ingest <github-url>` reaches the repo adapter."""
    from typer.testing import CliRunner

    from distill import _cli_impl, cli
    from distill.commands import ingest as ingest_cmd_mod

    monkeypatch.setattr(_cli_impl, "get_config", lambda: config)
    monkeypatch.setattr(ingest_cmd_mod, "get_config", lambda: config)
    monkeypatch.setattr(repo_mod, "fetch_repo", lambda owner, repo: _record())
    monkeypatch.setattr(
        repo_mod,
        "llm_call",
        lambda rc, **kwargs: LLM_Response(
            text="## Summary\nReaches 72.6 accuracy.", input_tokens=1, output_tokens=1, model="m"
        ),
    )

    result = CliRunner().invoke(cli.app, ["ingest", "https://github.com/o/r", "--topic", "tkg"])

    assert result.exit_code == 0, result.output
    assert "Repo" in result.output
    assert "1,234 stars" in result.output
