# pyright: strict
"""Structured JSON output layer for the Distill CLI.

Provides the JsonEnvelope wrapper, ExitCode enum, and error handling
for --json mode across all CLI commands.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, NoReturn, cast

__all__ = [
    "ExitCode",
    "JsonEnvelope",
    "emit_json",
    "emit_json_refusal",
    "exit_with_refusal",
    "handle_cli_error",
    "json_mode_active",
    "loop_refusal_fields",
    "phase_for_exit_code",
    "register_json_mode_reset",
    "reset_json_mode",
    "set_json_active",
]

# Per-invocation flag: set by the app callback from the global ``--json`` option
# and read by read commands that don't take a ``ctx`` parameter. A module flag
# (not the ambient Click context, which isn't reliably retrievable inside a
# Typer command body) reset every invocation by the callback.
_json_active = False


class ExitCode(IntEnum):
    """Stable CLI exit codes."""

    SUCCESS = 0
    RUNTIME_ERROR = 1
    USAGE_ERROR = 2
    CONFIG_ERROR = 3
    NETWORK_ERROR = 4
    NOT_FOUND = 5
    BUDGET_EXCEEDED = 6


_PHASE_BY_EXIT: dict[ExitCode, str] = {
    ExitCode.SUCCESS: "gate.success",
    ExitCode.RUNTIME_ERROR: "gate.runtime",
    ExitCode.USAGE_ERROR: "gate.usage",
    ExitCode.CONFIG_ERROR: "gate.config",
    ExitCode.NETWORK_ERROR: "gate.network",
    ExitCode.NOT_FOUND: "gate.not_found",
    ExitCode.BUDGET_EXCEEDED: "gate.budget",
}

_REASON_BY_EXIT: dict[ExitCode, str] = {
    ExitCode.RUNTIME_ERROR: "runtime_error",
    ExitCode.USAGE_ERROR: "usage_error",
    ExitCode.CONFIG_ERROR: "config_error",
    ExitCode.NETWORK_ERROR: "network_error",
    ExitCode.NOT_FOUND: "not_found",
    ExitCode.BUDGET_EXCEEDED: "budget_exceeded",
}


@dataclass
class JsonEnvelope:
    """Standard JSON output wrapper for --json mode."""

    status: str  # "ok" | "error"
    data: object = field(default=None)  # Command-specific payload
    error: str | None = None  # Error message when status == "error"

    def to_json(self) -> str:
        """Serialize to JSON string."""
        d: dict[str, Any] = {"status": self.status, "data": self.data}
        if self.error is not None:
            d["error"] = self.error
        return json.dumps(d, indent=2, default=str, allow_nan=False)

    @classmethod
    def from_json(cls, s: str) -> JsonEnvelope:
        """Deserialize from JSON string."""
        d = cast(dict[str, object], json.loads(s))
        status = d.get("status")
        if not isinstance(status, str):
            raise ValueError("JSON envelope missing string status")
        error = d.get("error")
        if error is not None and not isinstance(error, str):
            raise ValueError("JSON envelope error must be a string")
        return cls(
            status=status,
            data=d.get("data"),
            error=error,
        )

    @classmethod
    def success(cls, data: object = None) -> JsonEnvelope:
        """Create a success envelope."""
        return cls(status="ok", data=data)

    @classmethod
    def fail(cls, error: str, data: object = None) -> JsonEnvelope:
        """Create an error envelope."""
        return cls(status="error", data=data, error=error)


def set_json_active(enabled: bool) -> None:
    """Record whether ``--json`` is active for this invocation (called by the
    app callback). Resets every run, so a reused process never leaks state."""
    global _json_active
    _json_active = enabled


def reset_json_mode() -> None:
    """Restore human-mode stdout after a CLI invocation finishes."""
    from distill._console import set_json_mode

    set_json_mode(False)
    set_json_active(False)


def register_json_mode_reset(ctx: object) -> None:
    """Reset JSON mode when a Click/Typer context closes."""
    closer = getattr(ctx, "call_on_close", None)
    if callable(closer):
        closer(reset_json_mode)


def json_mode_active() -> bool:
    """Whether the global ``--json`` flag is set on this invocation."""
    return _json_active


def emit_json(data: object = None, *, error: str | None = None) -> None:
    """Write one JSON envelope to **stdout** (not the console).

    Always stdout regardless of the console's ``--json`` stderr redirect, so the
    machine-readable payload is the only thing on stdout while diagnostics go to
    stderr. Pass ``error`` for a failure envelope.
    """
    envelope = JsonEnvelope.fail(error, data) if error is not None else JsonEnvelope.success(data)
    sys.stdout.write(envelope.to_json() + "\n")


def loop_refusal_fields(
    *,
    action: str,
    phase: str,
    limit: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Fields external loops need on a CLI JSON refusal.

    Mirrors the MCP refusal envelope: action, phase, run_id, optional limit,
    and a library-relative telemetry path when the active run knows its ops
    directory. Never emits host absolute paths.
    """
    from distill.llm.run_context import current_run, current_run_id

    fields: dict[str, object] = {
        "action": action,
        "phase": phase,
        "run_id": current_run_id(),
    }
    if limit is not None:
        fields["limit"] = dict(limit)

    context = current_run()
    if context is not None and context.ops_dir is not None:
        # ops_dir is library/.distill; present as a library-relative label.
        fields["telemetry_path"] = (
            ".distill/phase_telemetry.jsonl"
            if context.ops_dir.name == ".distill"
            else "phase_telemetry.jsonl"
        )
    return fields


