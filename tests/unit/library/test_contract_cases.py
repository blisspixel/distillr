"""Generated contract tests for deterministic library helpers."""

from __future__ import annotations

import json
from pathlib import Path

import deal
import pytest
from hypothesis import strategies as st

from distill.library import paths
from distill.library.paths import (
    _is_single_path_component,
    apply_frontmatter,
    artifact_candidate_paths,
    artifact_filename,
    atomic_replace_json,
    atomic_replace_text,
    atomic_write_json,
    atomic_write_text,
    dump_frontmatter,
    extract_frontmatter,
    find_artifact,
    workspace_output_path,
)
from distill.library.wikilinks import parse_wiki_links

_FRONTMATTER_KEYS = st.from_regex(r"[A-Za-z][A-Za-z0-9 _.-]{0,20}", fullmatch=True)
_FRONTMATTER_TEXT = st.text(max_size=80)
_FRONTMATTER_VALUES = st.one_of(
    st.none(),
    st.just(""),
    _FRONTMATTER_TEXT,
    st.integers(min_value=-1000, max_value=1000),
    st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.lists(st.text(max_size=24), min_size=0, max_size=4),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=12),
        values=st.text(max_size=24),
        min_size=0,
        max_size=4,
    ),
)


def test_workspace_output_path_uses_sibling_output_and_confines_filename(tmp_path: Path) -> None:
    library_dir = tmp_path / "workspace" / "library"

    result = workspace_output_path(library_dir, "../../escape.md")

    assert result.parent == tmp_path / "workspace" / "output"
    assert result.name == "-..-escape.md"


_FRONTMATTER = st.dictionaries(
    keys=_FRONTMATTER_KEYS,
    values=_FRONTMATTER_VALUES,
    min_size=0,
    max_size=8,
)
_BODY_TEXT = st.text(max_size=240)
_MARKDOWN_CONTENT = st.one_of(
    _BODY_TEXT,
    _BODY_TEXT.map(lambda body: f'---\ntitle: "Existing"\ntags: ["old"]\n---\n\n{body}'),
)

_SLUG = st.from_regex(r"[a-z][a-z0-9-]{0,24}", fullmatch=True)
_SUFFIX = st.sampled_from(["Insights", "Synthesis", "Report", "Brief"])
_DISPLAY = st.text(
    alphabet=st.characters(blacklist_characters="]"),
    min_size=1,
    max_size=60,
).filter(lambda value: bool(value.strip()))
_WIKI_LINK = st.builds(
    lambda slug, suffix, display: f"[[{slug}_{suffix}|{display}]]",
    _SLUG,
    _SUFFIX,
    _DISPLAY,
)
_WIKI_CONTENT = st.lists(
    st.one_of(st.text(max_size=60), _WIKI_LINK),
    min_size=0,
    max_size=8,
).map("\n".join)


def test_frontmatter_unicode_line_separators_are_value_text() -> None:
    """Unicode line separators inside values must not split frontmatter rows."""
    dumped = dump_frontmatter({"a": ["\x85", "\u2028", "\u2029", ":"]})

    assert "a" in extract_frontmatter(dumped)


def test_dump_frontmatter_generated_contract_cases() -> None:
    """Generated frontmatter dictionaries must emit parseable fenced blocks."""
    for case in deal.cases(
        dump_frontmatter,
        count=80,
        kwargs={"frontmatter": _FRONTMATTER},
        check_types=False,
        seed=20260634,
    ):
        case()


def test_apply_frontmatter_generated_contract_cases() -> None:
    """Generated frontmatter patches must preserve the documented merge shape."""
    for case in deal.cases(
        apply_frontmatter,
        count=80,
        kwargs={"content": _MARKDOWN_CONTENT, "frontmatter": _FRONTMATTER},
        check_types=False,
        seed=20260635,
    ):
        case()


def test_path_component_predicate_rejects_unsafe_segments() -> None:
    """The path-component predicate is the direct confinement boundary."""
    assert _is_single_path_component("safe-name")
    assert not _is_single_path_component("")
    assert not _is_single_path_component("a/b")
    assert not _is_single_path_component(r"a\b")
    assert not _is_single_path_component("a\x00b")


