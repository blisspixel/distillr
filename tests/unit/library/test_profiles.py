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


def test_rejects_repository_url_not_on_github():
    bad = {
        "schema_version": "research-profile.v1",
        "name": "x",
        "topic": "x",
        "goal_file": "g.md",
        "sources": {"repositories": ["https://example.com/foo/bar"]},
    }
    with pytest.raises(ValueError, match=r"github\.com"):
        ResearchProfile.model_validate(bad)


def test_rejects_goal_file_with_drive_or_absolute(tmp_path: Path) -> None:
    path = tmp_path / "drive.yaml"
    path.write_text(
        """
        schema_version: research-profile.v1
        name: drive
        topic: drive
        goal_file: C:/foo.md
        queries:
          - agent loops
        """,
        encoding="utf-8",
    )
    with pytest.raises(ProfileValidationError, match="goal_file"):
        load_research_profile(path)


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


def _valid_profile(**overrides: object) -> dict[str, object]:
    """A minimal valid profile mapping, with per-test overrides merged in."""
    base: dict[str, object] = {
        "schema_version": "research-profile.v1",
        "name": "x",
        "topic": "x",
        "goal_file": "g.md",
        "sources": {"feeds": ["https://example.com/feed"]},
    }
    base.update(overrides)
    return base


def test_load_profile_reports_unreadable_file(tmp_path: Path) -> None:
    """A missing or unreadable profile raises ProfileValidationError, not a raw OSError."""
    with pytest.raises(ProfileValidationError, match="Could not read profile"):
        load_research_profile(tmp_path / "does-not-exist.yaml")


def test_load_profile_reports_invalid_yaml(tmp_path: Path) -> None:
    """Malformed YAML raises ProfileValidationError, not a raw YAMLError."""
    path = tmp_path / "broken.yaml"
    path.write_text("schema_version: [unclosed\n", encoding="utf-8")
    with pytest.raises(ProfileValidationError, match="Invalid YAML"):
        load_research_profile(path)


def test_load_profile_rejects_non_mapping_payload(tmp_path: Path) -> None:
    """A YAML document that is not a mapping is rejected with a clear message."""
    path = tmp_path / "list.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ProfileValidationError, match="must contain a YAML mapping"):
        load_research_profile(path)


def test_youtube_channel_requires_an_identifier() -> None:
    """A YouTube channel with no id, handle, or url is rejected."""
    raw = _valid_profile(sources={"youtube_channels": [{"label": "no id"}]})
    with pytest.raises(ValueError, match="channel_id, handle, or url"):
        ResearchProfile.model_validate(raw)


def test_youtube_channel_rejects_non_http_url() -> None:
    """A YouTube channel url must be http or https."""
    raw = _valid_profile(sources={"youtube_channels": [{"url": "ftp://youtube.com/x"}]})
    with pytest.raises(ValueError, match="youtube channel url"):
        ResearchProfile.model_validate(raw)


def test_rejects_domain_without_a_hostname() -> None:
    """A domain that resolves to no hostname is rejected."""
    raw = _valid_profile(sources={"domains": [".example.com"]})
    with pytest.raises(ValueError, match="hostname"):
        ResearchProfile.model_validate(raw)


def test_rejects_invalid_profile_name() -> None:
    """A profile name that is not a lowercase slug is rejected."""
    raw = _valid_profile(name="Not A Slug")
    with pytest.raises(ValueError, match="lowercase slug"):
        ResearchProfile.model_validate(raw)


def test_rejects_unsafe_topic() -> None:
    """A topic that is not already a safe slug is rejected."""
    raw = _valid_profile(topic="Not/Safe")
    with pytest.raises(ValueError, match="safe topic slug"):
        ResearchProfile.model_validate(raw)


def test_source_fields_coerce_null_to_empty_lists() -> None:
    """Null source collections coerce to empty lists rather than failing."""
    raw = _valid_profile(
        sources={
            "youtube_channels": None,
            "feeds": None,
            "domains": None,
            "repositories": None,
        },
        queries=["agent loops"],
    )
    profile = ResearchProfile.model_validate(raw)
    assert profile.sources.source_count == 0


def test_non_list_source_field_is_rejected() -> None:
    """A scalar where a source list is expected is rejected by the schema."""
    raw = _valid_profile(sources={"feeds": "not-a-list"}, queries=["agent loops"])
    with pytest.raises(ValueError):
        ResearchProfile.model_validate(raw)


def test_queries_null_coerces_to_empty_and_requires_a_source() -> None:
    """Null queries coerce to empty; with no sources the profile is rejected."""
    raw = {
        "schema_version": "research-profile.v1",
        "name": "x",
        "topic": "x",
        "goal_file": "g.md",
        "queries": None,
    }
    with pytest.raises(ValueError, match="at least one source or query"):
        ResearchProfile.model_validate(raw)


def test_find_profile_returns_explicit_yaml_path_in_subdir(tmp_path: Path) -> None:
    """An explicit, non-existent .yaml path with a directory component is returned as-is."""
    target = tmp_path / "sub" / "custom.yaml"
    assert find_research_profile(tmp_path, str(target)) == target


def test_find_profile_falls_back_to_canonical_path(tmp_path: Path) -> None:
    """A bare name with no matching file resolves to the canonical profile path."""
    assert find_research_profile(tmp_path, "agent-news") == profile_path(tmp_path, "agent-news")


@pytest.mark.parametrize("field", ["youtube_channels", "domains", "repositories"])
def test_non_list_scalar_source_collections_are_rejected(field: str) -> None:
    """A scalar where any source list is expected is rejected by the schema."""
    raw = _valid_profile(sources={field: "not-a-list"}, queries=["agent loops"])
    with pytest.raises(ValueError):
        ResearchProfile.model_validate(raw)


def test_non_list_queries_are_rejected() -> None:
    """A scalar where a query list is expected is rejected by the schema."""
    raw = _valid_profile(queries="not-a-list")
    with pytest.raises(ValueError):
        ResearchProfile.model_validate(raw)


def test_repository_github_url_needs_owner_and_name() -> None:
    """A github URL without both owner and name is rejected."""
    raw = _valid_profile(sources={"repositories": ["https://github.com/openai"]})
    with pytest.raises(ValueError, match="owner/name"):
        ResearchProfile.model_validate(raw)


def test_youtube_channel_with_only_channel_id_is_valid() -> None:
    """A channel with a channel_id and a blank url is accepted; the blank url validates to ''."""
    raw = _valid_profile(sources={"youtube_channels": [{"channel_id": "UC123456", "url": "  "}]})
    profile = ResearchProfile.model_validate(raw)
    channel = profile.sources.youtube_channels[0]
    assert channel.channel_id == "UC123456"
    assert channel.url == ""


def test_find_profile_returns_existing_explicit_path(tmp_path: Path) -> None:
    """An explicit path that exists is returned unchanged."""
    existing = tmp_path / "here.yaml"
    existing.write_text("schema_version: research-profile.v1\n", encoding="utf-8")
    assert find_research_profile(tmp_path, str(existing)) == existing


def test_find_profile_resolves_bare_yaml_name_to_profiles_dir(tmp_path: Path) -> None:
    """A bare .yaml filename resolves under the library's profiles directory."""
    assert find_research_profile(tmp_path, "custom.yaml") == tmp_path / "profiles" / "custom.yaml"
