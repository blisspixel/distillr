"""Tests for recurring research profile schema parsing."""

from __future__ import annotations

import sys
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


@pytest.mark.parametrize(
    "goal_file",
    [
        "goals/con.md",
        "goals/a?.md",
        "goals/name.",
        "goals/name. /file.md",
        "goals/file:stream",
        "goals/./x.md",
        "goals//x.md",
    ],
)
def test_goal_file_requires_canonical_cross_platform_components(goal_file: str) -> None:
    raw = _valid_profile(goal_file=goal_file)

    with pytest.raises(ValueError, match="goal_file"):
        ResearchProfile.model_validate(raw)


@pytest.mark.parametrize(
    "stale_after",
    ["P", "PT", "P1DT", "P\u0661D", "P" + "9" * 100 + "D", "P" + "9" * 5000 + "D"],
)
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


def test_freshness_duration_accepts_ten_year_boundary() -> None:
    raw = {
        "schema_version": "research-profile.v1",
        "name": "agent-news",
        "topic": "agent-news",
        "goal_file": "goals/agent-news.md",
        "sources": {"youtube_channels": [{"handle": "@Example"}]},
        "freshness": {"stale_after": "P3650D"},
    }

    assert ResearchProfile.model_validate(raw).freshness.stale_after == "P3650D"


@pytest.mark.parametrize("stale_after", ["P3651D", "P3650DT1H"])
@pytest.mark.parametrize(
    "source",
    [
        {"handle": "@Example"},
        {"url": "https://www.youtube.com/@Example"},
        {"channel_id": "UC123456"},
    ],
)
def test_freshness_duration_rejects_windows_beyond_discovery_horizon(
    stale_after: str, source: dict[str, str]
) -> None:
    raw = {
        "schema_version": "research-profile.v1",
        "name": "agent-news",
        "topic": "agent-news",
        "goal_file": "goals/agent-news.md",
        "sources": {"youtube_channels": [source]},
        "freshness": {"stale_after": stale_after},
    }

    with pytest.raises(ValueError, match="cannot exceed P3650D"):
        ResearchProfile.model_validate(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_new_items", True), ("max_metered_usd", True)],
)
def test_profile_limits_reject_boolean_coercion(field: str, value: object) -> None:
    raw = {
        "schema_version": "research-profile.v1",
        "name": "agent-news",
        "topic": "agent-news",
        "goal_file": "goals/agent-news.md",
        "queries": ["agent loops"],
        "limits": {field: value},
    }

    with pytest.raises(ValueError, match="numeric, not boolean"):
        ResearchProfile.model_validate(raw)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_profile_metered_budget_must_be_finite(value: float) -> None:
    raw = _valid_profile(limits={"max_metered_usd": value})

    with pytest.raises(ValueError, match="finite number"):
        ResearchProfile.model_validate(raw)


def test_profile_new_item_limit_has_a_hard_ceiling() -> None:
    raw = _valid_profile(limits={"max_new_items": 1_001})

    with pytest.raises(ValueError, match="less than or equal to 1000"):
        ResearchProfile.model_validate(raw)


@pytest.mark.parametrize(
    "overrides",
    [
        {"queries": [f"query {index}" for index in range(101)], "sources": {}},
        {"sources": {"feeds": [f"https://example.com/{index}.xml" for index in range(101)]}},
        {
            "queries": [f"query {index}" for index in range(50)],
            "sources": {"domains": [f"domain{index}.example.com" for index in range(51)]},
        },
    ],
)
def test_profile_declarations_have_per_list_and_total_caps(
    overrides: dict[str, object],
) -> None:
    raw = _valid_profile(**overrides)

    with pytest.raises(ValueError, match=r"(at most 100 items|more than 100 total)"):
        ResearchProfile.model_validate(raw)


