# pyright: strict
"""Claim envelope validation and construction for worker tasks."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from distill.llm.providers._agent_protocol import (
    WORKER_CLAIM_SCHEMA_VERSION,
    WORKER_PROTOCOL_VERSION,
)
from distill.worker._contracts import (
    WorkerTaskInvalid,
    required_text,
    required_timestamp,
    validated_label,
)
from distill.worker._models import Claim as _Claim
from distill.worker._models import PendingTask as _PendingTask

__all__ = [
    "_CLAIM_FIELDS",
    "_SHA256_RE",
    "_TOKEN_HASH_RE",
    "_claim_from_payload",
    "_validate_claim_envelope",
    "_validate_claim_policy",
    "_validated_claim_text",
]

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TOKEN_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_FIELDS = frozenset(
    {
        "schema_version",
        "protocol",
        "task_id",
        "prompt_hash",
        "claim_token_hash",
        "host",
        "worker_id",
        "billing_class",
        "no_metered_proven",
        "claimed_at",
        "lease_expires_at",
        "workspace",
        "prompt_sha256",
        "task_sha256",
        "allowed_write_paths",
    }
)


def _claim_from_payload(
    task: _PendingTask,
    payload: Mapping[str, Any],
    raw_bytes: bytes,
) -> _Claim:
    _validate_claim_envelope(task, payload)
    token_hash, host, worker_id, workspace_name, prompt_sha256, task_sha256 = _validated_claim_text(
        task, payload
    )
    claimed_at = required_timestamp(payload, "claimed_at")
    lease_expires_at = required_timestamp(payload, "lease_expires_at")
    _validate_claim_policy(task, payload, claimed_at, lease_expires_at)
    return _Claim(
        task_id=task.task_id,
        prompt_hash=task.prompt_hash,
        token_hash=token_hash,
        host=host,
        worker_id=worker_id,
        workspace_name=workspace_name,
        claimed_at=claimed_at,
        lease_expires_at=lease_expires_at,
        prompt_sha256=prompt_sha256,
        task_sha256=task_sha256,
        raw_bytes=raw_bytes,
    )


def _validate_claim_envelope(task: _PendingTask, payload: Mapping[str, Any]) -> None:
    if set(payload) != set(_CLAIM_FIELDS):
        raise WorkerTaskInvalid(f"claim fields do not match schema for task {task.task_id}")
    if payload.get("schema_version") != WORKER_CLAIM_SCHEMA_VERSION:
        raise WorkerTaskInvalid(f"claim has an unsupported schema for task {task.task_id}")
    if payload.get("protocol") != WORKER_PROTOCOL_VERSION:
        raise WorkerTaskInvalid(f"claim has an unsupported protocol for task {task.task_id}")
    if payload.get("task_id") != task.task_id or payload.get("prompt_hash") != task.prompt_hash:
        raise WorkerTaskInvalid(f"claim identity mismatch for task {task.task_id}")


def _validated_claim_text(
    task: _PendingTask,
    payload: Mapping[str, Any],
) -> tuple[str, str, str, str, str, str]:
    token_hash = required_text(payload, "claim_token_hash")
    host = required_text(payload, "host")
    worker_id = required_text(payload, "worker_id")
    workspace_name = required_text(payload, "workspace")
    prompt_sha256 = required_text(payload, "prompt_sha256")
    task_sha256 = required_text(payload, "task_sha256")
    if not _TOKEN_HASH_RE.fullmatch(token_hash):
        raise WorkerTaskInvalid(f"claim token hash is invalid for task {task.task_id}")
    if host != validated_label(host, field="claim host"):
        raise WorkerTaskInvalid(f"claim host is not canonical for task {task.task_id}")
    if worker_id != validated_label(worker_id, field="claim worker id"):
        raise WorkerTaskInvalid(f"claim worker id is not canonical for task {task.task_id}")
    if workspace_name != f"{task.task_id}-{token_hash[:16]}":
        raise WorkerTaskInvalid(f"claim workspace mismatch for task {task.task_id}")
    if not _SHA256_RE.fullmatch(prompt_sha256) or not _SHA256_RE.fullmatch(task_sha256):
        raise WorkerTaskInvalid(f"claim staging hash is invalid for task {task.task_id}")
    return token_hash, host, worker_id, workspace_name, prompt_sha256, task_sha256


def _validate_claim_policy(
    task: _PendingTask,
    payload: Mapping[str, Any],
    claimed_at: datetime,
    lease_expires_at: datetime,
) -> None:
    if lease_expires_at <= claimed_at:
        raise WorkerTaskInvalid(f"claim lease is invalid for task {task.task_id}")
    if payload.get("billing_class") != "host-managed":
        raise WorkerTaskInvalid(f"claim billing metadata is invalid for task {task.task_id}")
    if payload.get("no_metered_proven") is not False:
        raise WorkerTaskInvalid(f"claim billing metadata is invalid for task {task.task_id}")
    if payload.get("allowed_write_paths") != ["result.md"]:
        raise WorkerTaskInvalid(f"claim write boundary is invalid for task {task.task_id}")
