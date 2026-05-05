"""Structured JSON output layer for the Distill CLI.

Provides the JsonEnvelope wrapper, ExitCode enum, and error handling
for --json mode across all CLI commands.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

__all__ = ["ExitCode", "JsonEnvelope", "handle_cli_error"]


class ExitCode(IntEnum):
    """Stable CLI exit codes."""

    SUCCESS = 0
    RUNTIME_ERROR = 1
    USAGE_ERROR = 2
    CONFIG_ERROR = 3
    NETWORK_ERROR = 4
    NOT_FOUND = 5


@dataclass
class JsonEnvelope:
    """Standard JSON output wrapper for --json mode."""

    status: str  # "ok" | "error"
    data: Any = field(default=None)  # Command-specific payload
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
        d = json.loads(s)
        return cls(
            status=d["status"],
            data=d.get("data"),
            error=d.get("error"),
        )

    @classmethod
    def success(cls, data: Any = None) -> JsonEnvelope:
        """Create a success envelope."""
        return cls(status="ok", data=data)

    @classmethod
    def fail(cls, error: str, data: Any = None) -> JsonEnvelope:
        """Create an error envelope."""
        return cls(status="error", data=data, error=error)


def map_exception_to_exit_code(exc: BaseException) -> ExitCode:
    """Map an exception to the appropriate exit code."""
    import typer

    # Check for configuration errors
    exc_type_name = type(exc).__name__
    if "ConfigurationError" in exc_type_name or "config" in str(exc).lower():
        return ExitCode.CONFIG_ERROR

    # Network errors
    try:
        import requests

        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return ExitCode.NETWORK_ERROR
    except ImportError:
        pass

    if "timeout" in exc_type_name.lower() or "connection" in exc_type_name.lower():
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
