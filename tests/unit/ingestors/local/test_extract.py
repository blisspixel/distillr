"""Tests for distill.ingestors.local.extract."""

from __future__ import annotations

from pathlib import Path

import pytest

from distill.ingestors.local import LocalExtractionError, extract_local_document


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_extract_local_document_rejects_oversized_file(tmp_path, monkeypatch):
    # DoS guard: refuse a file over the byte cap before reading it into memory.
    from distill.ingestors.local import extract as ex

    monkeypatch.setattr(ex, "_MAX_FILE_BYTES", 16)
    big = _write(tmp_path / "big.txt", "a" * 64)
    with pytest.raises(LocalExtractionError, match="cap"):
        extract_local_document(big)


def test_markdown(tmp_path: Path):
    p = _write(tmp_path / "My_Article.md", "# Heading\n\nBody text about RoPE.")
    doc = extract_local_document(p)
    assert doc.kind == "markdown"
    assert doc.title == "My Article"
    assert "Body text" in doc.text


def test_plain_text_and_no_extension(tmp_path: Path):
    assert extract_local_document(_write(tmp_path / "notes.txt", "hello")).kind == "text"
    assert extract_local_document(_write(tmp_path / "README", "hi")).kind == "text"


def test_rejects_extensionless_dotfile(tmp_path: Path):
    # A config/secret dotfile (.env) must not be captured into the library via
    # the extensionless text route.
    p = _write(tmp_path / ".env", "SECRET=abc123")
    with pytest.raises(LocalExtractionError, match="dotfile"):
        extract_local_document(p)


def test_html_strips_script_and_style(tmp_path: Path):
    p = _write(
        tmp_path / "page.html",
        "<html><head><style>x{}</style></head>"
        "<body><h1>Title</h1><p>Hello <b>world</b></p><script>bad()</script></body></html>",
    )
    doc = extract_local_document(p)
    assert doc.kind == "html"
    assert "Title" in doc.text and "Hello world" in doc.text
    assert "bad()" not in doc.text
    assert "<" not in doc.text  # tags stripped


def test_unsupported_extension(tmp_path: Path):
    with pytest.raises(LocalExtractionError, match="Unsupported"):
        extract_local_document(_write(tmp_path / "thing.xyz", "data"))


def test_missing_file(tmp_path: Path):
    with pytest.raises(LocalExtractionError, match="Not a file"):
        extract_local_document(tmp_path / "nope.md")


def test_empty_file(tmp_path: Path):
    with pytest.raises(LocalExtractionError, match="No extractable text"):
        extract_local_document(_write(tmp_path / "empty.md", "   \n  "))


def test_truncation(tmp_path: Path):
    p = _write(tmp_path / "big.txt", "x " * 5000)
    doc = extract_local_document(p, max_chars=100)
    assert len(doc.text) <= 100
