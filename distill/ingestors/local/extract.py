"""Extract analyzable text from a local document.

The local-file counterpart to the network ingestors: given a path to a PDF,
Markdown file, plain-text file, or a saved/clipped HTML article, return the
plain text the analysis pipeline can reason over. Pure extraction -- no LLM, no
network. Mirrors the surrogate-sanitization the arXiv PDF path already uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

__all__ = [
    "LocalDocument",
    "LocalExtractionError",
    "extract_local_document",
]

_PDF_EXTS = frozenset({".pdf"})
_MARKDOWN_EXTS = frozenset({".md", ".markdown", ".mdown"})
_HTML_EXTS = frozenset({".html", ".htm"})
_TEXT_EXTS = frozenset({".txt", ".text", ".rst", ""})

# Default cap, mirroring the arXiv paper extractor's 100K-char ceiling so a huge
# document does not blow the analysis prompt's context budget.
_DEFAULT_MAX_CHARS = 100_000

# Hard byte/page caps so a hostile or accidentally-huge local file can't exhaust
# memory: the whole file is read into RAM before the char cap applies, so bound
# the read itself. Mirrors the arXiv extractor's page limit for PDFs.
_MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB
_PDF_PAGE_LIMIT = 50


class LocalExtractionError(RuntimeError):
    """Raised when a local file cannot be read or yields no usable text."""


@dataclass(slots=True)
class LocalDocument:
    """Extracted text from a local file, with a coarse kind and a display title."""

    text: str
    kind: str  # "pdf" | "markdown" | "text" | "html"
    title: str


def extract_local_document(path: Path, *, max_chars: int = _DEFAULT_MAX_CHARS) -> LocalDocument:
    """Extract text from ``path``, dispatching on file extension.

    Supports PDF (``.pdf``), Markdown (``.md`` / ``.markdown``), plain text
    (``.txt`` and extensionless), and saved HTML (``.html`` / ``.htm``). Raises
    :class:`LocalExtractionError` for a missing file, an unsupported type, or a
    document that yields no extractable text.
    """
    if not path.is_file():
        raise LocalExtractionError(f"Not a file: {path}")

    ext = path.suffix.lower()
    # Refuse extensionless dotfiles (.env, .netrc, ...): these are config/secret
    # files, not research content, and the extensionless "" text route would
    # otherwise capture their contents into the library.
    if not ext and path.name.startswith("."):
        raise LocalExtractionError(
            f"Refusing to ingest dotfile {path.name!r} (config/secret files are "
            "not research content). Give it a supported extension to ingest it."
        )
    _check_size(path)
    title = _title_from_name(path)

    if ext in _PDF_EXTS:
        text, kind = _extract_pdf(path), "pdf"
    elif ext in _HTML_EXTS:
        text, kind = _html_to_text(_read_text(path)), "html"
    elif ext in _MARKDOWN_EXTS:
        text, kind = _read_text(path), "markdown"
    elif ext in _TEXT_EXTS:
        text, kind = _read_text(path), "text"
    else:
        raise LocalExtractionError(
            f"Unsupported file type {ext or '(no extension)'!r} for {path.name}. "
            "Supported: .pdf, .md, .txt, .html."
        )

    text = _sanitize_surrogates(text).strip()
    if not text:
        raise LocalExtractionError(f"No extractable text in {path.name}.")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return LocalDocument(text=text, kind=kind, title=title)


def _check_size(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise LocalExtractionError(f"Could not stat {path.name}: {exc}") from exc
    if size > _MAX_FILE_BYTES:
        raise LocalExtractionError(
            f"{path.name} is {size} bytes, over the {_MAX_FILE_BYTES}-byte ingest cap."
        )


def _title_from_name(path: Path) -> str:
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return stem or path.name


def _read_text(path: Path) -> str:
    # Bounded read: the st_size pre-check covers regular files, but a FIFO /
    # /proc / symlinked path can report a small size and stream unbounded bytes,
    # so cap the read itself too.
    try:
        with path.open("rb") as fh:
            raw = fh.read(_MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise LocalExtractionError(f"Could not read {path.name}: {exc}") from exc
    if len(raw) > _MAX_FILE_BYTES:
        raise LocalExtractionError(f"{path.name} exceeds the {_MAX_FILE_BYTES}-byte ingest cap.")
    return raw.decode("utf-8", errors="replace")


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is a hard dependency
        raise LocalExtractionError("pypdf is required to read PDF files.") from exc
    try:
        reader = PdfReader(str(path))
        parts = [(page.extract_text() or "").strip() for page in reader.pages[:_PDF_PAGE_LIMIT]]
    except Exception as exc:
        raise LocalExtractionError(f"Could not extract PDF text from {path.name}: {exc}") from exc
    return "\n\n".join(part for part in parts if part)


def _sanitize_surrogates(text: str) -> str:
    """Drop lone surrogate codepoints pypdf occasionally emits (un-encodable)."""
    return text.encode("utf-8", "ignore").decode("utf-8", "ignore")


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text: collect text, drop script/style, keep block breaks."""

    _SKIP = frozenset({"script", "style", "head", "noscript", "template"})
    _BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        # Collapse runs of blank lines and trailing spaces.
        return re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", joined).strip()


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception as exc:
        raise LocalExtractionError(f"Could not parse HTML: {exc}") from exc
    return parser.text()
