"""Tests for recurring research profile schema parsing."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from distill.library.profiles import (
    PROFILE_SCHEMA_VERSION,
    ProfileValidationError,
    ResearchProfile,
    find_research_profile,
    load_research_profile,
    profile_path,
)

EXAMPLE_PROFILES = Path(__file__).resolve().parents[3] / "examples" / "profiles"


@pytest.mark.parametrize(
    "filename",
    [
        "ai-developer-news.yaml",
        "live-agentic-dev.yaml",
        "vendor-docs-watch.yaml",
    ],
)
def test_checked_in_examples_are_valid(filename: str) -> None:
    path = EXAMPLE_PROFILES / filename

    profile = load_research_profile(path)

    assert profile.schema_version == PROFILE_SCHEMA_VERSION
    assert profile.cost_mode == "no-metered"
    assert profile.limits.max_metered_usd == 0
    assert profile.sources.source_count > 0
    assert profile.queries
    assert (EXAMPLE_PROFILES / profile.goal_file).exists()


def test_coerces_common_source_shorthands() -> None:
    raw = yaml.safe_load(
        """
        schema_version: research-profile.v1
        name: agent-news
        topic: agent-news
        goal_file: goals/agent-news.md
        cost_mode: no-metered
        sources:
          youtube_channels:
            - OpenAI
            - https://www.youtube.com/@AnthropicAI
            - UC123456789
          feeds:
            - https://www.latent.space/feed
          domains:
            - https://www.Example.com
          repositories:
            - https://github.com/openai/codex
        queries:
          - agent loops
        limits:
          max_metered_usd: 0
        """
    )

    profile = ResearchProfile.model_validate(raw)

    assert profile.sources.youtube_channels[0].handle == "@OpenAI"
    assert profile.sources.youtube_channels[1].url == "https://www.youtube.com/@AnthropicAI"
    assert profile.sources.youtube_channels[2].channel_id == "UC123456789"
    assert profile.sources.feeds[0].url == "https://www.latent.space/feed"
    assert profile.sources.domains == ["example.com"]
    assert profile.sources.repositories == ["openai/codex"]


def test_rejects_profile_without_sources_or_queries(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text(
        """
        schema_version: research-profile.v1
        name: empty
        topic: empty
        goal_file: goals/empty.md
        cost_mode: no-metered
        limits:
          max_metered_usd: 0
        """,
        encoding="utf-8",
    )

    with pytest.raises(ProfileValidationError, match="at least one source or query"):
        load_research_profile(path)


def test_no_metered_profiles_must_have_zero_metered_budget(tmp_path: Path) -> None:
    path = tmp_path / "paid.yaml"
    path.write_text(
        """
        schema_version: research-profile.v1
        name: paid
        topic: paid
        goal_file: goals/paid.md
        cost_mode: no-metered
        queries:
          - agent loops
        limits:
          max_metered_usd: 1
        """,
        encoding="utf-8",
    )

    with pytest.raises(ProfileValidationError, match="max_metered_usd"):
        load_research_profile(path)


def test_goal_file_must_be_relative_safe_path(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text(
        """
        schema_version: research-profile.v1
        name: unsafe
        topic: unsafe
        goal_file: ../private.md
        queries:
          - agent loops
        """,
        encoding="utf-8",
    )

    with pytest.raises(ProfileValidationError, match="goal_file"):
        load_research_profile(path)


@pytest.mark.parametrize("stale_after", ["P", "PT", "P1DT"])
def test_freshness_duration_requires_a_complete_day_or_hour_value(stale_after: str) -> None:
    raw = {
        "schema_version": "research-profile.v1",
        "name": "agent-news",
        "topic": "agent-news",
        "goal_file": "goals/agent-news.md",
        "sources": {"feeds": ["https://www.latent.space/feed"]},
        "freshness": {"stale_after": stale_after},
    }

    with pytest.raises(ValueError, match="stale_after"):
        ResearchProfile.model_validate(raw)


def test_profile_path_resolution_prefers_existing_files(tmp_path: Path) -> None:
    canonical = profile_path(tmp_path, "agent-news")
    canonical.parent.mkdir(parents=True)
    canonical.write_text("schema_version: research-profile.v1\n", encoding="utf-8")
    explicit = tmp_path / "custom.yml"
    explicit.write_text("schema_version: research-profile.v1\n", encoding="utf-8")

    assert find_research_profile(tmp_path, "agent-news") == canonical


def test_rejects_bad_repository_and_domain_values():
    bad_repo = {
        "schema_version": "research-profile.v1",
        "name": "x",
        "topic": "x",
        "goal_file": "g.md",
        "sources": {"repositories": ["not-a-repo"]},
    }
    with pytest.raises(ValueError, match="repository"):
        ResearchProfile.model_validate(bad_repo)

    bad_domain = {
        "schema_version": "research-profile.v1",
        "name": "x",
        "topic": "x",
        "goal_file": "g.md",
        "sources": {"domains": ["example.com/foo"]},
    }
    with pytest.raises(ValueError, match="domain"):
        ResearchProfile.model_validate(bad_domain)


def test_rejects_bad_http_url_in_feeds():
    bad_feed = {
        "schema_version": "research-profile.v1",
        "name": "x",
        "topic": "x",
        "goal_file": "g.md",
        "sources": {"feeds": ["ftp://example.com/feed"]},
    }
    with pytest.raises(ValueError, match="http"):
        ResearchProfile.model_validate(bad_feed)


def test_rejects_empty_name_or_goal():
    base = {
        "schema_version": "research-profile.v1",
        "name": "",
        "topic": "x",
        "goal_file": "g.md",
        "sources": {"feeds": ["https://example.com/feed"]},
    }
    with pytest.raises(ValueError):
        ResearchProfile.model_validate(base)