def test_load_profile_wraps_oversized_yaml_integer_conversion(tmp_path: Path) -> None:
    path = tmp_path / "huge.yaml"
    path.write_text(
        "schema_version: research-profile.v1\n"
        "name: huge\n"
        "topic: huge\n"
        "goal_file: g.md\n"
        "queries: [x]\n"
        f"limits:\n  max_new_items: {'9' * 5000}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProfileValidationError, match="Invalid YAML"):
        load_research_profile(path)


def test_profile_yaml_integer_cap_is_independent_of_interpreter_limit(tmp_path: Path) -> None:
    path = tmp_path / "huge-disabled-cap.yaml"
    path.write_text(
        "schema_version: research-profile.v1\n"
        "name: huge-disabled-cap\n"
        "topic: huge-disabled-cap\n"
        "goal_file: g.md\n"
        "queries: [x]\n"
        f"limits:\n  max_new_items: {'9' * 900_000}\n",
        encoding="utf-8",
    )
    previous = sys.get_int_max_str_digits()
    try:
        sys.set_int_max_str_digits(0)
        with pytest.raises(ProfileValidationError, match="100 source characters"):
            load_research_profile(path)
    finally:
        sys.set_int_max_str_digits(previous)


@pytest.mark.parametrize(
    "integer_text",
    [
        "+" + "9" * 101,
        "0x" + "f" * 101,
        "0b" + "1" * 101,
        "1:" * 51 + "1",
        "1_" * 51 + "1",
    ],
)
def test_profile_yaml_integer_cap_covers_yaml_integer_forms(
    tmp_path: Path,
    integer_text: str,
) -> None:
    path = tmp_path / "numeric-forms.yaml"
    path.write_text(f"value: {integer_text}\n", encoding="utf-8")

    with pytest.raises(ProfileValidationError, match="100 source characters"):
        load_research_profile(path)


def test_load_profile_rejects_oversized_file_before_yaml_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "oversized.yaml"
    path.write_bytes(b"x" * 1_000_001)
    calls: list[object] = []
    monkeypatch.setattr(yaml, "load", lambda value, Loader: calls.append((value, Loader)) or {})

    with pytest.raises(ProfileValidationError, match="byte cap"):
        load_research_profile(path)

    assert calls == []


def test_load_profile_rejects_recursive_yaml_alias(tmp_path: Path) -> None:
    path = tmp_path / "recursive.yaml"
    path.write_text("root: &root\n  child: *root\n", encoding="utf-8")

    with pytest.raises(ProfileValidationError, match="recursive YAML aliases"):
        load_research_profile(path)


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


@pytest.mark.parametrize(
    "repository",
    [
        "https://user@github.com/openai/codex",
        "https://github.com:443/openai/codex",
        "https://github.com/openai/codex/issues",
        "https://github.com/openai/codex?tab=readme",
        "https://github.com/openai/codex#readme",
    ],
)
def test_rejects_ambiguous_repository_urls(repository: str) -> None:
    raw = _valid_profile(sources={"repositories": [repository]})

    with pytest.raises(ValueError, match="repository"):
        ResearchProfile.model_validate(raw)


def test_normalizes_exact_github_clone_url() -> None:
    raw = _valid_profile(sources={"repositories": ["https://github.com/openai/codex.git"]})

    profile = ResearchProfile.model_validate(raw)

    assert profile.sources.repositories == ["openai/codex"]


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


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/feed",
        "ftp://example.com/feed",
        "https://example.com:0/feed",
        "https://example.com:65536/feed",
    ],
)
def test_rejects_unsupported_feed_url(url: str):
    bad_feed = {
        "schema_version": "research-profile.v1",
        "name": "x",
        "topic": "x",
        "goal_file": "g.md",
        "sources": {"feeds": [url]},
    }
    with pytest.raises(ValueError, match=r"HTTPS|invalid port|between 1 and 65535|http or https"):
        ResearchProfile.model_validate(bad_feed)


@pytest.mark.parametrize("port", [443, 8443])
def test_accepts_feed_url_with_valid_explicit_port(port: int):
    profile = ResearchProfile.model_validate(
        {
            "schema_version": "research-profile.v1",
            "name": "x",
            "topic": "x",
            "goal_file": "g.md",
            "sources": {"feeds": [f"https://example.com:{port}/feed"]},
        }
    )

    assert profile.sources.feeds[0].url == f"https://example.com:{port}/feed"


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


