"""Extract analyzable text from a local document.

The local-file counterpart to the network ingestors: given a path to a PDF,
Markdown file, plain-text file, or a saved/clipped HTML article, return the
plain text the analysis pipeline can reason over. Pure extraction -- no LLM, no
network. Mirrors the surrogate-sanitization the arXiv PDF path already uses.
"""

from __future__ import annotations

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
_PDF_PAGE_LIMIT = 200
_MAX_PDF_TEXT_CHARS = 2_000_000
_PDF_WORKER_MEMORY_BYTES = 256 * 1024 * 1024
_PDF_WORKER_TIMEOUT_SECONDS = 60


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
    decoded = raw.decode("utf-8", errors="replace")
    if extension in _HTML_EXTS:
        return _html_to_text(decoded), "html"
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


def extract_pdf_text_bounded(path: Path, *, max_chars: int, max_pages: int) -> str:
    """Extract bounded PDF text in an isolated worker with resource limits."""

    if max_chars <= 0 or max_pages <= 0:
        return ""
    return _run_pdf_worker(path, max_chars, max_pages)


def _run_pdf_worker(path: Path, limit: int, max_pages: int) -> str:
    with tempfile.TemporaryDirectory(prefix="distill-pdf-") as temp_dir:
        output_path = Path(temp_dir) / "extracted.txt"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
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
            creationflags=creationflags,
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
                    _, stderr = process.communicate(timeout=_PDF_WORKER_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as exc:
                    process.kill()
                    process.communicate()
                    raise LocalExtractionError(
                        f"PDF text extraction timed out after "
                        f"{_PDF_WORKER_TIMEOUT_SECONDS} seconds."
                    ) from exc
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.communicate()
                raise
        finally:
            _close_windows_job(job_handle)

        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[:200]
            suffix = f": {detail}" if detail else ""
            raise LocalExtractionError(
                f"Could not extract PDF text from {path.name}; worker exited "
                f"with status {process.returncode}{suffix}"
            )
        if not output_path.is_file():
            return ""
        return _read_text(output_path)[:limit]


def _assign_windows_memory_job(process: subprocess.Popen[bytes], limit_bytes: int) -> int | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    information = _ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x100 | 0x2000
    information.ProcessMemoryLimit = limit_bytes
    process_handle = getattr(process, "_handle", None)
    if not isinstance(process_handle, int):
        kernel32.CloseHandle(job)
        raise OSError("Python did not expose the PDF worker process handle")
    if not kernel32.SetInformationJobObject(
        job,
        9,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ) or not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process_handle)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)
    return int(job)


def _close_windows_job(job_handle: int | None) -> None:
    if job_handle is None:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(wintypes.HANDLE(job_handle))


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


def html_to_text(html: str) -> str:
    """Public HTML-to-text reduction (also used by the newsletter adapter)."""
    return _html_to_text(html)
