"""Tests for distill.ingestors.local.extract."""

from __future__ import annotations

import sys
import types
from io import BytesIO
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


def test_size_check_reports_stat_failure(monkeypatch):
    from distill.ingestors.local import extract as ex

    class _UnreadablePath:
        name = "unreadable.txt"

        def stat(self):
            raise OSError("metadata unavailable")

    with pytest.raises(LocalExtractionError, match="metadata unavailable"):
        ex._check_size(_UnreadablePath())


def test_bounded_text_read_rejects_stream_larger_than_stat_cap(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    path = tmp_path / "growing.txt"
    path.write_bytes(b"abcd")
    monkeypatch.setattr(ex, "_MAX_FILE_BYTES", 3)

    with pytest.raises(LocalExtractionError, match="exceeds"):
        ex._read_text(path)


def test_text_read_wraps_open_failure():
    from distill.ingestors.local import extract as ex

    class _UnreadablePath:
        name = "unreadable.txt"

        def open(self, *args, **kwargs):
            raise OSError("read unavailable")

    with pytest.raises(LocalExtractionError, match="read unavailable"):
        ex._read_text(_UnreadablePath())


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


def test_rejects_benign_name_symlink_to_secret(tmp_path: Path):
    secret = _write(tmp_path / ".provider-secret", "API_KEY=must-not-ingest")
    alias = tmp_path / "research-notes.txt"
    try:
        alias.symlink_to(secret)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")

    with pytest.raises(LocalExtractionError, match="unsafe"):
        extract_local_document(alias)


def test_rejects_hard_link_alias_to_secret(tmp_path: Path):
    secret = _write(tmp_path / ".provider-secret", "API_KEY=must-not-ingest")
    alias = tmp_path / "research-notes.txt"
    try:
        alias.hardlink_to(secret)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")

    with pytest.raises(LocalExtractionError, match="unsafe"):
        extract_local_document(alias)


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


def test_pdf_stops_extracting_pages_at_requested_character_limit(tmp_path, monkeypatch):
    from distill.ingestors.local import _pdf_worker

    calls: list[int] = []

    class _Page:
        def __init__(self, index: int) -> None:
            self.index = index

        def extract_text(self) -> str:
            calls.append(self.index)
            return "abcdefghij"

    fake_pypdf = types.SimpleNamespace(
        PdfReader=lambda path: types.SimpleNamespace(pages=[_Page(1), _Page(2)])
    )
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)
    pdf = tmp_path / "bounded.pdf"
    pdf.write_bytes(b"%PDF-fake")
    output = tmp_path / "bounded.txt"

    _pdf_worker.extract_pdf_to_file(pdf, output, max_chars=8, max_pages=200)

    assert output.read_text(encoding="utf-8") == "abcdefgh"
    assert calls == [1]


def test_pdf_character_limit_applies_after_leading_whitespace(tmp_path, monkeypatch):
    from distill.ingestors.local import _pdf_worker

    class _Page:
        def extract_text(self) -> str:
            return " " * 10 + "VISIBLE"

    monkeypatch.setitem(
        sys.modules,
        "pypdf",
        types.SimpleNamespace(PdfReader=lambda path: types.SimpleNamespace(pages=[_Page()])),
    )
    pdf = tmp_path / "leading-space.pdf"
    pdf.write_bytes(b"%PDF-fake")
    output = tmp_path / "leading-space.txt"

    _pdf_worker.extract_pdf_to_file(pdf, output, max_chars=7, max_pages=1)

    assert output.read_text(encoding="utf-8") == "VISIBLE"


def test_pdf_worker_skips_blank_pages_and_separates_text_pages(tmp_path, monkeypatch):
    from distill.ingestors.local import _pdf_worker

    class _Page:
        def __init__(self, text: str) -> None:
            self.text = text

        def extract_text(self) -> str:
            return self.text

    pages = [_Page("  "), _Page("first"), _Page("second")]
    monkeypatch.setitem(
        sys.modules,
        "pypdf",
        types.SimpleNamespace(PdfReader=lambda path: types.SimpleNamespace(pages=pages)),
    )
    output = tmp_path / "pages.txt"

    _pdf_worker.extract_pdf_to_file(tmp_path / "source.pdf", output, max_chars=20, max_pages=3)

    assert output.read_text(encoding="utf-8") == "first\n\nsecond"


