# pyright: strict, reportPrivateUsage=false, reportUnusedFunction=false
"""Validation contracts for host-session task and receipt files."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from distill.llm.providers._agent_files import read_task_text
from distill.llm.providers._agent_protocol import (
    MAX_AGENT_SIDECAR_BYTES,
    validate_host_submission,
)
from distill.llm.providers.agent import (
    AGENT_TASK_SCHEMA_VERSION,
    MAX_AGENT_RESULT_BYTES,
    MAX_AGENT_TASK_BYTES,
    AgentProvider,
)
from distill.llm.usage import MAX_USAGE_TOKENS

_TASK_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_WORKLOAD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class WorkerTaskError(ValueError):
    """Base error for a rejected worker operation."""


class WorkerTaskNotFound(WorkerTaskError):
    """Raised when a requested task does not exist."""


class WorkerTaskConflict(WorkerTaskError):
    """Raised when task ownership or published output conflicts."""


class WorkerTaskInvalid(WorkerTaskError):
    """Raised when a task or receipt fails its structural contract."""


class _TaskView(Protocol):
    @property
    def task_id(self) -> str: ...

    @property
    def prompt_hash(self) -> str: ...

    @property
    def max_result_bytes(self) -> int: ...


class _ClaimView(Protocol):
    @property
    def token_hash(self) -> str: ...


class _BoundRootView(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def identity(self) -> tuple[int, int]: ...


def _validated_task_identity(
    payload: Mapping[str, Any],
    path: Path,
) -> tuple[str, str, str, str]:
    task_id = _required_text(payload, "task_id")
    workload = _required_text(payload, "workload_tag")
    prompt = _required_text(payload, "prompt", strip=False)
    prompt_hash = _required_text(payload, "prompt_hash")
    _validated_task_id(task_id)
    if not _WORKLOAD_RE.fullmatch(workload):
        raise WorkerTaskInvalid(f"task {path.name} has an invalid workload tag")
    if path.name != f"{workload}_{task_id}.json":
        raise WorkerTaskInvalid(f"task {path.name} does not match its declared identity")
    expected_hash = AgentProvider._prompt_hash(prompt, workload)
    if not hmac.compare_digest(prompt_hash, expected_hash):
        raise WorkerTaskInvalid(f"task {path.name} has a mismatched prompt hash")
    if payload.get("schema_version") not in {None, AGENT_TASK_SCHEMA_VERSION}:
        raise WorkerTaskInvalid(f"task {path.name} has an unsupported schema version")
    if payload.get("expected_output_format") != "markdown":
        raise WorkerTaskInvalid(f"task {path.name} does not request markdown output")
    return task_id, workload, prompt, prompt_hash


def _validate_declared_result_limit(
    payload: Mapping[str, Any],
    path: Path,
    expected: int,
) -> None:
    declared = payload.get("max_result_bytes")
    if declared is not None and declared != expected:
        raise WorkerTaskInvalid(f"task {path.name} has a mismatched result size limit")


def _optional_creation_timestamp(payload: Mapping[str, Any], path: Path) -> str:
    value = payload.get("created_at")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WorkerTaskInvalid(f"task {path.name} has an invalid creation timestamp")
    _parse_timestamp(value, field="created_at")
    return value


def _validate_existing_submission(
    task: _TaskView,
    claim: _ClaimView,
    payload: Mapping[str, Any],
    result_bytes: bytes,
) -> None:
    try:
        receipt = validate_host_submission(
            payload,
            task_id=task.task_id,
            prompt_hash=task.prompt_hash,
            result_text=result_bytes.decode("utf-8"),
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorkerTaskConflict(f"task has an invalid submission receipt: {exc}") from exc
    if not hmac.compare_digest(receipt.claim_token_hash, claim.token_hash):
        raise WorkerTaskConflict("task already has a submission from another claim")


def _validate_workspace_names(workspace: Path) -> None:
    try:
        names = {entry.name for entry in workspace.iterdir()}
    except OSError as exc:
        raise WorkerTaskInvalid("worker workspace cannot be enumerated") from exc
    expected = {"prompt.md", "task.json", "result.md"}
    unexpected = names - expected
    missing = expected - names
    if unexpected:
        raise WorkerTaskInvalid(
            "worker workspace contains unexpected paths: " + ", ".join(sorted(unexpected))
        )
    if missing:
        raise WorkerTaskInvalid(
            "worker workspace is missing required paths: " + ", ".join(sorted(missing))
        )


def _read_workspace_files(
    workspace: Path,
    root: _BoundRootView,
    task: _TaskView,
) -> tuple[str, str, str]:
    prompt = read_task_text(
        workspace / "prompt.md",
        root.path,
        max_bytes=MAX_AGENT_TASK_BYTES,
        root_identity=root.identity,
    )
    staged_task = read_task_text(
        workspace / "task.json",
        root.path,
        max_bytes=MAX_AGENT_SIDECAR_BYTES,
        root_identity=root.identity,
    )
    result = read_task_text(
        workspace / "result.md",
        root.path,
        max_bytes=min(MAX_AGENT_RESULT_BYTES, task.max_result_bytes),
        root_identity=root.identity,
    )
    if prompt is None or staged_task is None or result is None:
        raise WorkerTaskInvalid("worker workspace contains an unsafe or oversized file")
    return prompt, staged_task, result


def _json_mapping(text: str, *, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkerTaskInvalid(f"{label} is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise WorkerTaskInvalid(f"{label} must be a JSON object")
    return dict(cast(Mapping[str, Any], value))


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _required_text(payload: Mapping[str, Any], field: str, *, strip: bool = True) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise WorkerTaskInvalid(f"{field} must be a string")
    normalized = value.strip() if strip else value
    if not normalized:
        raise WorkerTaskInvalid(f"{field} must be non-empty")
    return normalized


def _required_positive_int(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkerTaskInvalid(f"{field} must be a positive integer")
    return value


def _required_timestamp(payload: Mapping[str, Any], field: str) -> datetime:
    text = _required_text(payload, field)
    return _parse_timestamp(text, field=field)


def _parse_timestamp(text: str, *, field: str) -> datetime:
    try:
        value = datetime.fromisoformat(text)
    except ValueError as exc:
        raise WorkerTaskInvalid(f"{field} must be an ISO 8601 timestamp") from exc
    if value.tzinfo is None:
        raise WorkerTaskInvalid(f"{field} must include a timezone")
    return value.astimezone(UTC)


def _validated_task_id(value: str) -> str:
    normalized = value.strip().lower()
    if not _TASK_ID_RE.fullmatch(normalized):
        raise WorkerTaskInvalid("task id must be exactly 12 lowercase hexadecimal characters")
    return normalized


def _validated_label(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if not _LABEL_RE.fullmatch(normalized):
        raise WorkerTaskInvalid(
            f"{field} must use 1 to 64 letters, digits, dots, underscores, or hyphens"
        )
    return normalized


def _validated_workload_filter(value: str) -> str:
    normalized = value.strip()
    if normalized and not _WORKLOAD_RE.fullmatch(normalized):
        raise WorkerTaskInvalid("workload filter contains unsupported characters")
    return normalized


def _validated_model(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > 200 or any(ord(char) < 32 for char in normalized):
        raise WorkerTaskInvalid("model must be at most 200 printable characters")
    return normalized


def _validated_reason(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 500 or any(ord(char) < 32 for char in normalized):
        raise WorkerTaskInvalid("reason must contain 1 to 500 printable characters")
    return normalized


def _claim_token_hash(value: object) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 512:
        raise WorkerTaskInvalid("claim token is missing or malformed")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_usage(input_tokens: object | None, output_tokens: object | None) -> None:
    if (input_tokens is None) != (output_tokens is None):
        raise WorkerTaskInvalid("input and output token counts must be supplied together")
    for label, value in (("input tokens", input_tokens), ("output tokens", output_tokens)):
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= MAX_USAGE_TOKENS
        ):
            raise WorkerTaskInvalid(f"{label} must be between 0 and {MAX_USAGE_TOKENS}")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _staged_prompt_bytes(prompt: str) -> bytes:
    normalized = prompt.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized.encode("utf-8")


def _normalized_result_bytes(result: str) -> bytes:
    normalized = result.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    content = normalized.encode("utf-8")
    if len(content) > MAX_AGENT_RESULT_BYTES:
        raise WorkerTaskInvalid("worker result exceeds the global result size limit")
    return content
