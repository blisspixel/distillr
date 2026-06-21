"""MCP tools — OKF export and validation."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from distill.library.okf import export_okf_bundle, validate_okf_bundle
from distill.mcp import server as _server

__all__: list[str] = []


def _resolve_workspace_path(workspace: Path, path: str) -> Path | None:
    """Resolve a relative path under the Distill workspace root."""
    if not path or not isinstance(path, str) or "\x00" in path:
        return None
    windows_path = PureWindowsPath(path)
    if (
        PurePosixPath(path).is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
    ):
        return None
    try:
        root = workspace.resolve(strict=False)
        candidate = (root / path).resolve(strict=False)
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate


def _bundle_preview(output_dir: Path) -> str:
    for name in ("llms.txt", "index.md"):
        path = output_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            return text[:800] + ("\n... (truncated)" if len(text) > 800 else "")
    return ""


@_server.mcp.tool()
@_server.write_tool("okf_export")
def okf_export(topic: str) -> str:
    """Export a topic (or ``all``) into an OKF v0.1 bundle under output/.

    Args:
        topic: Topic name, or ``all`` for the whole library
    """
    config = _server._config()
    normalized = topic.strip() or "all"
    try:
        result = export_okf_bundle(config, normalized)
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, indent=2)

    payload = {
        "status": "ok" if result.validation.ok else "invalid",
        "topic": result.topic,
        "output_dir": str(result.output_dir),
        "files_written": result.files_written,
        "validation": result.validation.to_dict(),
        "index_path": str(result.output_dir / "index.md"),
        "log_path": str(result.output_dir / "log.md"),
        "llms_txt_path": str(result.output_dir / "llms.txt"),
        "preview": _bundle_preview(result.output_dir),
    }
    return json.dumps(payload, indent=2)


@_server.mcp.tool()
def okf_validate(path: str) -> str:
    """Validate an OKF bundle directory (read-only structural check).

    Args:
        path: Workspace-relative path to the bundle, e.g. output/okf-ai
    """
    config = _server._config()
    workspace = config.library_dir.parent
    bundle_path = _resolve_workspace_path(workspace, path)
    if bundle_path is None or not bundle_path.is_dir():
        return json.dumps(
            {
                "status": "error",
                "error": "path must be a relative directory inside the Distill workspace.",
            },
            indent=2,
        )

    result = validate_okf_bundle(bundle_path)
    return json.dumps(
        {
            "status": "ok" if result.ok else "invalid",
            "validation": result.to_dict(),
        },
        indent=2,
    )