def test_pdf_has_default_extracted_text_limit(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    limits: list[int] = []

    def run_worker(path: Path, limit: int, max_pages: int) -> str:
        limits.append(limit)
        assert max_pages == 200
        return "abcde"

    monkeypatch.setattr(ex, "_run_pdf_worker", run_worker)
    monkeypatch.setattr(ex, "_MAX_PDF_TEXT_CHARS", 5)
    pdf = tmp_path / "default-bounded.pdf"
    pdf.write_bytes(b"%PDF-fake")

    doc = extract_local_document(pdf)

    assert doc.text == "abcde"
    assert limits == [5]


def test_pdf_zero_character_limit_skips_worker(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    monkeypatch.setattr(
        ex,
        "extract_pdf_text_bounded",
        lambda *args, **kwargs: pytest.fail("worker should not run"),
    )

    assert ex._extract_pdf(tmp_path / "unused.pdf", max_chars=0) == ""


def test_pdf_worker_main_validates_handshake_and_runs(monkeypatch, tmp_path):
    from distill.ingestors.local import _pdf_worker

    source = tmp_path / "source.pdf"
    destination = tmp_path / "destination.txt"
    calls: list[tuple[Path, Path, int, int]] = []
    monkeypatch.setattr(
        _pdf_worker,
        "extract_pdf_to_file",
        lambda source, destination, *, max_chars, max_pages: calls.append(
            (source, destination, max_chars, max_pages)
        ),
    )
    monkeypatch.setattr(_pdf_worker, "_set_posix_memory_limit", lambda limit: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", str(source), str(destination), "12", "3", "1024"],
    )
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=BytesIO(b"0")))
    assert _pdf_worker.main() == 3
    assert calls == []

    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=BytesIO(b"1")))
    assert _pdf_worker.main() == 0
    assert calls == [(source, destination, 12, 3)]


def test_pdf_worker_main_rejects_bad_arguments(monkeypatch):
    from distill.ingestors.local import _pdf_worker

    monkeypatch.setattr(sys, "argv", ["worker"])
    assert _pdf_worker.main() == 2


def test_pdf_worker_main_reports_invalid_numeric_limits(monkeypatch, capsys):
    from distill.ingestors.local import _pdf_worker

    monkeypatch.setattr(sys, "argv", ["worker", "in", "out", "bad", "1", "1"])

    assert _pdf_worker.main() == 1
    assert "ValueError" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("current_limits", "infinity", "expected"),
    [
        ((-1, -1), -1, (512, -1)),
        ((256, 1024), -1, (256, 1024)),
        ((-1, 128), -1, (128, 128)),
        ((-1, -1), 2**63 - 1, (512, -1)),
    ],
)
def test_pdf_worker_applies_bounded_posix_memory_limit(
    monkeypatch, current_limits, infinity, expected
):
    from distill.ingestors.local import _pdf_worker

    observed = []
    fake_resource = types.SimpleNamespace(
        RLIMIT_AS=9,
        RLIM_INFINITY=infinity,
        getrlimit=lambda resource: current_limits,
        setrlimit=lambda resource, limits: observed.append((resource, limits)),
    )
    monkeypatch.setattr(_pdf_worker.os, "name", "posix")
    monkeypatch.setitem(sys.modules, "resource", fake_resource)

    _pdf_worker._set_posix_memory_limit(512)

    assert observed == [(9, expected)]


class _FakeWorkerStdin:
    def write(self, data: bytes) -> None:
        assert data == b"1"

    def close(self) -> None:
        return None


class _FakeWorkerProcess:
    def __init__(self, *, returncode: int, stderr: bytes = b"", times_out: bool = False):
        self.stdin = _FakeWorkerStdin()
        self.returncode = returncode
        self.stderr = stderr
        self.times_out = times_out
        self.killed = False

    def communicate(self, timeout=None):
        if timeout is not None and self.times_out and not self.killed:
            raise __import__("subprocess").TimeoutExpired("worker", timeout)
        return b"", self.stderr

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def poll(self):
        return self.returncode if self.killed else None