def phase_for_exit_code(code: ExitCode | int) -> str:
    """Map a stable CLI exit code to a loop-readable refusal phase id."""
    try:
        return _PHASE_BY_EXIT[ExitCode(int(code))]
    except ValueError:
        return "gate.runtime"


def emit_json_refusal(
    *,
    reason: str,
    error: str,
    phase: str,
    action: str = "cli",
    limit: Mapping[str, object] | None = None,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Emit one failure envelope with loop-readable refusal fields."""
    data: dict[str, object] = {
        "reason": reason,
        **loop_refusal_fields(action=action, phase=phase, limit=limit),
    }
    if extra is not None:
        data.update(dict(extra))
    emit_json(data, error=error)


def exit_with_refusal(
    message: str,
    *,
    code: ExitCode,
    reason: str,
    phase: str | None = None,
    action: str = "cli",
    limit: Mapping[str, object] | None = None,
) -> NoReturn:
    """Refuse a CLI command with human or JSON output and a stable exit code."""
    import typer
    from rich.markup import escape

    from distill._console import console

    resolved_phase = phase or phase_for_exit_code(code)
    if json_mode_active():
        emit_json_refusal(
            reason=reason,
            error=message,
            phase=resolved_phase,
            action=action,
            limit=limit,
        )
    else:
        # Escape so operator text like "missing [draft].pdf" is not Rich markup.
        console.print(f"[red]{escape(message)}[/red]")
    raise typer.Exit(int(code))


def _int_attr(obj: object, name: str) -> int | None:
    value = cast(object | None, getattr(obj, name, None))
    return value if isinstance(value, int) else None


def _http_status_code(exc: BaseException) -> int | None:
    status = _int_attr(exc, "status_code")
    if status is not None:
        return status
    status = _int_attr(exc, "code")
    if status is not None:
        return status
    response = cast(object | None, getattr(exc, "response", None))
    if response is None:
        return None
    return _int_attr(response, "status_code")


def _exit_code_from_http_status(status: int | None) -> ExitCode | None:
    if status in (401, 402, 403):
        return ExitCode.CONFIG_ERROR
    if status == 404:
        return ExitCode.NOT_FOUND
    if status == 429 or (status is not None and status >= 500):
        return ExitCode.NETWORK_ERROR
    return None


def _is_requests_network_error(exc: BaseException) -> bool:
    try:
        import requests
    except ImportError:
        return False
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


def map_exception_to_exit_code(exc: BaseException) -> ExitCode:
    """Map an exception to the appropriate exit code."""
    import typer

    from distill.pipeline.costs import BudgetExceededError

    if isinstance(exc, BudgetExceededError):
        return ExitCode.BUDGET_EXCEEDED

    # Type identity only. Message substrings such as "config" or "not found"
    # are too common in unrelated runtime errors to drive process status.
    exc_type_name = type(exc).__name__
    if "ConfigurationError" in exc_type_name:
        return ExitCode.CONFIG_ERROR

    status_code = _exit_code_from_http_status(_http_status_code(exc))
    if status_code is not None:
        return status_code

    if (
        _is_requests_network_error(exc)
        or "timeout" in exc_type_name.lower()
        or "connection" in exc_type_name.lower()
    ):
        return ExitCode.NETWORK_ERROR

    if "NotFound" in exc_type_name:
        return ExitCode.NOT_FOUND

    if isinstance(exc, typer.BadParameter):
        return ExitCode.USAGE_ERROR
    if isinstance(exc, SystemExit) and exc.code == 2:
        return ExitCode.USAGE_ERROR

    return ExitCode.RUNTIME_ERROR


def handle_cli_error(exc: BaseException, *, json_mode: bool = False) -> int:
    """Handle a CLI error, optionally producing JSON output.

    Returns the exit code to use.
    """
    code = map_exception_to_exit_code(exc)

    if json_mode:
        data = _structured_error_data(exc, code=code)
        envelope = JsonEnvelope.fail(str(exc), data)
        sys.stdout.write(envelope.to_json() + "\n")
    else:
        sys.stderr.write(f"Error: {exc}\n")

    return int(code)


def _structured_error_data(exc: BaseException, *, code: ExitCode) -> dict[str, object]:
    """Return stable orchestration metadata for typed retryable failures."""
    from distill.llm.errors import ProviderBusyTimeoutError

    data: dict[str, object] = {
        "reason": _REASON_BY_EXIT.get(code, "runtime_error"),
        **loop_refusal_fields(
            action="cli",
            phase=phase_for_exit_code(code),
            limit={"kind": "exception", "type": type(exc).__name__},
        ),
    }
    if isinstance(exc, ProviderBusyTimeoutError):
        data.update(
            {
                "code": "provider_busy",
                "retryable": True,
                "terminal": False,
                "provider": exc.provider,
                "requested_model": exc.requested_model,
                "active_models": list(exc.active_models),
                "waited_seconds": exc.timeout_seconds,
            }
        )
    return data
