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
from typing import Any

from distill.process_security import package_install_context, resolve_executable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HardwareProfile:
    """Detected hardware capabilities."""

    gpu_type: str  # "nvidia" | "amd" | "intel" | "apple_silicon" | "none"
    gpu_name: str  # Detected GPU or unified-memory device label
    vram_gb: float  # GPU VRAM or unified memory; 0.0 when not measured
    system_ram_gb: float
    is_container: bool
    # Whether ``vram_gb`` is a real measurement. Without this, 0.0 meant both
    # "this machine has no GPU" and "we could not measure one", and every
    # consumer read it as the former -- so an AMD or Intel box was told its
    # models would "run on CPU (slow)" while the GPU was doing all the work.
    vram_measured: bool = False
    # Whether ``vram_gb`` is a hard capacity ceiling. True only for dedicated
    # VRAM reported by a vendor tool. False for unified memory (Apple) and for
    # an integrated GPU's BIOS carve-out, where the real budget is shared system
    # RAM -- a 780M reports 2GB and happily runs an 18GB model. Treating a
    # carve-out as a ceiling would wrongly disqualify every usable model.
    vram_is_dedicated: bool = False

    @property
    def has_gpu(self) -> bool:
        """True when an accelerator was positively identified."""
        return self.gpu_type not in ("none", "")

    @property
    def vram_capacity_gb(self) -> float:
        """Hard VRAM ceiling in GB, or 0.0 when no ceiling can be asserted."""
        return self.vram_gb if (self.vram_measured and self.vram_is_dedicated) else 0.0


def detect_hardware() -> HardwareProfile:
    """Detect GPU and RAM on Linux, macOS, and Windows, for any GPU vendor.

    Probe order is most-precise-first: a vendor tool that reports real VRAM
    (nvidia-smi, rocm-smi), then Apple unified memory, then platform-native
    adapter enumeration that at least identifies the vendor. A GPU we can name
    but not size is reported with ``vram_measured=False`` rather than 0.0-as-no-GPU.
    """
    system_ram_gb = _get_system_ram()
    is_container = _is_container()

    detected = (
        _detect_nvidia()
        or _detect_amd()
        or _detect_apple_silicon(system_ram_gb)
        or _detect_platform_adapter()
    )
    if detected is None:
        return HardwareProfile(
            gpu_type="none",
            gpu_name="",
            vram_gb=0.0,
            system_ram_gb=system_ram_gb,
            is_container=is_container,
            vram_measured=False,
            vram_is_dedicated=False,
        )

    gpu_type, gpu_name, vram_gb, dedicated = detected
    return HardwareProfile(
        gpu_type=gpu_type,
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        system_ram_gb=system_ram_gb,
        is_container=is_container,
        vram_measured=vram_gb > 0.0,
        vram_is_dedicated=dedicated,
    )


def _detect_apple_silicon(system_ram_gb: float) -> tuple[str, str, float, bool] | None:
    """Apple Silicon shares one memory pool, so unified RAM is the GPU budget."""
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None
    # Unified memory: a budget shared with the OS, never a dedicated ceiling.
    return ("apple_silicon", _get_apple_chip_name(), system_ram_gb, False)


def _detect_amd() -> tuple[str, str, float, bool] | None:
    """Detect an AMD GPU via rocm-smi, then the Linux amdgpu sysfs node."""
    vram_gb = _amd_vram_from_rocm_smi()
    if vram_gb is not None:
        return ("amd", "AMD GPU", vram_gb, True)
    sysfs = _amd_vram_from_sysfs()
    if sysfs is not None:
        return ("amd", "AMD GPU", sysfs, True)
    return None


def _amd_vram_from_rocm_smi() -> float | None:
    """Total VRAM in GB from ``rocm-smi``, or None when unavailable."""
    try:
        result = _run_tool("rocm-smi", "--showmeminfo", "vram", "--csv")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        for field in line.split(","):
            value = field.strip()
            # rocm-smi reports total VRAM in bytes; take the first plausible one.
            if value.isdigit() and int(value) > 1024**3:
                return round(int(value) / (1024**3), 1)
    return None


