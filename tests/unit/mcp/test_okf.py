"""Tests for MCP OKF export and validation tools."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from distill.config import DistillConfig
from distill.library.okf import export_okf_bundle


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_okf_export_writes_bundle_and_returns_paths(tmp_path: Path) -> None:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    topic_dir = config.topic_dir("ai")
    _write(
        topic_dir / "videos" / "x" / "x_Insights.md",
        "---\nvideo_title: Example\n---\n\n# Insight\n",
    )

    with patch("distill.mcp.server._config", return_value=config):
        from distill.mcp.tools.okf import okf_export

        result = json.loads(okf_export("ai"))

    assert result["status"] == "ok"
    assert result["topic"] == "ai"
    assert Path(result["output_dir"]).exists()
    assert result["files_written"] >= 3
    assert "index.md" in result["index_path"]
    assert result["preview"]


def test_okf_export_missing_topic_returns_error(tmp_path: Path) -> None:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    with patch("distill.mcp.server._config", return_value=config):
        from distill.mcp.tools.okf import okf_export

        result = json.loads(okf_export("missing"))

    assert result["status"] == "error"


def test_okf_validate_accepts_workspace_relative_bundle(tmp_path: Path) -> None:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    _write(
        config.topic_dir("ai") / "x_Insights.md",
        "---\ntitle: X\n---\n\n# X\n",
    )
    export_okf_bundle(config, "ai")

    with patch("distill.mcp.server._config", return_value=config):
        from distill.mcp.tools.okf import okf_validate

        result = json.loads(okf_validate("output/okf-ai"))

    assert result["status"] == "ok"
    assert result["validation"]["ok"] is True


def test_okf_validate_rejects_escape_paths(tmp_path: Path) -> None:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    with patch("distill.mcp.server._config", return_value=config):
        from distill.mcp.tools.okf import okf_validate

        result = json.loads(okf_validate("../../etc/passwd"))

    assert result["status"] == "error"


def test_okf_export_refused_in_read_only_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DISTILL_MCP_READ_ONLY", "1")
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    with patch("distill.mcp.server._config", return_value=config):
        from distill.mcp.tools.okf import okf_export

        result = json.loads(okf_export("ai"))

    assert result["status"] == "read_only"
