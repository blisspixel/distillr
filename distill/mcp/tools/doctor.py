"""MCP tools — doctor: check environment health."""

from __future__ import annotations

import json
import shutil

from distill.mcp import server as _server

__all__: list[str] = []


@_server.mcp.tool()
def doctor() -> str:
    """Check environment health: API keys, yt-dlp, dependencies."""
    config = _server._config()
    checks: list[dict] = []

    # API keys
    checks.append(
        {
            "check": "xai_api_key",
            "status": "ok" if config.xai_api_key.get_secret_value() else "missing",
        }
    )
    checks.append(
        {
            "check": "gemini_api_key",
            "status": "ok" if config.gemini_api_key.get_secret_value() else "missing",
        }
    )
    checks.append(
        {
            "check": "openai_api_key",
            "status": "ok" if config.openai_api_key.get_secret_value() else "optional",
        }
    )

    # yt-dlp
    yt_dlp_path = shutil.which("yt-dlp")
    checks.append(
        {
            "check": "yt-dlp",
            "status": "ok" if yt_dlp_path else "missing",
            "path": yt_dlp_path or "",
        }
    )

    # Library directory
    lib_exists = config.library_dir.exists()
    checks.append(
        {
            "check": "library_dir",
            "status": "ok" if lib_exists else "missing",
            "path": str(config.library_dir),
        }
    )

    # Playwright
    try:
        import playwright  # noqa: F401

        checks.append({"check": "playwright", "status": "ok"})
    except ImportError:
        checks.append({"check": "playwright", "status": "missing"})

    all_ok = all(c["status"] in ("ok", "optional") for c in checks)
    return json.dumps(
        {
            "status": "ok" if all_ok else "warning",
            "checks": checks,
        },
        indent=2,
    )