def test_pdf_worker_preserves_user_site_packages_with_safe_path(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    process = _FakeWorkerProcess(returncode=0)
    commands: list[list[str]] = []

    def start_worker(argv, **kwargs):
        commands.append(argv)
        return process

    monkeypatch.setattr(ex.subprocess, "Popen", start_worker)
    monkeypatch.setattr(ex, "_assign_windows_memory_job", lambda process, limit: None)

    assert ex.extract_pdf_text_bounded(tmp_path / "empty.pdf", max_chars=100, max_pages=2) == ""
    assert commands[0][:4] == [
        sys.executable,
        "-P",
        "-m",
        "distill.ingestors.local._pdf_worker",
    ]
    assert "-I" not in commands[0]


def test_pdf_worker_nonzero_exit_reports_bounded_stderr(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    process = _FakeWorkerProcess(returncode=1, stderr=b"parser failed")
    monkeypatch.setattr(ex.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ex, "_assign_windows_memory_job", lambda process, limit: None)

    with pytest.raises(LocalExtractionError, match="parser failed"):
        ex.extract_pdf_text_bounded(tmp_path / "bad.pdf", max_chars=100, max_pages=2)


def test_pdf_worker_nonzero_exit_without_stderr_reports_status(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    process = _FakeWorkerProcess(returncode=7)
    monkeypatch.setattr(ex.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ex, "_assign_windows_memory_job", lambda process, limit: None)

    with pytest.raises(LocalExtractionError, match=r"status 7$"):
        ex.extract_pdf_text_bounded(tmp_path / "bad.pdf", max_chars=100, max_pages=2)


def test_pdf_worker_timeout_kills_process(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    process = _FakeWorkerProcess(returncode=0, times_out=True)
    monkeypatch.setattr(ex.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ex, "_assign_windows_memory_job", lambda process, limit: None)

    with pytest.raises(LocalExtractionError, match="timed out"):
        ex.extract_pdf_text_bounded(tmp_path / "slow.pdf", max_chars=100, max_pages=2)

    assert process.killed is True


def test_pdf_worker_missing_control_pipe_kills_process(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    process = _FakeWorkerProcess(returncode=0)
    process.stdin = None
    monkeypatch.setattr(ex.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ex, "_assign_windows_memory_job", lambda process, limit: None)

    with pytest.raises(LocalExtractionError, match="control pipe"):
        ex.extract_pdf_text_bounded(tmp_path / "bad.pdf", max_chars=100, max_pages=2)

    assert process.killed is True


def test_pdf_worker_returns_empty_when_worker_writes_no_output(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    process = _FakeWorkerProcess(returncode=0)
    monkeypatch.setattr(ex.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ex, "_assign_windows_memory_job", lambda process, limit: None)

    assert ex.extract_pdf_text_bounded(tmp_path / "blank.pdf", max_chars=100, max_pages=2) == ""


def test_pdf_worker_returns_bounded_worker_output(tmp_path, monkeypatch):
    from distill.ingestors.local import extract as ex

    process = _FakeWorkerProcess(returncode=0)

    def start_worker(argv, **kwargs):
        Path(argv[5]).write_text("abcdef", encoding="utf-8")
        return process

    monkeypatch.setattr(ex.subprocess, "Popen", start_worker)
    monkeypatch.setattr(ex, "_assign_windows_memory_job", lambda process, limit: None)

    assert ex.extract_pdf_text_bounded(tmp_path / "bounded.pdf", max_chars=4, max_pages=2) == "abcd"


def test_non_windows_pdf_worker_needs_no_job_object(monkeypatch):
    from distill.ingestors.local import extract as ex

    monkeypatch.setattr(ex.os, "name", "posix")

    assert ex._assign_windows_memory_job(_FakeWorkerProcess(returncode=0), 1024) is None


class _FakeKernelFunction:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class _FakeKernel32:
    def __init__(self):
        self.CreateJobObjectW = _FakeKernelFunction(91)
        self.SetInformationJobObject = _FakeKernelFunction(True)
        self.AssignProcessToJobObject = _FakeKernelFunction(True)
        self.CloseHandle = _FakeKernelFunction(True)


def test_windows_pdf_worker_job_boundary_is_portably_exercised(monkeypatch):
    import ctypes

    from distill.ingestors.local import extract as ex

    kernel32 = _FakeKernel32()
    process = _FakeWorkerProcess(returncode=0)
    process._handle = 73
    monkeypatch.setattr(ex.os, "name", "nt")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: kernel32, raising=False)

    job_handle = ex._assign_windows_memory_job(process, 4096)

    assert job_handle == 91
    assert len(kernel32.SetInformationJobObject.calls) == 1
    assert len(kernel32.AssignProcessToJobObject.calls) == 1
    ex._close_windows_job(job_handle)
    assert len(kernel32.CloseHandle.calls) == 1


def test_windows_pdf_worker_skips_posix_limit(monkeypatch):
    from distill.ingestors.local import _pdf_worker

    monkeypatch.setattr(_pdf_worker.os, "name", "nt")

    assert _pdf_worker._set_posix_memory_limit(512) is None


@pytest.mark.parametrize(("max_chars", "max_pages"), [(0, 1), (1, 0)])
def test_bounded_pdf_extraction_rejects_empty_limits(tmp_path, max_chars, max_pages):
    from distill.ingestors.local.extract import extract_pdf_text_bounded

    assert (
        extract_pdf_text_bounded(tmp_path / "unused.pdf", max_chars=max_chars, max_pages=max_pages)
        == ""
    )


def test_pdf_worker_process_runs_under_resource_boundary(tmp_path):
    from pypdf import PdfWriter

    pdf = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf.open("wb") as output:
        writer.write(output)

    with pytest.raises(LocalExtractionError, match="No extractable text"):
        extract_local_document(pdf)
