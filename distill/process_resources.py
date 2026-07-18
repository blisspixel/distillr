"""Cross-platform child-process time, memory, and tree cleanup controls."""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import IO

import psutil

__all__ = [
    "BoundedByteTail",
    "ProcessBudgetExceeded",
    "assign_windows_memory_job",
    "close_windows_job",
    "process_tree_rss_bytes",
    "start_bounded_pipe_drain",
    "terminate_process_tree",
    "wait_for_process_budget",
]


class BoundedByteTail:
    """Retain a fixed-size byte tail while another thread drains a pipe."""

    def __init__(self, limit: int) -> None:
        if limit <= 0:
            raise ValueError("diagnostic byte limit must be positive")
        self._limit = limit
        self._data = bytearray()
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self._lock:
            self._data.extend(chunk)
            overflow = len(self._data) - self._limit
            if overflow > 0:
                del self._data[:overflow]

    def bytes(self) -> bytes:
        with self._lock:
            return bytes(self._data)


def start_bounded_pipe_drain(
    stream: IO[bytes],
    *,
    limit: int,
    thread_name: str,
) -> tuple[BoundedByteTail, threading.Thread]:
    """Drain a binary pipe to EOF while retaining only a fixed diagnostic tail."""

    tail = BoundedByteTail(limit)

    def drain() -> None:
        try:
            while chunk := stream.read(8_192):
                tail.append(chunk)
        except (OSError, ValueError):
            return

    thread = threading.Thread(
        target=drain,
        daemon=True,
        name=thread_name,
    )
    thread.start()
    return tail, thread


@dataclass(frozen=True)
class ProcessBudgetExceeded(RuntimeError):
    """Raised when a child tree exceeds its elapsed-time or memory budget."""

    kind: str
    limit: int | float
    observed: int | float

    def __str__(self) -> str:
        return (
            f"child process {self.kind} budget exceeded "
            f"(limit={self.limit:g}, observed={self.observed:g})"
        )


def process_tree_rss_bytes(pid: int) -> int:
    """Return a conservative RSS sum for one live process and its descendants."""

    try:
        root = psutil.Process(pid)
        processes = [root, *root.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0
    total = 0
    for process in processes:
        try:
            total += int(process.memory_info().rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def wait_for_process_budget(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    memory_limit_bytes: int,
    poll_seconds: float = 0.025,
) -> int:
    """Wait for a child while enforcing aggregate tree RSS and elapsed time."""

    if timeout_seconds <= 0 or memory_limit_bytes <= 0 or poll_seconds <= 0:
        raise ValueError("process budgets must be positive")
    started = time.monotonic()
    deadline = started + timeout_seconds
    peak_rss = 0
    while process.poll() is None:
        rss = process_tree_rss_bytes(process.pid)
        peak_rss = max(peak_rss, rss)
        if rss > memory_limit_bytes:
            raise ProcessBudgetExceeded("memory", memory_limit_bytes, rss)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProcessBudgetExceeded(
                "time",
                timeout_seconds,
                time.monotonic() - started,
            )
        try:
            process.wait(timeout=min(poll_seconds, remaining))
        except subprocess.TimeoutExpired:
            continue
    return peak_rss


def terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill a child and every descendant still attributable to it."""

    try:
        root = psutil.Process(process.pid)
        descendants = root.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        descendants = []
        root = None
    for child in reversed(descendants):
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if root is not None:
        with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
            root.kill()
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def assign_windows_memory_job(
    process: subprocess.Popen[bytes],
    *,
    process_memory_bytes: int | None = None,
    job_memory_bytes: int | None = None,
) -> int | None:
    """Assign a Windows child to a kill-on-close memory-limited Job Object."""

    if os.name != "nt":
        return None
    if process_memory_bytes is None and job_memory_bytes is None:
        raise ValueError("a Windows process or job memory limit is required")
    if process_memory_bytes is not None and process_memory_bytes <= 0:
        raise ValueError("process memory limit must be positive")
    if job_memory_bytes is not None and job_memory_bytes <= 0:
        raise ValueError("job memory limit must be positive")

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
    limit_flags = 0x2000
    if process_memory_bytes is not None:
        limit_flags |= 0x100
        information.ProcessMemoryLimit = process_memory_bytes
    if job_memory_bytes is not None:
        limit_flags |= 0x200
        information.JobMemoryLimit = job_memory_bytes
    information.BasicLimitInformation.LimitFlags = limit_flags
    process_handle = getattr(process, "_handle", None)
    if not isinstance(process_handle, int):
        kernel32.CloseHandle(job)
        raise OSError("Python did not expose the child process handle")
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


def close_windows_job(job_handle: int | None) -> None:
    """Close a Windows Job Object handle, killing any remaining members."""

    if job_handle is None:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(wintypes.HANDLE(job_handle))
