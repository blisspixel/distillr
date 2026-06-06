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

    # API keys -- live-validated via the shared CLI helper so the MCP doctor,
    # the CLI doctor, and the --json path never disagree about key health.
    # Presence alone is not health: a revoked/expired key is present but dead,
    # and reporting it "ok" is the false-green this tool used to produce.
    from distill.commands._logic import _doctor_validate_key

    for provider, label in (
        ("xai", "xai_api_key"),
        ("gemini", "gemini_api_key"),
        ("openai", "openai_api_key"),
    ):
        status, detail = _doctor_validate_key(provider, config)
        entry: dict = {"check": label, "status": status}
        if status == "invalid":
            entry["detail"] = detail[:120]
        checks.append(entry)

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

    # Retired models
    from distill.llm.router import RETIRED_MODELS, RETIREMENT_DATE

    model_fields = [
        "xai_fast_model",
        "xai_premium_model",
        "xai_analysis_model",
        "xai_rerank_model",
        "xai_synthesis_model",
        "xai_site_model",
        "accordion_section_model",
    ]
    for field in model_fields:
        value = getattr(config, field, "")
        if value and value in RETIRED_MODELS:
            checks.append(
                {
                    "check": "retired_model",
                    "status": "warning",
                    "field": field,
                    "model": value,
                    "retirement_date": RETIREMENT_DATE,
                    "replacement": RETIRED_MODELS[value],
                }
            )

    # "not_set" = an optional key (gemini/openai) is absent -- not a failure.
    # "missing" (required xai absent) and "invalid" (present but rejected) flip
    # the overall status to warning.
    all_ok = all(c["status"] in ("ok", "optional", "not_set") for c in checks)
    return json.dumps(
        {
            "status": "ok" if all_ok else "warning",
            "checks": checks,
        },
        indent=2,
    )
