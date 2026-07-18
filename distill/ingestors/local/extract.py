"""Extract analyzable text from a local document.

The local-file counterpart to the network ingestors: given a path to a PDF,
Markdown file, plain-text file, or a saved/clipped HTML article, return the
plain text the analysis pipeline can reason over. Pure extraction -- no LLM, no
network. Mirrors the surrogate-sanitization the arXiv PDF path already uses.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from distill.library.confined import read_confined_bytes
from distill.process_resources import (
    ProcessBudgetExceeded,
    assign_windows_memory_job,
    close_windows_job,
    start_bounded_pipe_drain,
    terminate_process_tree,
    wait_for_process_budget,
)
from distill.process_security import package_install_context

__all__ = [
    "LocalDocument",
    "LocalExtractionError",
    "extract_local_document",
    "extract_pdf_text_bounded",
]

_PDF_EXTS = frozenset({".pdf"})
_MARKDOWN_EXTS = frozenset({".md", ".markdown", ".mdown"})
_HTML_EXTS = frozenset({".html", ".htm"})
_TEXT_EXTS = frozenset({".txt", ".text", ".rst", ""})

# Hard byte/page caps so a hostile or accidentally-huge local file can't exhaust
# memory. Analysis chunks long documents when the provider window requires it.
_MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB
HTML_WORKER_INPUT_BYTES = _MAX_FILE_BYTES
_PDF_PAGE_LIMIT = 200
_MAX_PDF_TEXT_CHARS = 2_000_000
_PDF_WORKER_MEMORY_BYTES = 256 * 1024 * 1024
_PDF_WORKER_TIMEOUT_SECONDS = 60
_PDF_WORKER_DIAGNOSTIC_BYTES = 4_096
_HTML_WORKER_MEMORY_BYTES = 192 * 1024 * 1024
_HTML_WORKER_TIMEOUT_SECONDS = 10.0
_HTML_WORKER_DIAGNOSTIC_BYTES = 4_096
_MAX_HTML_TEXT_CHARS = 2_000_000
_MAX_HTML_PARSE_EVENTS = 250_000
_MAX_HTML_PARSE_DEPTH = 512


class LocalExtractionError(RuntimeError):
    """Raised when a local file cannot be read or yields no usable text."""


@dataclass(slots=True)
class LocalDocument:
    """Extracted text from a local file, with a coarse kind and a display title."""

    text: str
    kind: str  # "pdf" | "markdown" | "text" | "html"
    title: str


def _read_local_snapshot(path: Path) -> bytes:
    try:
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        raise LocalExtractionError(f"Not a file: {path}") from exc
    except OSError as exc:
        raise LocalExtractionError(f"Could not inspect {path.name}: {exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise LocalExtractionError(f"Refusing unsafe local file path: {path}")
    if file_stat.st_size > _MAX_FILE_BYTES:
        raise LocalExtractionError(
            f"{path.name} is {file_stat.st_size} bytes, over the {_MAX_FILE_BYTES}-byte ingest cap."
        )
    raw = read_confined_bytes(path, path.parent, max_bytes=_MAX_FILE_BYTES)
    if raw is None:
        raise LocalExtractionError(f"Refusing unsafe or unreadable local file path: {path}")
    return raw


def _extract_snapshot(
    raw: bytes,
    extension: str,
    *,
    max_chars: int | None,
) -> tuple[str, str]:
    if extension in _PDF_EXTS:
        with tempfile.TemporaryDirectory(prefix="distill-pdf-input-") as temp_dir:
            snapshot = Path(temp_dir) / f"document{extension}"
            snapshot.write_bytes(raw)
            return _extract_pdf(snapshot, max_chars=max_chars), "pdf"
    if extension in _HTML_EXTS:
        return _extract_html_snapshot(raw, max_chars=max_chars), "html"
    decoded = raw.decode("utf-8", errors="replace")
    if extension in _MARKDOWN_EXTS:
        return decoded, "markdown"
    if extension in _TEXT_EXTS:
        return decoded, "text"
    raise LocalExtractionError(f"Unsupported local document extension: {extension}")


def extract_local_document(path: Path, *, max_chars: int | None = None) -> LocalDocument:
    """Extract text from ``path``, dispatching on file extension.

    Supports PDF (``.pdf``), Markdown (``.md`` / ``.markdown``), plain text
    (``.txt`` and extensionless), and saved HTML (``.html`` / ``.htm``). Raises
    :class:`LocalExtractionError` for a missing file, an unsupported type, or a
    document that yields no extractable text.
    """
    ext = path.suffix.lower()
    # Refuse extensionless dotfiles (.env, .netrc, ...): these are config/secret
    # files, not research content, and the extensionless "" text route would
    # otherwise capture their contents into the library.
    if not ext and path.name.startswith("."):
        raise LocalExtractionError(
            f"Refusing to ingest dotfile {path.name!r} (config/secret files are "
            "not research content). Give it a supported extension to ingest it."
        )
    if ext not in _PDF_EXTS | _HTML_EXTS | _MARKDOWN_EXTS | _TEXT_EXTS:
        raise LocalExtractionError(
            f"Unsupported file type {ext or '(no extension)'!r} for {path.name}. "
            "Supported: .pdf, .md, .txt, .html."
        )
    raw = _read_local_snapshot(path)
    title = _title_from_name(path)
    text, kind = _extract_snapshot(raw, ext, max_chars=max_chars)

    text = _sanitize_surrogates(text).strip()
    if not text:
        raise LocalExtractionError(f"No extractable text in {path.name}.")
    if max_chars is not None and len(text) > max_chars:
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


def _extract_pdf(path: Path, *, max_chars: int | None) -> str:
    """Extract PDF text in a timeout and memory-limited subprocess."""

    limit = _MAX_PDF_TEXT_CHARS
    if max_chars is not None:
        limit = min(limit, max(0, max_chars))
    if limit <= 0:
        return ""
    return extract_pdf_text_bounded(path, max_chars=limit, max_pages=_PDF_PAGE_LIMIT)


def extract_pdf_text_bounded(
    path: Path,
    *,
    max_chars: int,
    max_pages: int,
    timeout_seconds: float | None = None,
) -> str:
    """Extract bounded PDF text in an isolated worker with resource limits."""

    if max_chars <= 0 or max_pages <= 0:
        return ""
    timeout = _PDF_WORKER_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("PDF worker timeout must be a positive number")
    return _run_pdf_worker(path, max_chars, max_pages, min(timeout, _PDF_WORKER_TIMEOUT_SECONDS))


def _stop_pdf_worker(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()


def _extract_html_snapshot(raw: bytes, *, max_chars: int | None) -> str:
    limit = _MAX_HTML_TEXT_CHARS
    if max_chars is not None:
        limit = min(limit, max(0, max_chars))
    if limit <= 0:
        return ""
    with tempfile.TemporaryDirectory(prefix="distill-html-") as temp_dir:
        root = Path(temp_dir)
        input_path = root / "document.html"
        output_path = root / "extracted.txt"
        input_path.write_bytes(raw)
        trusted_cwd, child_env = package_install_context()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            [
                sys.executable,
                "-P",
                "-m",
                "distill.ingestors.local._html_worker",
                str(input_path),
                str(output_path),
                str(limit),
            ],
            cwd=trusted_cwd,
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        stderr_stream = process.stderr
        if stderr_stream is None:
            terminate_process_tree(process)
            raise LocalExtractionError("HTML worker did not expose a diagnostic pipe.")
        diagnostic_tail, diagnostic_thread = start_bounded_pipe_drain(
            stderr_stream,
            limit=_HTML_WORKER_DIAGNOSTIC_BYTES,
            thread_name="distill-html-diagnostics",
        )
        job_handle: int | None = None
        try:
            job_handle = assign_windows_memory_job(
                process,
                process_memory_bytes=_HTML_WORKER_MEMORY_BYTES,
            )
            worker_stdin = process.stdin
            if worker_stdin is None:
                raise LocalExtractionError("HTML worker did not expose a control pipe.")
            worker_stdin.write(b"1")
            worker_stdin.close()
            process.stdin = None
            wait_for_process_budget(
                process,
                timeout_seconds=_HTML_WORKER_TIMEOUT_SECONDS,
                memory_limit_bytes=_HTML_WORKER_MEMORY_BYTES,
            )
        except ProcessBudgetExceeded as exc:
            terminate_process_tree(process)
            raise LocalExtractionError(f"HTML parsing exceeded its {exc.kind} budget.") from exc
        except BaseException:
            terminate_process_tree(process)
            raise
        finally:
            close_windows_job(job_handle)
            diagnostic_thread.join(timeout=1)
            with contextlib.suppress(OSError):
                stderr_stream.close()
            diagnostic_thread.join(timeout=1)
        if process.returncode != 0:
            detail = diagnostic_tail.bytes().decode("utf-8", errors="replace").strip()[-200:]
            suffix = f": {detail}" if detail else ""
            raise LocalExtractionError(
                f"Could not parse local HTML; worker exited with status "
                f"{process.returncode}{suffix}"
            )
        output = read_confined_bytes(output_path, root, max_bytes=_MAX_HTML_TEXT_CHARS * 4)
        if output is None:
            return ""
        return output.decode("utf-8", errors="replace")[:limit]


def _run_pdf_worker(path: Path, limit: int, max_pages: int, timeout_seconds: float) -> str:
    with tempfile.TemporaryDirectory(prefix="distill-pdf-") as temp_dir:
        output_path = Path(temp_dir) / "extracted.txt"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        trusted_cwd, child_env = package_install_context()
        process = subprocess.Popen(
            [
                sys.executable,
                "-P",
                "-m",
                "distill.ingestors.local._pdf_worker",
                str(path.resolve()),
                str(output_path),
                str(limit),
                str(max_pages),
                str(_PDF_WORKER_MEMORY_BYTES),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=trusted_cwd,
            env=child_env,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        stderr_stream = process.stderr
        if stderr_stream is None:
            process.kill()
            process.wait()
            raise LocalExtractionError("PDF worker did not expose a diagnostic pipe.")
        diagnostic_tail, diagnostic_thread = start_bounded_pipe_drain(
            stderr_stream,
            limit=_PDF_WORKER_DIAGNOSTIC_BYTES,
            thread_name="distill-pdf-diagnostics",
        )
        job_handle: int | None = None
        try:
            try:
                job_handle = _assign_windows_memory_job(process, _PDF_WORKER_MEMORY_BYTES)
                worker_stdin = process.stdin
                if worker_stdin is None:
                    raise LocalExtractionError("PDF worker did not expose a control pipe.")
                worker_stdin.write(b"1")
                worker_stdin.close()
                process.stdin = None
                try:
                    process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    _stop_pdf_worker(process)
                    raise LocalExtractionError(
                        f"PDF text extraction timed out after {timeout_seconds:g} seconds."
                    ) from exc
            except BaseException:
                _stop_pdf_worker(process)
                raise
        finally:
            _close_windows_job(job_handle)
            diagnostic_thread.join(timeout=1)
            with contextlib.suppress(OSError):
                stderr_stream.close()
            diagnostic_thread.join(timeout=1)

        if process.returncode != 0:
            detail = diagnostic_tail.bytes().decode("utf-8", errors="replace").strip()[-200:]
            suffix = f": {detail}" if detail else ""
            raise LocalExtractionError(
                f"Could not extract PDF text from {path.name}; worker exited "
                f"with status {process.returncode}{suffix}"
            )
        if not output_path.is_file():
            return ""
        return _read_text(output_path)[:limit]


def _assign_windows_memory_job(process: subprocess.Popen[bytes], limit_bytes: int) -> int | None:
    return assign_windows_memory_job(process, process_memory_bytes=limit_bytes)


def _close_windows_job(job_handle: int | None) -> None:
    close_windows_job(job_handle)


def _sanitize_surrogates(text: str) -> str:
    """Drop lone surrogate codepoints pypdf occasionally emits (un-encodable)."""
    return text.encode("utf-8", "ignore").decode("utf-8", "ignore")


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text: collect text, drop script/style, keep block breaks."""

    _SKIP = frozenset({"script", "style", "head", "noscript", "template"})
    _BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})
    _VOID = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(
        self,
        *,
        max_chars: int = _MAX_HTML_TEXT_CHARS,
        max_events: int = _MAX_HTML_PARSE_EVENTS,
        max_depth: int = _MAX_HTML_PARSE_DEPTH,
    ) -> None:
        if min(max_chars, max_events, max_depth) <= 0:
            raise ValueError("HTML parser budgets must be positive")
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._depth = 0
        self._events = 0
        self._chars = 0
        self._max_chars = max_chars
        self._max_events = max_events
        self._max_depth = max_depth

    def _record_event(self) -> None:
        self._events += 1
        if self._events > self._max_events:
            raise _HTMLParseLimit

    def _append(self, value: str) -> None:
        remaining = self._max_chars - self._chars
        if remaining <= 0:
            raise _HTMLParseLimit
        fragment = value[:remaining]
        self._chunks.append(fragment)
        self._chars += len(fragment)
        if len(fragment) < len(value):
            raise _HTMLParseLimit

    def handle_starttag(self, tag: str, attrs: object) -> None:
        self._record_event()
        if tag not in self._VOID:
            self._depth += 1
            if self._depth > self._max_depth:
                raise _HTMLParseLimit
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        self._record_event()
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._append("\n")
        if tag not in self._VOID:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        self._record_event()
        if self._skip_depth == 0 and data.strip():
            self._append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        # Collapse runs of blank lines and trailing spaces.
        return re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", joined).strip()


class _HTMLParseLimit(Exception):
    """Internal signal that returns the safely retained HTML prefix."""


def _html_to_text(html: str, *, max_chars: int = _MAX_HTML_TEXT_CHARS) -> str:
    parser = _TextExtractor(max_chars=max_chars)
    try:
        parser.feed(html)
    except _HTMLParseLimit:
        return parser.text()
    except Exception as exc:
        raise LocalExtractionError(f"Could not parse HTML: {exc}") from exc
    return parser.text()


def html_to_text(html: str, *, max_chars: int = _MAX_HTML_TEXT_CHARS) -> str:
    """Public HTML-to-text reduction (also used by the newsletter adapter)."""
    return _html_to_text(html, max_chars=max_chars)
