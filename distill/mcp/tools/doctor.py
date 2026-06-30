# pyright: strict
"""MCP tools — doctor: check environment health."""

from __future__ import annotations

import json
import shutil
from importlib.util import find_spec
from typing import Literal, NotRequired, TypedDict

from distill.doctor.checks import doctor_validate_key
from distill.mcp.server import load_config, mcp

type DoctorCheckStatus = Literal[
    "ok", "optional", "not_set", "missing", "invalid", "unknown", "warning"
]


class DoctorCheck(TypedDict):
    check: str
    status: DoctorCheckStatus
    detail: NotRequired[str]
    path: NotRequired[str]
    field: NotRequired[str]
    model: NotRequired[str]
    retirement_date: NotRequired[str]
    replacement: NotRequired[str]


__all__: list[str] = []


@mcp.tool()
def doctor() -> str:
    """Check environment health: API keys, yt-dlp, dependencies."""
    config = load_config()
    checks: list[DoctorCheck] = []

    # API keys -- live-validated via the shared CLI helper so the MCP doctor,
    # the CLI doctor, and the --json path never disagree about key health.
    # Presence alone is not health: a revoked/expired key is present but dead,
    # and reporting it "ok" is the false-green this tool used to produce.
    for provider, label in (
        ("xai", "xai_api_key"),
        ("gemini", "gemini_api_key"),
        ("anthropic", "anthropic_api_key"),
        ("openai", "openai_api_key"),
    ):
        status, detail = doctor_validate_key(provider, config)
        entry: DoctorCheck = {"check": label, "status": status}
        if status in ("invalid", "unknown"):
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
    checks.append(
        {
            "check": "playwright",
            "status": "ok" if find_spec("playwright") else "missing",
        }
    )

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
    # "missing" (required xai absent), "invalid" (present but auth-rejected), and
    # "unknown" (present but unverifiable -- transient/offline) flip the overall
    # status to warning. "unknown" is a soft signal, not a confirmed rejection.
    all_ok = all(c["status"] in ("ok", "optional", "not_set") for c in checks)
    return json.dumps(
        {
            "status": "ok" if all_ok else "warning",
            "checks": checks,
        },
        indent=2,
    )
