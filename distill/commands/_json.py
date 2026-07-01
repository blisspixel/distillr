# pyright: strict
"""Structured JSON output layer for the Distill CLI.

Provides the JsonEnvelope wrapper, ExitCode enum, and error handling
for --json mode across all CLI commands.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, cast

__all__ = [
    "ExitCode",
    "JsonEnvelope",
    "emit_json",
    "handle_cli_error",
    "json_mode_active",
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
        return json.dumps(d, indent=2, default=str)

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

    # Check for configuration errors
    exc_type_name = type(exc).__name__
    if "ConfigurationError" in exc_type_name or "config" in str(exc).lower():
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

    # Resource not found
    if "NotFound" in exc_type_name or "not found" in str(exc).lower():
        return ExitCode.NOT_FOUND

    # Usage errors
    if isinstance(exc, (typer.BadParameter, SystemExit)):
        if isinstance(exc, SystemExit) and exc.code == 2:
            return ExitCode.USAGE_ERROR
        if isinstance(exc, typer.BadParameter):
            return ExitCode.USAGE_ERROR

    return ExitCode.RUNTIME_ERROR


def handle_cli_error(exc: BaseException, *, json_mode: bool = False) -> int:
    """Handle a CLI error, optionally producing JSON output.

    Returns the exit code to use.
    """
    code = map_exception_to_exit_code(exc)

    if json_mode:
        envelope = JsonEnvelope.fail(str(exc))
        sys.stdout.write(envelope.to_json() + "\n")
    else:
        sys.stderr.write(f"Error: {exc}\n")

    return int(code)
