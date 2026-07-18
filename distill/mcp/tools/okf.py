# pyright: strict
"""MCP tools — OKF export and validation."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from distill.library.confined import read_confined_text, validate_confined_path
from distill.library.okf import OkfValidationLimits, export_okf_bundle, validate_okf_bundle
from distill.mcp.server import load_config, mcp, write_tool

__all__: list[str] = []

_MCP_OKF_LIMITS = OkfValidationLimits(
    max_entries=10_000,
    max_files=2_000,
    max_file_bytes=2 * 1024 * 1024,
    max_total_bytes=32 * 1024 * 1024,
    max_tree_depth=32,
    max_yaml_depth=48,
    max_links_per_file=1_024,
    max_issues=500,
    timeout_seconds=10.0,
)
_MAX_OKF_PREVIEW_BYTES = 64 * 1024


def _resolve_workspace_path(workspace: Path, path: str) -> Path | None:
    """Resolve a relative path under the Distill workspace root."""
    if not path or "\x00" in path:
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
        candidate = root / path
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate


def _resolve_okf_bundle_path(workspace: Path, path: str) -> Path | None:
    candidate = _resolve_workspace_path(workspace, path)
    if candidate is None:
        return None
    try:
        relative = candidate.relative_to(workspace.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if (
        len(relative.parts) != 2
        or relative.parts[0] != "output"
        or not relative.parts[1].casefold().startswith("okf-")
    ):
        return None
    validated = validate_confined_path(candidate, workspace, expect_directory=True)
    return validated[0] if validated is not None else None


def _bundle_preview(output_dir: Path) -> str:
    for name in ("llms.txt", "index.md"):
        path = output_dir / name
        text = read_confined_text(path, output_dir, max_bytes=_MAX_OKF_PREVIEW_BYTES)
        if text is not None:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            return text[:800] + ("\n... (truncated)" if len(text) > 800 else "")
    return ""


@mcp.tool()
@write_tool("okf_export")
def okf_export(topic: str) -> str:
    """Export a topic (or ``all``) into an OKF v0.1 bundle under output/.

    Args:
        topic: Topic name, or ``all`` for the whole library
    """
    config = load_config()
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


@mcp.tool()
def okf_validate(path: str) -> str:
    """Validate an OKF bundle directory (read-only structural check).

    Args:
        path: Workspace-relative path to the bundle, e.g. output/okf-ai
    """
    config = load_config()
    workspace = config.library_dir.parent
    bundle_path = _resolve_okf_bundle_path(workspace, path)
    if bundle_path is None:
        return json.dumps(
            {
                "status": "error",
                "error": "path must identify a regular output/okf-* bundle directory.",
            },
            indent=2,
        )

    result = validate_okf_bundle(bundle_path, limits=_MCP_OKF_LIMITS)
    return json.dumps(
        {
            "status": "ok" if result.ok else "invalid",
            "validation": result.to_dict(),
        },
        indent=2,
    )
