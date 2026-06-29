from __future__ import annotations

from pathlib import Path


def test_mcp_python_files_are_pyright_strict() -> None:
    mcp_root = Path(__file__).resolve().parents[3] / "distill" / "mcp"
    missing: list[str] = []

    for path in sorted(mcp_root.rglob("*.py")):
        header = path.read_text(encoding="utf-8").splitlines()[:3]
        if not any("pyright: strict" in line for line in header):
            missing.append(path.relative_to(mcp_root).as_posix())

    assert missing == []
