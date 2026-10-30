"""Supply-chain contracts for the clean-machine installers."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEMVER = r"\d+\.\d+\.\d+"


@pytest.mark.parametrize("name", ["install.sh", "install.ps1"])
def test_installers_use_canonical_repository_without_renaming_package(name: str) -> None:
    script = (_REPO_ROOT / "scripts" / name).read_text(encoding="utf-8-sig")

    assert f"https://raw.githubusercontent.com/pueo-labs/distillr/main/scripts/{name}" in script
    assert "git clone https://github.com/pueo-labs/distillr.git" in script
    assert "blisspixel/distillr" not in script
    assert re.search(r'(?:PACKAGE|\$Package)\s*=\s*"distillr"', script)


def test_pypi_metadata_uses_canonical_repository() -> None:
    project = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())["project"]

    assert project["name"] == "distillr"
    assert "packaging>=26.3" in project["dependencies"]
    assert project["urls"] == {
        "Homepage": "https://github.com/pueo-labs/distillr",
        "Repository": "https://github.com/pueo-labs/distillr",
        "Issues": "https://github.com/pueo-labs/distillr/issues",
    }


def test_shell_installer_executes_without_bom_or_network(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("The shell installer targets macOS and Linux")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is unavailable")
    script = _REPO_ROOT / "scripts" / "install.sh"
    assert script.read_bytes().startswith(b"#!/usr/bin/env bash\n")
    # A shell function isolates the package-manager call without installing
    # anything or relying on a separate executable fixture.
    result = subprocess.run(
        [
            bash,
            "-c",
            'uv() { printf "UV:%s\\n" "$*"; }; source "$1"',
            "installer-test",
            str(script),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "UV:tool install distillr" in result.stdout
    assert "git clone https://github.com/pueo-labs/distillr.git" in result.stdout


def test_powershell_installer_executes_without_network(tmp_path: Path) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    script = str(_REPO_ROOT / "scripts" / "install.ps1").replace("'", "''")
    harness = tmp_path / "install-test.ps1"
    harness.write_text(
        "function uv { Write-Output \"UV:$($args -join ' ')\"; $global:LASTEXITCODE = 0 }\n"
        f"& '{script}'\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "UV:tool install distillr" in result.stdout
    assert "git clone https://github.com/pueo-labs/distillr.git" in result.stdout


def test_shell_bootstrap_uses_versioned_uv_installer() -> None:
    script = (_REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert re.search(rf'^UV_VERSION="{_SEMVER}"$', script, re.MULTILINE)
    assert re.search(r'^UV_INSTALLER_SHA256="[0-9a-f]{64}"$', script, re.MULTILINE)
    assert "https://astral.sh/uv/${UV_VERSION}/install.sh" in script
    assert "https://astral.sh/uv/install.sh" not in script
    assert 'if [ "$actual_sha256" != "$UV_INSTALLER_SHA256" ]' in script
    assert "| sh" not in script


def test_shell_installer_handles_python_floor_and_path_portably() -> None:
    script = (_REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert "python312_available()" in script
    assert "sys.version_info >= (3, 12)" in script
    assert "&& ! python312_available" in script
    assert "sort -V" not in script
    assert 'if [ -n "${XDG_BIN_HOME:-}" ]; then' in script
    assert ":${XDG_BIN_HOME:-}:" not in script
    assert '"$PYTHON" -m pipx install --python "$PYTHON" "$PACKAGE"' in script
    assert '\n        pipx install "$PACKAGE"' not in script


def test_powershell_bootstrap_uses_versioned_uv_installer() -> None:
    script = (_REPO_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert re.search(rf'^\$UvVersion = "{_SEMVER}"$', script, re.MULTILINE)
    assert re.search(r'^\$UvInstallerSha256 = "[0-9a-f]{64}"$', script, re.MULTILINE)
    assert "https://astral.sh/uv/$UvVersion/install.ps1" in script
    assert "https://astral.sh/uv/install.ps1" not in script
    assert "Get-FileHash -LiteralPath $installer -Algorithm SHA256" in script
    assert "irm 'https://astral.sh" not in script


def test_powershell_installer_checks_python_floor_and_native_failures() -> None:
    script = (_REPO_ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")

    assert "function Get-SuitablePythonCommand" in script
    assert "sys.version_info >= (3, 12)" in script
    assert "-not $haveUv -and -not $python" in script
    assert "& $python -m pipx install --python $python $Package" in script
    assert "\n    pipx install $Package" not in script
    for operation in (
        "uv installer",
        "uv tool install",
        "pip install pipx",
        "pipx ensurepath",
        "pipx install",
    ):
        assert f'Assert-NativeSuccess -Operation "{operation}" -ExitCode $LASTEXITCODE' in script
