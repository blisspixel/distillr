# pyright: strict
"""Shared receipt contract for host-session AgentProvider submissions."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from distill.llm.usage import MAX_USAGE_TOKENS

WORKER_PROTOCOL_VERSION = "agent-worker.v1"
WORKER_CLAIM_SCHEMA_VERSION = "agent-worker-claim.v1"
WORKER_SUBMISSION_SCHEMA_VERSION = "agent-worker-submission.v1"
WORKER_ABANDONMENT_SCHEMA_VERSION = "agent-worker-abandonment.v1"
MAX_AGENT_SIDECAR_BYTES = 128 * 1024

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TOKEN_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_WORKLOAD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$")
_SUBMISSION_FIELDS = frozenset(
    {
        "schema_version",
        "protocol",
        "task_id",
        "workload",
        "prompt_hash",
        "claim_token_hash",
        "host",
        "worker_id",
        "model",
        "claimed_at",
        "submitted_at",
        "elapsed_ms",
        "result_sha256",
        "result_bytes",
        "usage",
        "billing",
        "files_read",
        "files_written",
        "published_result",
    }
)


@dataclass(frozen=True)
class HostSubmission:
    """Validated metadata for one result produced in an active host session."""

    task_id: str
    prompt_hash: str
    claim_token_hash: str
    host: str
    worker_id: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    usage_source: str
    result_sha256: str

    @property
    def model_label(self) -> str:
        return self.model or f"host:{self.host}"


def validate_host_submission(
    payload: Mapping[str, Any],
    *,
    task_id: str,
    prompt_hash: str,
    result_text: str,
) -> HostSubmission:
    """Validate a worker submission against its task and published result."""

    _validate_envelope(payload, task_id=task_id, prompt_hash=prompt_hash)
    host = _required_label(payload, "host")
    worker_id = _required_label(payload, "worker_id")
    claim_token_hash = _required_string(payload, "claim_token_hash")
    if not _TOKEN_HASH_RE.fullmatch(claim_token_hash):
        raise ValueError("worker submission claim token hash is invalid")
    model = payload.get("model", "")
    if (
        not isinstance(model, str)
        or len(model) > 200
        or any(ord(character) < 32 for character in model)
    ):
        raise ValueError("worker submission model is invalid")
    result_bytes = _normalized_result_bytes(result_text)
    expected_result_hash = _result_sha256(result_bytes)
    if payload.get("result_sha256") != expected_result_hash:
        raise ValueError("worker submission result hash does not match the published result")
    _validate_result_evidence(payload, task_id=task_id, result_bytes=result_bytes)
    _validate_timing(payload)
    input_tokens, output_tokens, usage_source = _validated_usage(payload)
    _validate_billing(payload)
    return HostSubmission(
        task_id=task_id,
        prompt_hash=prompt_hash,
        claim_token_hash=claim_token_hash,
        host=host,
        worker_id=worker_id,
        model=model.strip(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usage_source=usage_source,
        result_sha256=expected_result_hash,
    )


def _validate_envelope(
    payload: Mapping[str, Any],
    *,
    task_id: str,
    prompt_hash: str,
) -> None:
    if frozenset(payload) != _SUBMISSION_FIELDS:
        raise ValueError("worker submission fields do not match the supported schema")
    if payload.get("schema_version") != WORKER_SUBMISSION_SCHEMA_VERSION:
        raise ValueError("worker submission schema is unsupported")
    if payload.get("protocol") != WORKER_PROTOCOL_VERSION:
        raise ValueError("worker submission protocol is unsupported")
    if payload.get("task_id") != task_id or payload.get("prompt_hash") != prompt_hash:
        raise ValueError("worker submission task identity does not match")


def _validate_result_evidence(
    payload: Mapping[str, Any],
    *,
    task_id: str,
    result_bytes: bytes,
) -> None:
    workload = payload.get("workload")
    if not isinstance(workload, str) or not _WORKLOAD_RE.fullmatch(workload):
        raise ValueError("worker submission workload is invalid")
    if payload.get("result_bytes") != len(result_bytes):
        raise ValueError("worker submission result byte count does not match")
    if payload.get("files_read") != ["prompt.md", "task.json"]:
        raise ValueError("worker submission read set is invalid")
    if payload.get("files_written") != ["result.md"]:
        raise ValueError("worker submission write set is invalid")
    expected_result = f"{workload}_{task_id}_result.md"
    if payload.get("published_result") != expected_result:
        raise ValueError("worker submission published result identity is invalid")


def _validate_timing(payload: Mapping[str, Any]) -> None:
    claimed_at = _timestamp(payload.get("claimed_at"), field="claimed_at")
    submitted_at = _timestamp(payload.get("submitted_at"), field="submitted_at")
    if submitted_at < claimed_at:
        raise ValueError("worker submission predates its claim")
    elapsed_ms = payload.get("elapsed_ms")
    expected_elapsed_ms = int((submitted_at - claimed_at).total_seconds() * 1000)
    if (
        isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, int)
        or elapsed_ms != expected_elapsed_ms
    ):
        raise ValueError("worker submission elapsed time is invalid")


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"worker submission {field} must be an ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"worker submission {field} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"worker submission {field} must include a timezone")
    return parsed.astimezone(UTC)


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"worker submission {field} must be a non-empty string")
    return value.strip()


def _required_label(payload: Mapping[str, Any], field: str) -> str:
    value = _required_string(payload, field).lower()
    if not _LABEL_RE.fullmatch(value):
        raise ValueError(f"worker submission {field} is invalid")
    return value


def _validated_usage(payload: Mapping[str, Any]) -> tuple[int | None, int | None, str]:
    usage_value = payload.get("usage")
    if not isinstance(usage_value, Mapping):
        raise ValueError("worker submission usage must be an object")
    usage = cast(Mapping[str, object], usage_value)
    if set(usage) != {"input_tokens", "output_tokens", "source"}:
        raise ValueError("worker submission usage fields are invalid")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    source = usage.get("source")
    if (input_tokens is None) != (output_tokens is None):
        raise ValueError("worker submission token counts must be supplied together")
    _validate_token_count(input_tokens, "input_tokens")
    _validate_token_count(output_tokens, "output_tokens")
    expected_source = "host-reported" if input_tokens is not None else "host-managed-unavailable"
    if source != expected_source:
        raise ValueError("worker submission usage source does not match its token evidence")
    return cast(int | None, input_tokens), cast(int | None, output_tokens), expected_source


def _validate_token_count(value: object, field: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_USAGE_TOKENS:
        raise ValueError(f"worker submission {field} is outside the supported range")


def _validate_billing(payload: Mapping[str, Any]) -> None:
    billing_value = payload.get("billing")
    if not isinstance(billing_value, Mapping):
        raise ValueError("worker submission billing must be an object")
    billing = cast(Mapping[str, object], billing_value)
    if set(billing) != {"class", "no_metered_proven", "proof"}:
        raise ValueError("worker submission billing fields are invalid")
    if billing.get("class") != "host-managed":
        raise ValueError("worker submission billing class must be host-managed")
    if billing.get("no_metered_proven") is not False:
        raise ValueError("worker submission cannot claim proven no-metered billing")
    if billing.get("proof") != "unavailable":
        raise ValueError("worker submission billing proof must remain unavailable")


def _normalized_result_bytes(result_text: str) -> bytes:
    normalized = result_text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized.encode("utf-8")


def _result_sha256(result_bytes: bytes) -> str:
    return f"sha256:{hashlib.sha256(result_bytes).hexdigest()}"