@pytest.mark.parametrize(
    "source",
    [
        {"channel_id": "UC123456", "handle": "@Example"},
        {"channel_id": "UC123456", "url": "https://youtube.com/@Different"},
        {"handle": "@Example", "url": "https://youtube.com/@Different"},
    ],
)
def test_youtube_channel_rejects_ambiguous_identifiers(source: dict[str, str]) -> None:
    raw = _valid_profile(sources={"youtube_channels": [source]})

    with pytest.raises(ValueError, match="exactly one"):
        ResearchProfile.model_validate(raw)


def test_youtube_channel_rejects_non_http_url() -> None:
    """A YouTube channel url must be http or https."""
    raw = _valid_profile(sources={"youtube_channels": [{"url": "ftp://youtube.com/x"}]})
    with pytest.raises(ValueError, match="youtube channel url"):
        ResearchProfile.model_validate(raw)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch",
        "https://youtube.com/results",
        "https://youtube.com/embed/abc123",
        "https://youtube.com/arbitrary",
        "https://youtube.com/@Example/live",
        "https://youtube.com/channel/UC123456/extra",
        "https://youtube.com/@ab",
        "https://youtube.com/channel/not-a-channel",
        "https://user@youtube.com/@Example",
        "https://youtube.com:443/@Example",
        "https://youtube.com/@Example?view=1",
        "http://youtube.com/@Example",
    ],
)
def test_youtube_channel_rejects_noncanonical_url_paths(url: str) -> None:
    raw = _valid_profile(sources={"youtube_channels": [{"url": url}]})

    with pytest.raises(ValueError, match="youtube channel url"):
        ResearchProfile.model_validate(raw)


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/@Example",
        "https://youtube.com/@Example/videos",
        "https://youtube.com/@Example/shorts/",
        "https://youtube.com/channel/UC123456",
        "https://youtube.com/channel/UC123456/videos",
    ],
)
def test_youtube_channel_accepts_canonical_url_paths(url: str) -> None:
    raw = _valid_profile(sources={"youtube_channels": [{"url": url}]})

    profile = ResearchProfile.model_validate(raw)

    assert profile.sources.youtube_channels[0].url == url.rstrip("/")


@pytest.mark.parametrize(
    "source",
    [
        {"handle": "@ab"},
        {"handle": "@bad/path"},
        {"channel_id": "UCbad?value"},
        {"channel_id": "UC123"},
    ],
)
def test_youtube_channel_rejects_invalid_bounded_identifiers(source: dict[str, str]) -> None:
    raw = _valid_profile(sources={"youtube_channels": [source]})

    with pytest.raises(ValueError, match=r"youtube (handle|channel_id)"):
        ResearchProfile.model_validate(raw)


def test_rejects_domain_without_a_hostname() -> None:
    """A domain that resolves to no hostname is rejected."""
    raw = _valid_profile(sources={"domains": [".example.com"]})
    with pytest.raises(ValueError, match="hostname"):
        ResearchProfile.model_validate(raw)


@pytest.mark.parametrize(
    "domain",
    [
        "https://user@example.com",
        "example.com:443",
        "example.com?x=1",
        "127.0.0.1",
        "[::1]",
        "-bad.example",
        "bad_.example",
    ],
)
def test_rejects_ambiguous_or_non_dns_domains(domain: str) -> None:
    raw = _valid_profile(sources={"domains": [domain]})

    with pytest.raises(ValueError, match="domain"):
        ResearchProfile.model_validate(raw)


def test_rejects_invalid_profile_name() -> None:
    """A profile name that is not a lowercase slug is rejected."""
    raw = _valid_profile(name="Not A Slug")
    with pytest.raises(ValueError, match="lowercase slug"):
        ResearchProfile.model_validate(raw)


@pytest.mark.parametrize(
    "name",
    ["a.", "con", "nul", "com1", "lpt9", "con.profile"],
)
def test_rejects_profile_names_that_collide_on_windows(name: str) -> None:
    raw = _valid_profile(name=name)

    with pytest.raises(ValueError, match="canonical cross-platform"):
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
