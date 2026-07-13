"""Supply-chain contracts for the clean-machine installers."""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEMVER = r"\d+\.\d+\.\d+"


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
