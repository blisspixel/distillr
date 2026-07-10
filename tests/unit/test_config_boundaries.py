"""Boundary and compatibility tests for configuration normalization."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from distill import config as config_module
from distill.config import DistillConfig


@pytest.mark.parametrize("value", [None, "", "metered", "no_metered"])
def test_cost_mode_rejects_unknown_values(value: object) -> None:
    with pytest.raises(ValueError, match="cost_mode must be one of"):
        config_module._normalize_cost_mode(value)


@pytest.mark.parametrize("value", [True, False])
def test_float_input_rejects_booleans(value: bool) -> None:
    with pytest.raises(ValueError, match="threshold must be a number"):
        config_module._float_input_text(value, field_name="threshold")


def test_float_input_rejects_non_scalar_objects() -> None:
    with pytest.raises(ValueError, match="threshold must be a number"):
        config_module._float_input_text(object(), field_name="threshold")


@pytest.mark.parametrize(
    ("normalizer", "value", "message"),
    [
        (config_module._positive_float, True, "must be a positive number"),
        (config_module._positive_float, float("inf"), "must be finite"),
        (config_module._non_negative_float, object(), "must be a non-negative number"),
        (config_module._non_negative_float, float("nan"), "must be finite"),
        (config_module._non_negative_float, -0.01, "greater than or equal to 0"),
    ],
)
def test_float_policy_rejects_invalid_values(normalizer, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalizer(value, field_name="threshold")


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "cannot be empty"),
        ("site batch", "cannot contain whitespace"),
        ("report/unsafe", "invalid character"),
    ],
)
def test_workflow_budget_key_rejects_unsafe_names(value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        config_module._normalize_workflow_budget_key(value)


def test_workflow_budget_parser_accepts_none_mapping_and_empty_chunks() -> None:
    assert config_module.parse_cost_workflow_budgets(None) == {}
    assert config_module.parse_cost_workflow_budgets(MappingProxyType({" REPORT ": "2.5"})) == {
        "report": 2.5
    }
    assert config_module.parse_cost_workflow_budgets("report=1,, site=2, ") == {
        "report": 1.0,
        "site": 2.0,
    }


def test_unreadable_checkout_marker_falls_back_to_user_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    package = repo / "distill"
    package.mkdir(parents=True)
    marker = repo / "pyproject.toml"
    marker.write_text('[project]\nname = "distillr"\n', encoding="utf-8")
    home = tmp_path / "home"
    original_read_text = Path.read_text

    def read_text(path: Path, *args, **kwargs) -> str:
        if path == marker:
            raise OSError("marker became unreadable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))

    assert config_module._default_library_dir(package) == home / ".distill" / "library"


def test_deprecated_path_helpers_delegate_with_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    from distill.library import paths

    calls: list[tuple[object, ...]] = []

    def sanitize(value: str) -> str:
        calls.append(("sanitize", value))
        return "safe"

    def slugify(title: str, video_id: str, *, max_len: int) -> str:
        calls.append(("slugify", title, video_id, max_len))
        return "slug"

    def site_name(url: str) -> str:
        calls.append(("site", url))
        return "site"

    monkeypatch.setattr(paths, "sanitize_path_component", sanitize)
    monkeypatch.setattr(paths, "slugify_title", slugify)
    monkeypatch.setattr(paths, "site_name_from_url", site_name)

    with pytest.deprecated_call(match="sanitize_path_component"):
        assert config_module.sanitize_path_component("A/B") == "safe"
    with pytest.deprecated_call(match="slugify_title"):
        assert config_module.slugify_title("A Report", "id", max_len=20) == "slug"
    with pytest.deprecated_call(match="site_name_from_url"):
        assert config_module.site_name_from_url("https://docs.example.com/path") == "site"

    assert calls == [
        ("sanitize", "A/B"),
        ("slugify", "A Report", "id", 20),
        ("site", "https://docs.example.com/path"),
    ]


def test_site_and_paper_paths_are_sanitized_under_topic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for field_name in DistillConfig.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)
    monkeypatch.chdir(tmp_path)
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    unsafe_topic = r"..\..\outside"
    topic_dir = config.topic_dir(unsafe_topic)

    assert config.site_dir(unsafe_topic, "docs/example") == topic_dir / "sites" / "docs-example"
    assert config.site_pages_dir(unsafe_topic, "docs/example") == (
        topic_dir / "sites" / "docs-example" / "pages"
    )
    page_dir = config.site_page_dir(unsafe_topic, "docs/example", "Page One!", "p1")
    assert page_dir == (topic_dir / "sites" / "docs-example" / "pages" / "page-one_p1")
    assert config.papers_dir(unsafe_topic) == topic_dir / "papers"
    paper_dir = config.paper_dir(unsafe_topic, "Paper One!", "arxiv-1")
    assert paper_dir == (topic_dir / "papers" / "paper-one_arxiv1")
    topics_root = config.topics_dir().resolve(strict=False)
    page_dir.resolve(strict=False).relative_to(topics_root)
    paper_dir.resolve(strict=False).relative_to(topics_root)
    assert len(config.site_page_dir(unsafe_topic, "docs/example", "A" * 120).name) == 70
    assert len(config.paper_dir(unsafe_topic, "A" * 120).name) == 70
