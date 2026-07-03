"""Tests for em-dash normalization at the artifact write boundary."""

from __future__ import annotations

from pathlib import Path

from distill.library.paths import normalize_dashes, write_markdown_artifact


def test_normalizes_em_dash_to_spaced_hyphen():
    assert normalize_dashes("a—b") == "a - b"
    assert normalize_dashes("a — b") == "a - b"  # collapses surrounding spaces
    assert (
        normalize_dashes("one route—domain adaptation—wins")
        == "one route - domain adaptation - wins"
    )


def test_leaves_ascii_and_en_dash_untouched():
    assert normalize_dashes("plain hyphen - stays") == "plain hyphen - stays"
    # An en-dash is not an em-dash, so a numeric range is left untouched.
    en_dash = chr(0x2013)
    assert normalize_dashes(f"range 5{en_dash}10") == f"range 5{en_dash}10"


def test_preserves_em_dash_inside_code_fence():
    out = normalize_dashes("prose—here\n```\ncode—line\n```\nafter—text")
    assert "prose - here" in out
    assert "code—line" in out  # the fenced snippet is left intact
    assert "after - text" in out


def test_write_normalizes_authored_prose(tmp_path: Path):
    path = write_markdown_artifact(tmp_path, "insights", "route A—route B\n", identity="x")
    text = path.read_text(encoding="utf-8")
    assert "—" not in text
    assert "route A - route B" in text


def test_write_preserves_dashes_in_source_capture(tmp_path: Path):
    # A receipt (captured source) keeps its punctuation for provenance fidelity.
    path = write_markdown_artifact(tmp_path, "content", "quoted source—as written\n", identity="x")
    assert "—" in path.read_text(encoding="utf-8")
