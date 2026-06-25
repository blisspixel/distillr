# pyright: strict
"""Hardware detection for local inference recommendations.

Detects GPU type, VRAM, system RAM, and container environment to inform
model selection and context window configuration.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HardwareProfile:
    """Detected hardware capabilities."""

    gpu_type: str  # "nvidia", "apple_silicon", "none"
    gpu_name: str  # Detected GPU or unified-memory device label
    vram_gb: float  # GPU VRAM or unified memory
    system_ram_gb: float
    is_container: bool


def detect_hardware() -> HardwareProfile:
    """Detect GPU and RAM.

    - NVIDIA: parse nvidia-smi output
    - Apple Silicon: parse sysctl output
    - Container: check /.dockerenv or cgroup
    """
    gpu_type = "none"
    gpu_name = ""
    vram_gb = 0.0
    system_ram_gb = _get_system_ram()
    is_container = _is_container()

    # Try NVIDIA first
    nvidia = _detect_nvidia()
    if nvidia:
        gpu_type, gpu_name, vram_gb = nvidia
    elif platform.system() == "Darwin" and platform.machine() == "arm64":
        gpu_type = "apple_silicon"
        gpu_name = _get_apple_chip_name()
        vram_gb = system_ram_gb  # Unified memory

    return HardwareProfile(
        gpu_type=gpu_type,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        system_ram_gb=system_ram_gb,
        is_container=is_container,
    )


def _detect_nvidia() -> tuple[str, str, float] | None:
    """Detect NVIDIA GPU via nvidia-smi. Returns (gpu_type, gpu_name, vram_gb) or None."""
    try:
        result = _run_tool(
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        )
        if result.returncode != 0:
            return None

        line = result.stdout.strip().split("\n")[0]
        if not line:
            return None

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            return None

        gpu_name = parts[0]
        try:
            vram_mb = float(parts[1])
            vram_gb = vram_mb / 1024.0
        except ValueError:
            vram_gb = 0.0

        return ("nvidia", gpu_name, round(vram_gb, 1))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _get_apple_chip_name() -> str:
    """Get Apple Silicon chip name via sysctl."""
    try:
        result = _run_tool("sysctl", "-n", "machdep.cpu.brand_string")
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return "Apple Silicon"


def _get_system_ram() -> float:
    """Get system RAM in GB (macOS, Linux, and Windows)."""
    system = platform.system()
    if system == "Darwin":
        return _get_macos_ram()
    if system == "Linux":
        return _get_linux_ram()
    if system == "Windows":
        return _get_windows_ram()
    return 0.0


def _get_windows_ram() -> float:
    """Get Windows physical RAM in GB via GlobalMemoryStatusEx (no extra deps)."""
    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = (
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            )

        stat = _MemoryStatusEx()
        stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
            return round(stat.ullTotalPhys / (1024**3), 1)
    except (OSError, AttributeError, ValueError):
        pass
    return 0.0


def _get_macos_ram() -> float:
    """Get macOS system RAM via sysctl hw.memsize."""
    try:
        result = _run_tool("sysctl", "-n", "hw.memsize")
        if result.returncode == 0 and result.stdout.strip():
            bytes_val = int(result.stdout.strip())
            return round(bytes_val / (1024**3), 1)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return 0.0


def _run_tool(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run an external diagnostic tool after resolving it from PATH."""
    executable = shutil.which(name)
    if executable is None:
        raise FileNotFoundError(name)
    return subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        timeout=5,
    )


def _get_linux_ram() -> float:
    """Get Linux system RAM from /proc/meminfo."""
    try:
        meminfo = Path("/proc/meminfo").read_text()
        for line in meminfo.split("\n"):
            if line.startswith("MemTotal:"):
                parts = line.split()
                if len(parts) >= 2:
                    kb = int(parts[1])
                    return round(kb / (1024**2), 1)
    except (OSError, ValueError):
        pass
    return 0.0


def _is_container() -> bool:
    """Detect if running inside a Docker container."""
    # Check for /.dockerenv
    if Path("/.dockerenv").exists():
        return True

    # Check cgroup for docker/container references
    try:
        cgroup = Path("/proc/1/cgroup").read_text()
        if "docker" in cgroup or "containerd" in cgroup or "kubepods" in cgroup:
            return True
    except OSError:
        pass

    return False