def _amd_vram_from_sysfs() -> float | None:
    """Total VRAM in GB from the Linux amdgpu sysfs node, or None."""
    try:
        cards = sorted(Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"))
    except OSError:
        return None
    for card in cards:
        try:
            total = int(card.read_text().strip())
        except (OSError, ValueError):
            continue
        if total > 0:
            return round(total / (1024**3), 1)
    return None


def _detect_platform_adapter() -> tuple[str, str, float, bool] | None:
    """Name the display adapter using a platform-native, dependency-free source.

    This is the catch-all that keeps non-NVIDIA machines from reporting "no GPU":
    it identifies the vendor even when no vendor CLI is installed.
    """
    if platform.system() == "Windows":
        return _detect_windows_adapter()
    return None


def _detect_windows_adapter() -> tuple[str, str, float, bool] | None:
    """Read the display adapter from the Windows driver registry.

    Uses ``winreg`` rather than spawning WMIC/PowerShell: no subprocess, no
    deprecated tooling, and ``qwMemorySize`` reports true VRAM above the 4GB
    ceiling that ``Win32_VideoController.AdapterRAM`` truncates at.
    """
    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows
        return None

    display_class = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, display_class) as root:
            for index in range(64):
                try:
                    subkey_name = winreg.EnumKey(root, index)
                except OSError:
                    break
                if not subkey_name.isdigit():
                    continue
                adapter = _read_windows_adapter(winreg, root, subkey_name)
                if adapter is not None:
                    return adapter
    except OSError:
        return None
    return None


def _read_windows_adapter(
    winreg: Any, root: Any, subkey_name: str
) -> tuple[str, str, float, bool] | None:
    """Return (vendor, name, vram_gb, dedicated) for one adapter registry subkey."""
    try:
        with winreg.OpenKey(root, subkey_name) as subkey:
            try:
                description = str(winreg.QueryValueEx(subkey, "DriverDesc")[0])
            except OSError:
                return None
            vram_gb = 0.0
            for value_name in (
                "HardwareInformation.qwMemorySize",
                "HardwareInformation.MemorySize",
            ):
                try:
                    raw = winreg.QueryValueEx(subkey, value_name)[0]
                except OSError:
                    continue
                if isinstance(raw, bytes):
                    raw = int.from_bytes(raw, "little")
                try:
                    vram_gb = round(int(raw) / (1024**3), 1)
                except (TypeError, ValueError):
                    vram_gb = 0.0
                if vram_gb > 0:
                    break
            # The registry cannot distinguish dedicated VRAM from an integrated
            # carve-out, so never assert this figure as a capacity ceiling.
            return (_vendor_from_name(description), description, vram_gb, False)
    except OSError:
        return None


def _vendor_from_name(name: str) -> str:
    """Map an adapter description to a vendor tag."""
    lowered = name.casefold()
    if "nvidia" in lowered or "geforce" in lowered or "quadro" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered:
        return "amd"
    if "intel" in lowered or "arc" in lowered:
        return "intel"
    return "none"


def _detect_nvidia() -> tuple[str, str, float, bool] | None:
    """Detect NVIDIA GPU via nvidia-smi. Returns (type, name, vram_gb, dedicated) or None."""
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

        return ("nvidia", gpu_name, round(vram_gb, 1), True)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _get_apple_chip_name() -> str:
    """Get Apple Silicon chip name via sysctl."""
    try:
        result = _run_tool("sysctl", "-n", "machdep.cpu.brand_string")
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "Apple Silicon"
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
        return 0.0
    return 0.0


def _get_macos_ram() -> float:
    """Get macOS system RAM via sysctl hw.memsize."""
    try:
        result = _run_tool("sysctl", "-n", "hw.memsize")
        if result.returncode == 0 and result.stdout.strip():
            bytes_val = int(result.stdout.strip())
            return round(bytes_val / (1024**3), 1)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        return 0.0
    return 0.0


def _run_tool(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run an external diagnostic tool after resolving it from PATH."""
    executable = resolve_executable(name)
    if executable is None:
        raise FileNotFoundError(name)
    trusted_cwd, child_env = package_install_context()
    return subprocess.run(
        [executable, *args],
        capture_output=True,
        text=True,
        timeout=5,
        cwd=trusted_cwd,
        env=child_env,
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
        return 0.0
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
        return False

    return False
