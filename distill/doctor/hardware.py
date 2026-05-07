# pyright: strict
"""Hardware detection for local inference recommendations.

Detects GPU type, VRAM, system RAM, and container environment to inform
model selection and context window configuration.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HardwareProfile:
    """Detected hardware capabilities."""

    gpu_type: str  # "nvidia", "apple_silicon", "none"
    gpu_name: str  # e.g., "RTX 4090", "M1 Pro"
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
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
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
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return "Apple Silicon"


def _get_system_ram() -> float:
    """Get system RAM in GB."""
    system = platform.system()
    if system == "Darwin":
        return _get_macos_ram()
    elif system == "Linux":
        return _get_linux_ram()
    return 0.0


def _get_macos_ram() -> float:
    """Get macOS system RAM via sysctl hw.memsize."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            bytes_val = int(result.stdout.strip())
            return round(bytes_val / (1024**3), 1)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return 0.0


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
