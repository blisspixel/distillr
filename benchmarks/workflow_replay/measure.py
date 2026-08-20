# pyright: strict
"""Process RSS, digests, and source fingerprint for workflow replay."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import json
import math
import os
import platform
import sys
import sysconfig
import threading
import tomllib
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

MIN_P95_SAMPLES = 20


def json_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def nearest_rank(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _windows_rss_bytes() -> int:
    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD),
            ("page_fault_count", ctypes.wintypes.DWORD),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
    process = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
    return int(counters.working_set_size) if ok else 0


def current_rss_bytes() -> int:
    if sys.platform == "win32":
        return _windows_rss_bytes()
    statm = Path("/proc/self/statm")
    if statm.exists():
        try:
            resident_pages = int(statm.read_text(encoding="ascii").split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            pass
    try:
        import resource

        maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return maximum if sys.platform == "darwin" else maximum * 1024
    except (ImportError, OSError, ValueError):
        return 0


class PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.001) -> None:
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._samples = [current_rss_bytes()]
        self._thread = threading.Thread(target=self._sample, daemon=True)

    @property
    def baseline(self) -> int:
        return self._samples[0]

    def _sample(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._samples.append(current_rss_bytes())

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> int:
        self._stop.set()
        self._thread.join()
        self._samples.append(current_rss_bytes())
        return max(self._samples)


def project_version(source_root: Path) -> str:
    raw = tomllib.loads((source_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = raw.get("project")
    if not isinstance(project, dict):
        raise ValueError("benchmark pyproject has no project table")
    value = cast("Mapping[str, object]", project).get("version")
    if not isinstance(value, str) or not value:
        raise ValueError("benchmark pyproject has no project version")
    return value


def installed_distill_version() -> str:
    try:
        return version("distillr")
    except PackageNotFoundError:
        return ""


def source_fingerprint(source_root: Path) -> tuple[str, int]:
    root = source_root.resolve()
    candidates: set[Path] = set()
    for directory in (root / "distill", root / "benchmarks" / "workflow_replay"):
        if directory.is_dir():
            candidates.update(path for path in directory.rglob("*.py") if path.is_file())
    for name in ("pyproject.toml", "uv.lock"):
        path = root / name
        if path.is_file():
            candidates.add(path)
    if not candidates:
        raise ValueError(f"no replay source files found under {root}")
    digest = hashlib.sha256()
    for path in sorted(candidates, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest(), len(candidates)


def environment(source_root: Path) -> dict[str, Any]:
    fingerprint, source_files = source_fingerprint(source_root)
    project = project_version(source_root)
    installed = installed_distill_version()
    return {
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        "generated_at": datetime.now(UTC).isoformat(),
        "installed_distill_version": installed,
        "installed_distill_version_matches_project": installed == project,
        "operating_system": platform.system(),
        "platform_release": platform.release(),
        "processor": platform.processor(),
        "project_version": project,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "source_file_count": source_files,
        "source_fingerprint_kind": "normalized-source-tree-sha256",
        "source_fingerprint_sha256": fingerprint,
    }
