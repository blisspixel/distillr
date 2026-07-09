"""Release metadata contracts that protect fresh downstream installations."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_mcp_runtime_dependency_stays_on_supported_v1_line() -> None:
    """Do not let a fresh install cross the ungraduated MCP v2 boundary."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "mcp>=1.27.2,<2" in pyproject["project"]["dependencies"]