def test_artifact_filename_defaults_to_markdown_and_strips_extension_dot() -> None:
    """Artifact filenames default to markdown and normalize extension spelling."""
    assert artifact_filename("ai c1", "synthesis") == "ai_c1_Synthesis.md"
    assert artifact_filename("ai c1", "transcript", extension=".txt") == "ai_c1_Transcript.txt"


def test_artifact_candidate_paths_expose_reader_compatibility_order(tmp_path: Path) -> None:
    candidates = artifact_candidate_paths(
        tmp_path,
        "transcript",
        identity="ai c1",
        extension="txt",
    )

    assert [candidate.name for candidate in candidates] == [
        "ai_c1_Transcript.txt",
        "ai_c1_transcript.txt",
        "transcript.txt",
    ]


def test_find_artifact_default_returns_modern_markdown_path(tmp_path: Path) -> None:
    """Missing artifacts still resolve to the canonical markdown target path."""
    topic = tmp_path / "topic"

    assert find_artifact(topic, "synthesis", identity="ai c1") == topic / "ai_c1_Synthesis.md"


def test_dump_frontmatter_uses_lowercase_boolean_scalars() -> None:
    """Boolean frontmatter uses the lowercase YAML scalar spelling."""
    dumped = dump_frontmatter({"enabled": True, "disabled": False})

    assert "enabled: true" in dumped
    assert "disabled: false" in dumped


def test_apply_frontmatter_preserves_existing_list_fields_as_lists() -> None:
    """Carried-forward inline list fields remain YAML lists after merging."""
    content = dump_frontmatter({"title": "T", "tags": ["a", "b"]}) + "\n\nBody"

    patched = apply_frontmatter(content, {"generated_at": "2026-06-28T00:00:00"})

    assert 'tags: ["a", "b"]' in patched


def test_atomic_write_text_creates_parent_and_replaces_atomically(tmp_path: Path) -> None:
    """Atomic writes create nested parents, replace content, and clean temp files."""
    target = tmp_path / "nested" / "note.md"

    atomic_write_text(target, "first")
    atomic_write_text(target, "second")

    assert target.read_text(encoding="utf-8") == "second"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_atomic_write_json_is_compliant_and_refuses_non_finite(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "metadata.json"

    atomic_write_json(target, {"count": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"count": 2}
    assert target.read_text(encoding="utf-8").endswith("\n")
    with pytest.raises(ValueError, match="JSON compliant"):
        atomic_write_json(target, {"count": float("nan")})


def test_atomic_replace_helpers_publish_without_persistent_lock_files(tmp_path: Path) -> None:
    text_path = tmp_path / "scratch" / "result.txt"
    json_path = tmp_path / "scratch" / "result.json"

    atomic_replace_text(text_path, "result")
    atomic_replace_json(json_path, {"ok": True})

    assert text_path.read_text(encoding="utf-8") == "result"
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"ok": True}
    assert list(text_path.parent.glob(".distill-write-*.lock")) == []


def test_atomic_write_text_retries_transient_replace_sharing_conflict(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "note.md"
    target.write_text("old", encoding="utf-8")
    original_replace = Path.replace
    attempts = 0

    def transient_replace(source: Path, destination: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("reader still owns a sharing handle")
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", transient_replace)
    monkeypatch.setattr(paths, "_is_retryable_replace_error", lambda _error: True)
    monkeypatch.setattr(paths.time, "sleep", lambda _seconds: None)

    atomic_write_text(target, "new")

    assert attempts == 3
    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(".note.md.*.tmp")) == []


def test_atomic_write_text_bounds_replace_retry_and_cleans_temp(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "note.md"
    target.write_text("old", encoding="utf-8")

    def blocked_replace(_source: Path, _destination: Path) -> Path:
        raise PermissionError("reader never released its sharing handle")

    monkeypatch.setattr(Path, "replace", blocked_replace)
    monkeypatch.setattr(paths, "_is_retryable_replace_error", lambda _error: True)
    monkeypatch.setattr(paths, "_ATOMIC_REPLACE_TIMEOUT_SECONDS", 0.0)

    with pytest.raises(PermissionError, match="reader never released"):
        atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".note.md.*.tmp")) == []


def test_parse_wiki_links_generated_contract_cases() -> None:
    """Generated wiki-link content must satisfy render and parse round-trips."""
    for case in deal.cases(
        parse_wiki_links,
        count=100,
        kwargs={"content": _WIKI_CONTENT},
        check_types=False,
        seed=20260636,
    ):
        case()
