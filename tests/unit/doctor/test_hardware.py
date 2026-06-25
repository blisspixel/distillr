"""Unit tests for distill.doctor.hardware — hardware detection with mocked subprocess."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from distill.doctor.hardware import (
    _detect_nvidia,
    _get_apple_chip_name,
    _get_system_ram,
    _is_container,
    detect_hardware,
)


class TestDetectNvidia:
    """Tests for NVIDIA GPU detection via nvidia-smi."""

    def test_nvidia_detected_with_valid_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "NVIDIA Test GPU, 24564\n"

        with (
            patch("distill.doctor.hardware.shutil.which", return_value="nvidia-smi"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _detect_nvidia()

        assert result is not None
        gpu_type, gpu_name, vram_gb = result
        assert gpu_type == "nvidia"
        assert gpu_name == "NVIDIA Test GPU"
        assert vram_gb == pytest.approx(24.0, abs=0.1)

    def test_nvidia_not_found(self) -> None:
        with patch("distill.doctor.hardware.shutil.which", return_value=None):
            result = _detect_nvidia()
        assert result is None

    def test_nvidia_smi_nonzero_return(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with (
            patch("distill.doctor.hardware.shutil.which", return_value="nvidia-smi"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _detect_nvidia()
        assert result is None

    def test_nvidia_smi_timeout(self) -> None:
        with (
            patch("distill.doctor.hardware.shutil.which", return_value="nvidia-smi"),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5)),
        ):
            result = _detect_nvidia()
        assert result is None

    def test_nvidia_empty_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with (
            patch("distill.doctor.hardware.shutil.which", return_value="nvidia-smi"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _detect_nvidia()
        assert result is None


class TestAppleChipName:
    """Tests for Apple Silicon chip name detection."""

    def test_apple_chip_detected(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Apple Test Chip\n"

        with (
            patch("distill.doctor.hardware.shutil.which", return_value="sysctl"),
            patch("subprocess.run", return_value=mock_result),
        ):
            name = _get_apple_chip_name()
        assert name == "Apple Test Chip"

    def test_apple_chip_fallback(self) -> None:
        with patch("distill.doctor.hardware.shutil.which", return_value=None):
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
            patch("distill.doctor.hardware.shutil.which", return_value="sysctl"),
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
            patch("distill.doctor.hardware.shutil.which", side_effect=lambda cmd: cmd),
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
            patch("distill.doctor.hardware.shutil.which", return_value=None),
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
