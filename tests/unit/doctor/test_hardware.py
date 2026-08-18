"""Unit tests for distill.doctor.hardware — hardware detection with mocked subprocess."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from distill.doctor import hardware as hardware_mod
from distill.doctor.hardware import (
    HardwareProfile,
    _detect_amd,
    _detect_nvidia,
    _detect_windows_adapter,
    _get_apple_chip_name,
    _get_linux_ram,
    _get_macos_ram,
    _get_system_ram,
    _get_windows_ram,
    _is_container,
    _run_tool,
    _vendor_from_name,
    detect_hardware,
)


class TestDetectNvidia:
    """Tests for NVIDIA GPU detection via nvidia-smi."""

    def test_nvidia_detected_with_valid_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "NVIDIA Test GPU, 24564\n"

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="nvidia-smi"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _detect_nvidia()

        assert result is not None
        gpu_type, gpu_name, vram_gb, dedicated = result
        assert dedicated is True  # nvidia-smi reports a real dedicated ceiling
        assert gpu_type == "nvidia"
        assert gpu_name == "NVIDIA Test GPU"
        assert vram_gb == pytest.approx(24.0, abs=0.1)

    def test_nvidia_not_found(self) -> None:
        with patch("distill.doctor.hardware.resolve_executable", return_value=None):
            result = _detect_nvidia()
        assert result is None

    def test_nvidia_smi_nonzero_return(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="nvidia-smi"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _detect_nvidia()
        assert result is None

    def test_nvidia_smi_timeout(self) -> None:
        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="nvidia-smi"),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5)),
        ):
            result = _detect_nvidia()
        assert result is None

    def test_nvidia_empty_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="nvidia-smi"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _detect_nvidia()
        assert result is None

    def test_nvidia_malformed_csv_returns_none(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "NVIDIA Test GPU\n"

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="nvidia-smi"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _detect_nvidia()

        assert result is None

    def test_nvidia_bad_memory_reports_zero_vram(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "NVIDIA Test GPU, not-a-number\n"

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="nvidia-smi"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _detect_nvidia()

        assert result == ("nvidia", "NVIDIA Test GPU", 0.0, True)


class TestAppleChipName:
    """Tests for Apple Silicon chip name detection."""

    def test_apple_chip_detected(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Apple Test Chip\n"

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="sysctl"),
            patch("subprocess.run", return_value=mock_result),
        ):
            name = _get_apple_chip_name()
        assert name == "Apple Test Chip"

    def test_apple_chip_fallback(self) -> None:
        with patch("distill.doctor.hardware.resolve_executable", return_value=None):
            name = _get_apple_chip_name()
        assert name == "Apple Silicon"

    def test_apple_chip_empty_output_falls_back(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n"

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="sysctl"),
            patch("subprocess.run", return_value=mock_result),
        ):
            name = _get_apple_chip_name()

        assert name == "Apple Silicon"


class TestSystemRam:
    """Tests for system RAM detection."""

    def test_macos_ram(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        # 16 GB in bytes
        mock_result.stdout = "17179869184\n"

        with (
            patch("platform.system", return_value="Darwin"),
            patch("distill.doctor.hardware.resolve_executable", return_value="sysctl"),
            patch("subprocess.run", return_value=mock_result),
        ):
            ram = _get_system_ram()
        assert ram == pytest.approx(16.0, abs=0.1)

    def test_linux_ram(self) -> None:
        meminfo = "MemTotal:       16384000 kB\nMemFree:        8192000 kB\n"
        with (
            patch("platform.system", return_value="Linux"),
            patch("pathlib.Path.read_text", return_value=meminfo),
        ):
            ram = _get_system_ram()
        assert ram == pytest.approx(15.6, abs=0.2)

    def test_windows_ram(self) -> None:
        # Windows is now supported; _get_system_ram routes to _get_windows_ram.
        with (
            patch("platform.system", return_value="Windows"),
            patch("distill.doctor.hardware._get_windows_ram", return_value=32.0),
        ):
            ram = _get_system_ram()
        assert ram == pytest.approx(32.0, abs=0.1)

    def test_unknown_os(self) -> None:
        with patch("platform.system", return_value="Plan9"):
            ram = _get_system_ram()
        assert ram == 0.0

    def test_macos_ram_invalid_value_returns_zero(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not-an-int\n"

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="sysctl"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _get_macos_ram() == 0.0

    def test_macos_ram_empty_output_returns_zero(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n"

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="sysctl"),
            patch("subprocess.run", return_value=mock_result),
        ):
            assert _get_macos_ram() == 0.0

    def test_linux_ram_without_memtotal_returns_zero(self) -> None:
        with patch("pathlib.Path.read_text", return_value="MemFree: 8192000 kB\n"):
            assert _get_linux_ram() == 0.0

    def test_linux_ram_short_memtotal_returns_zero(self) -> None:
        with patch("pathlib.Path.read_text", return_value="MemTotal:\n"):
            assert _get_linux_ram() == 0.0

    def test_linux_ram_invalid_memtotal_returns_zero(self) -> None:
        with patch("pathlib.Path.read_text", return_value="MemTotal: nope kB\n"):
            assert _get_linux_ram() == 0.0

    def test_windows_ram_success_uses_global_memory_status(self, monkeypatch) -> None:
        import ctypes

        def global_memory_status_ex(pointer) -> int:
            pointer._obj.ullTotalPhys = 16 * 1024**3
            return 1

        monkeypatch.setattr(
            ctypes,
            "windll",
            SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=global_memory_status_ex)),
            raising=False,
        )

        assert _get_windows_ram() == 16.0

    def test_windows_ram_failed_status_returns_zero(self, monkeypatch) -> None:
        import ctypes

        monkeypatch.setattr(
            ctypes,
            "windll",
            SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=lambda _ptr: 0)),
            raising=False,
        )

        assert _get_windows_ram() == 0.0

    def test_windows_ram_os_error_returns_zero(self, monkeypatch) -> None:
        import ctypes

        def global_memory_status_ex(_pointer) -> int:
            raise OSError("denied")

        monkeypatch.setattr(
            ctypes,
            "windll",
            SimpleNamespace(kernel32=SimpleNamespace(GlobalMemoryStatusEx=global_memory_status_ex)),
            raising=False,
        )

        assert _get_windows_ram() == 0.0


class TestContainerDetection:
    """Tests for container environment detection."""

    def test_dockerenv_exists(self) -> None:
        with patch("pathlib.Path.exists", return_value=True):
            assert _is_container() is True

    def test_cgroup_contains_docker(self) -> None:
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.read_text", return_value="/docker/abc123\n"),
        ):
            assert _is_container() is True

    def test_not_container(self) -> None:
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.read_text", side_effect=OSError),
        ):
            assert _is_container() is False

    @pytest.mark.parametrize("marker", ["containerd", "kubepods"])
    def test_cgroup_container_markers(self, marker: str) -> None:
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.read_text", return_value=f"/runtime/{marker}/abc123\n"),
        ):
            assert _is_container() is True

    def test_cgroup_without_container_markers(self) -> None:
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.read_text", return_value="/user.slice/session.scope\n"),
        ):
            assert _is_container() is False


class TestRunTool:
    """Tests for external diagnostic tool invocation."""

    def test_run_tool_resolves_executable_and_sets_timeout(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["resolved-tool", "--version"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

        with (
            patch(
                "distill.doctor.hardware.resolve_executable",
                return_value="resolved-tool",
            ),
            patch(
                "distill.doctor.hardware.package_install_context",
                return_value=("/trusted", {"PATH": "/usr/bin"}),
            ),
            patch("subprocess.run", return_value=completed) as run,
        ):
            result = _run_tool("tool", "--version")

        assert result is completed
        run.assert_called_once_with(
            ["resolved-tool", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd="/trusted",
            env={"PATH": "/usr/bin"},
        )


class TestDetectHardware:
    """Integration tests for the full detect_hardware() function."""

    def test_nvidia_system(self) -> None:
        nvidia_result = MagicMock()
        nvidia_result.returncode = 0
        nvidia_result.stdout = "NVIDIA GeForce RTX 3080, 10240\n"

        ram_result = MagicMock()
        ram_result.returncode = 0
        ram_result.stdout = "34359738368\n"  # 32 GB

        def mock_run(cmd, **kwargs):
            if "nvidia-smi" in cmd:
                return nvidia_result
            if "hw.memsize" in cmd or "sysctl" in cmd:
                return ram_result
            raise FileNotFoundError

        with (
            patch("distill.doctor.hardware.resolve_executable", side_effect=lambda cmd: cmd),
            patch("subprocess.run", side_effect=mock_run),
            patch("platform.system", return_value="Linux"),
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.read_text", side_effect=OSError),
        ):
            profile = detect_hardware()

        assert profile.gpu_type == "nvidia"
        assert "RTX 3080" in profile.gpu_name
        assert profile.vram_gb == pytest.approx(10.0, abs=0.1)
        assert profile.is_container is False

    def test_no_gpu_system(self) -> None:
        with (
            patch("distill.doctor.hardware.resolve_executable", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError),
            patch("platform.system", return_value="Linux"),
            patch("platform.machine", return_value="x86_64"),
            patch("pathlib.Path.exists", return_value=False),
            patch("pathlib.Path.read_text", side_effect=OSError),
        ):
            profile = detect_hardware()

        assert profile.gpu_type == "none"
        assert profile.gpu_name == ""
        assert profile.vram_gb == 0.0

    def test_apple_silicon_system(self) -> None:
        with (
            patch("distill.doctor.hardware._detect_nvidia", return_value=None),
            patch("distill.doctor.hardware._get_system_ram", return_value=24.0),
            patch("distill.doctor.hardware._get_apple_chip_name", return_value="Apple M4"),
            patch("distill.doctor.hardware._is_container", return_value=False),
            patch("platform.system", return_value="Darwin"),
            patch("platform.machine", return_value="arm64"),
        ):
            profile = detect_hardware()

        assert profile.gpu_type == "apple_silicon"
        assert profile.gpu_name == "Apple M4"
        assert profile.vram_gb == 24.0
        assert profile.system_ram_gb == 24.0
        assert profile.is_container is False


class TestVendorAndCapacitySemantics:
    """A measured VRAM figure is not always a capacity ceiling."""

    @pytest.mark.parametrize(
        ("description", "expected"),
        (
            ("NVIDIA GeForce RTX 4090", "nvidia"),
            ("AMD Radeon(TM) 780M", "amd"),
            ("Intel(R) Iris(R) Xe Graphics", "intel"),
            ("Intel(R) Arc(TM) A770", "intel"),
            ("Microsoft Basic Display Adapter", "none"),
        ),
    )
    def test_vendor_from_adapter_description(self, description: str, expected: str) -> None:
        assert _vendor_from_name(description) == expected

    def test_integrated_carve_out_is_not_a_capacity_ceiling(self) -> None:
        """A 780M reports a 2GB carve-out but runs 18GB models from shared RAM."""
        profile = HardwareProfile(
            gpu_type="amd",
            gpu_name="AMD Radeon(TM) 780M",
            vram_gb=2.0,
            system_ram_gb=62.0,
            is_container=False,
            vram_measured=True,
            vram_is_dedicated=False,
        )

        assert profile.has_gpu is True
        assert profile.vram_capacity_gb == 0.0  # no ceiling may be asserted

    def test_dedicated_vram_is_a_capacity_ceiling(self) -> None:
        profile = HardwareProfile(
            gpu_type="nvidia",
            gpu_name="RTX 4090",
            vram_gb=24.0,
            system_ram_gb=64.0,
            is_container=False,
            vram_measured=True,
            vram_is_dedicated=True,
        )

        assert profile.vram_capacity_gb == 24.0

    def test_absent_gpu_is_distinguishable_from_unmeasured(self) -> None:
        absent = HardwareProfile("none", "", 0.0, 16.0, False)
        present_unsized = HardwareProfile("intel", "Intel Arc", 0.0, 16.0, False)

        assert absent.has_gpu is False
        assert present_unsized.has_gpu is True
        assert present_unsized.vram_capacity_gb == 0.0


class TestAmdDetection:
    """AMD is detected from a vendor tool or the kernel, on any platform."""

    def test_rocm_smi_reports_total_vram(self) -> None:
        result = MagicMock()
        result.returncode = 0
        result.stdout = "device,VRAM Total Memory (B)\ncard0,25769803776\n"

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="rocm-smi"),
            patch("subprocess.run", return_value=result),
        ):
            assert _detect_amd() == ("amd", "AMD GPU", 24.0, True)

    def test_rocm_smi_absent_falls_through_to_sysfs(self, tmp_path: Path) -> None:
        vram_node = tmp_path / "card0" / "device" / "mem_info_vram_total"
        vram_node.parent.mkdir(parents=True)
        vram_node.write_text("17179869184\n", encoding="utf-8")

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value=None),
            patch.object(hardware_mod.Path, "glob", return_value=[vram_node]),
        ):
            assert _detect_amd() == ("amd", "AMD GPU", 16.0, True)

    def test_rocm_smi_nonzero_exit_is_not_a_detection(self) -> None:
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value="rocm-smi"),
            patch("subprocess.run", return_value=result),
            patch.object(hardware_mod.Path, "glob", return_value=[]),
        ):
            assert _detect_amd() is None

    def test_unreadable_sysfs_node_is_skipped(self, tmp_path: Path) -> None:
        bad = tmp_path / "card0" / "device" / "mem_info_vram_total"
        bad.parent.mkdir(parents=True)
        bad.write_text("not-a-number", encoding="utf-8")

        with (
            patch("distill.doctor.hardware.resolve_executable", return_value=None),
            patch.object(hardware_mod.Path, "glob", return_value=[bad]),
        ):
            assert _detect_amd() is None

    def test_no_amd_anywhere(self) -> None:
        with (
            patch("distill.doctor.hardware.resolve_executable", return_value=None),
            patch.object(hardware_mod.Path, "glob", side_effect=OSError),
        ):
            assert _detect_amd() is None


class _FakeWinreg:
    """Minimal winreg stand-in over a {subkey: {value: data}} tree."""

    HKEY_LOCAL_MACHINE = object()

    def __init__(self, tree: dict[str, dict[str, object]]) -> None:
        self._tree = tree

    def OpenKey(self, root: object, name: str):
        if isinstance(root, _FakeWinreg._Key):
            return _FakeWinreg._Key(self, name)
        return _FakeWinreg._Key(self, None)

    def EnumKey(self, key: object, index: int) -> str:
        names = list(self._tree)
        if index >= len(names):
            raise OSError("no more items")
        return names[index]

    def QueryValueEx(self, key: object, name: str):
        values = self._tree.get(getattr(key, "name", "") or "", {})
        if name not in values:
            raise OSError(name)
        return (values[name], 0)

    class _Key:
        def __init__(self, owner: _FakeWinreg, name: str | None) -> None:
            self.owner = owner
            self.name = name

        def __enter__(self) -> _FakeWinreg._Key:
            return self

        def __exit__(self, *exc: object) -> None:
            return None


class TestWindowsAdapterDetection:
    """The Windows fallback names a GPU without spawning a subprocess."""

    @staticmethod
    def _detect(tree: dict[str, dict[str, object]]):
        fake = _FakeWinreg(tree)
        with patch.dict("sys.modules", {"winreg": fake}):
            return _detect_windows_adapter()

    def test_amd_adapter_with_qword_memory(self) -> None:
        result = self._detect(
            {
                "0000": {
                    "DriverDesc": "AMD Radeon(TM) 780M",
                    "HardwareInformation.qwMemorySize": 2147483648,
                }
            }
        )
        # The registry cannot tell a carve-out from dedicated VRAM, so never
        # report this figure as a capacity ceiling.
        assert result == ("amd", "AMD Radeon(TM) 780M", 2.0, False)

    def test_byte_encoded_memory_value_is_decoded(self) -> None:
        result = self._detect(
            {
                "0000": {
                    "DriverDesc": "Intel(R) Arc(TM) A770",
                    "HardwareInformation.MemorySize": (16 * 1024**3).to_bytes(8, "little"),
                }
            }
        )
        assert result == ("intel", "Intel(R) Arc(TM) A770", 16.0, False)

    def test_adapter_without_a_memory_value_still_names_the_gpu(self) -> None:
        result = self._detect({"0000": {"DriverDesc": "NVIDIA GeForce RTX 4090"}})
        assert result == ("nvidia", "NVIDIA GeForce RTX 4090", 0.0, False)

    def test_non_numeric_subkeys_and_missing_descriptions_are_skipped(self) -> None:
        result = self._detect(
            {
                "Properties": {"DriverDesc": "ignored, not a numeric subkey"},
                "0000": {"HardwareInformation.qwMemorySize": 1},
                "0001": {"DriverDesc": "AMD Radeon RX 7900"},
            }
        )
        assert result == ("amd", "AMD Radeon RX 7900", 0.0, False)

    def test_unreadable_registry_reports_no_adapter(self) -> None:
        class _Broken:
            HKEY_LOCAL_MACHINE = object()

            def OpenKey(self, *args: object):
                raise OSError("access denied")

        with patch.dict("sys.modules", {"winreg": _Broken()}):
            assert _detect_windows_adapter() is None

    def test_unparseable_memory_value_degrades_to_unsized(self) -> None:
        result = self._detect(
            {"0000": {"DriverDesc": "AMD Radeon", "HardwareInformation.qwMemorySize": "huge"}}
        )
        assert result == ("amd", "AMD Radeon", 0.0, False)


class TestDetectionDegradesToNoGpu:
    """Every probe failing must report "none", never crash or invent a device."""

    def test_all_probes_absent_reports_no_gpu(self) -> None:
        with (
            patch("distill.doctor.hardware.resolve_executable", return_value=None),
            patch.object(hardware_mod.Path, "glob", side_effect=OSError),
            patch("platform.system", return_value="Linux"),
            patch("distill.doctor.hardware._get_system_ram", return_value=16.0),
            patch("distill.doctor.hardware._is_container", return_value=False),
        ):
            profile = detect_hardware()

        assert profile.gpu_type == "none"
        assert profile.has_gpu is False
        assert profile.vram_measured is False
        assert profile.vram_capacity_gb == 0.0

    def test_windows_registry_absent_reports_no_adapter(self) -> None:
        """A machine with no display-adapter key must not raise."""

        class _Empty:
            HKEY_LOCAL_MACHINE = object()

            class _Key:
                def __enter__(self):
                    return self

                def __exit__(self, *exc: object) -> None:
                    return None

            def OpenKey(self, *args: object):
                return self._Key()

            def EnumKey(self, key: object, index: int) -> str:
                raise OSError("no more items")

        with patch.dict("sys.modules", {"winreg": _Empty()}):
            assert _detect_windows_adapter() is None

    def test_a_subkey_that_cannot_be_opened_is_skipped(self) -> None:
        class _Broken:
            HKEY_LOCAL_MACHINE = object()
            _depth = 0

            class _Key:
                def __enter__(self):
                    return self

                def __exit__(self, *exc: object) -> None:
                    return None

            def OpenKey(self, root: object, name: str = ""):
                if name == "0000":
                    raise OSError("access denied")
                return self._Key()

            def EnumKey(self, key: object, index: int) -> str:
                if index == 0:
                    return "0000"
                raise OSError("no more items")

            def QueryValueEx(self, key: object, name: str):
                raise OSError(name)

        with patch.dict("sys.modules", {"winreg": _Broken()}):
            assert _detect_windows_adapter() is None
