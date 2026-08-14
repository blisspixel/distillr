# pyright: strict
"""Provider-availability refusals shared by CLI commands."""

from __future__ import annotations

from distill.commands._json import ExitCode, exit_with_refusal

__all__ = ["require_api_key", "require_model"]


def require_api_key(value: str | object, message: str) -> None:
    if not value:
        exit_with_refusal(
            message,
            code=ExitCode.CONFIG_ERROR,
            reason="config_error",
            action="provider",
            limit={"kind": "api_key"},
        )


def require_model(workload: str = "", hint: str = "") -> None:
    """Exit unless a cloud key or local provider can serve ``workload``."""
    from distill.llm.availability import model_available

    if model_available(workload):
        return
    target = f" for {workload}" if workload else ""
    extra = f" {hint}" if hint else ""
    exit_with_refusal(
        "No model configured"
        f"{target}. Set a cloud key (XAI_API_KEY / GEMINI_API_KEY) or a local "
        f"provider (DISTILL_PROVIDER=ollama).{extra}",
        code=ExitCode.CONFIG_ERROR,
        reason="config_error",
        action="provider",
        limit={"kind": "model", "workload": workload or "default"},
    )
