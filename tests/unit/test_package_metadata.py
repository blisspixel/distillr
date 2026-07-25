"""Release metadata contracts that protect fresh downstream installations."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_editable_lock_version_matches_project_version() -> None:
    """Release bumps must keep the editable root package current in uv.lock."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    editable_roots = [
        package
        for package in lock["package"]
        if package.get("name") == "distillr" and package.get("source") == {"editable": "."}
    ]

    assert len(editable_roots) == 1
    assert editable_roots[0]["version"] == pyproject["project"]["version"]


def test_mcp_runtime_dependency_stays_on_supported_v1_line() -> None:
    """Do not let a fresh install cross the ungraduated MCP v2 boundary."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "mcp>=1.27.2,<2" in pyproject["project"]["dependencies"]
