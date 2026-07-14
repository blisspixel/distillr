# pyright: strict
"""Memory-limited subprocess worker for local PDF text extraction."""

from __future__ import annotations

import os
import sys
from itertools import islice
from pathlib import Path


def _bounded_resource_limits(
    soft: int,
    hard: int,
    infinity: int,
    limit_bytes: int,
) -> tuple[int, int]:
    hard_is_unlimited = hard == infinity or hard < 0
    soft_is_unlimited = soft == infinity or soft < 0
    maximum_soft = limit_bytes if hard_is_unlimited else min(hard, limit_bytes)
    bounded_soft = maximum_soft if soft_is_unlimited else min(soft, maximum_soft)
    bounded_hard = maximum_soft if hard_is_unlimited else hard
    return bounded_soft, bounded_hard


def _darwin_virtual_size_bytes() -> int:
    import ctypes

    class _ProcTaskInfo(ctypes.Structure):
        _fields_ = [
            ("pti_virtual_size", ctypes.c_uint64),
            ("pti_resident_size", ctypes.c_uint64),
            ("pti_total_user", ctypes.c_uint64),
            ("pti_total_system", ctypes.c_uint64),
            ("pti_threads_user", ctypes.c_uint64),
            ("pti_threads_system", ctypes.c_uint64),
            ("pti_policy", ctypes.c_int32),
            ("pti_faults", ctypes.c_int32),
            ("pti_pageins", ctypes.c_int32),
            ("pti_cow_faults", ctypes.c_int32),
            ("pti_messages_sent", ctypes.c_int32),
            ("pti_messages_received", ctypes.c_int32),
            ("pti_syscalls_mach", ctypes.c_int32),
            ("pti_syscalls_unix", ctypes.c_int32),
            ("pti_csw", ctypes.c_int32),
            ("pti_threadnum", ctypes.c_int32),
            ("pti_numrunning", ctypes.c_int32),
            ("pti_priority", ctypes.c_int32),
        ]

    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    libproc.proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    libproc.proc_pidinfo.restype = ctypes.c_int
    task_info = _ProcTaskInfo()
    task_info_size = ctypes.sizeof(task_info)
    bytes_read = libproc.proc_pidinfo(
        os.getpid(),
        4,  # PROC_PIDTASKINFO
        0,
        ctypes.byref(task_info),
        task_info_size,
    )
    if bytes_read != task_info_size or task_info.pti_virtual_size <= 0:
        error_code = ctypes.get_errno()
        raise OSError(error_code, "could not measure Darwin worker address space")
    return int(task_info.pti_virtual_size)


def _set_posix_memory_limit(limit_bytes: int) -> None:
    if os.name == "nt":
        return
    import resource

    def apply(resource_kind: int, requested_limit: int) -> None:
        soft, hard = resource.getrlimit(resource_kind)
        limits = _bounded_resource_limits(
            soft,
            hard,
            resource.RLIM_INFINITY,
            requested_limit,
        )
        resource.setrlimit(resource_kind, limits)

    try:
        apply(resource.RLIMIT_AS, limit_bytes)
    except ValueError:
        if sys.platform != "darwin":
            raise
        # Darwin rejects a total address-space ceiling below the interpreter's
        # existing system mappings. Measure that trusted pre-parser baseline,
        # then keep the requested allocation headroom kernel-enforced.
        apply(resource.RLIMIT_AS, _darwin_virtual_size_bytes() + limit_bytes)


def extract_pdf_to_file(
    source: Path,
    destination: Path,
    *,
    max_chars: int,
    max_pages: int,
) -> None:
    """Incrementally extract bounded page text to ``destination``."""

    from pypdf import PdfReader

    reader = PdfReader(str(source))
    extracted_chars = 0
    wrote_page = False
    with destination.open("w", encoding="utf-8", errors="ignore", newline="\n") as output:
        for page in islice(reader.pages, max_pages):
            separator_chars = 2 if wrote_page else 0
            remaining = max_chars - extracted_chars - separator_chars
            if remaining <= 0:
                break
            page_text = page.extract_text() or ""
            start = next(
                (index for index, character in enumerate(page_text) if not character.isspace()),
                len(page_text),
            )
            bounded_text = page_text[start : start + remaining].rstrip()
            if not bounded_text:
                continue
            if wrote_page:
                output.write("\n\n")
            output.write(bounded_text)
            wrote_page = True
            extracted_chars += separator_chars + len(bounded_text)


def main() -> int:
    if len(sys.argv) != 6:
        return 2
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    try:
        max_chars = int(sys.argv[3])
        max_pages = int(sys.argv[4])
        memory_limit = int(sys.argv[5])
        _set_posix_memory_limit(memory_limit)
        if sys.stdin.buffer.read(1) != b"1":
            return 3
        extract_pdf_to_file(
            source,
            destination,
            max_chars=max_chars,
            max_pages=max_pages,
        )
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
