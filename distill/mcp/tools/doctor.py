# pyright: strict
"""MCP tools — doctor: check environment health."""

from __future__ import annotations

import json
import shutil
from importlib.util import find_spec
from typing import Literal, NotRequired, TypedDict

from distill.doctor.checks import doctor_validate_key
from distill.mcp.server import READ_TOOL_ANNOTATIONS, load_config, mcp

_YT_DLP_BASENAME = "yt-dlp"

type DoctorCheckStatus = Literal[
    "ok",
    "optional",
    "not_set",
    "missing",
    "invalid",
    "unknown",
    "skipped",
    "warning",
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


@mcp.tool(annotations=READ_TOOL_ANNOTATIONS)
def doctor() -> str:
    """Check environment health: API keys, yt-dlp, dependencies."""
    config = load_config()
    checks: list[DoctorCheck] = []

    # MCP diagnostics are configuration-only. Live provider probes can create
    # spend and do not pass through this tool's per-call tracker or ledger.
    # Configured keys therefore remain unknown until the operator runs the local
    # CLI doctor, where live validation is explicit and cost policy is visible.
    for provider, label in (
        ("xai", "xai_api_key"),
        ("gemini", "gemini_api_key"),
        ("anthropic", "anthropic_api_key"),
        ("openai", "openai_api_key"),
        ("openrouter", "openrouter_api_key"),
    ):
        status, detail = doctor_validate_key(provider, config, live=False)
        entry: DoctorCheck = {"check": label, "status": status}
        if status in ("invalid", "unknown", "skipped"):
            entry["detail"] = detail[:120]
        checks.append(entry)

    # yt-dlp: report basename only so MCP does not leak install layout.
    yt_dlp_path = shutil.which(_YT_DLP_BASENAME)
    checks.append(
        {
            "check": "yt-dlp",
            "status": "ok" if yt_dlp_path else "missing",
            "path": _YT_DLP_BASENAME if yt_dlp_path else "",
        }
    )

    # Library directory: the confided corpus root is presented as "." so the
    # host absolute path never appears in agent-visible tool results.
    lib_exists = config.library_dir.exists()
    checks.append(
        {
            "check": "library_dir",
            "status": "ok" if lib_exists else "missing",
            "path": ".",
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
    # "missing" (required xai absent), "invalid" (present but auth-rejected),
    # "unknown" (present but unverifiable), and "skipped" (live validation
    # blocked by policy) flip the overall status to warning.
    all_ok = all(c["status"] in ("ok", "optional", "not_set") for c in checks)
    return json.dumps(
        {
            "status": "ok" if all_ok else "warning",
            "checks": checks,
        },
        indent=2,
    )
