# pyright: strict
"""Bounded pending-task discovery and exact-prompt deduplication."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

from distill.llm.providers._agent_files import read_task_text, task_root_is_unchanged
from distill.llm.providers._agent_protocol import (
    AGENT_TASK_SCHEMA_VERSION,
    MAX_AGENT_PENDING_TASKS,
    MAX_AGENT_TASK_BYTES,
    WORKER_PROTOCOL_VERSION,
    agent_result_byte_limit,
)
from distill.llm.router import ConfigurationError

DirectResultPath = Callable[[Path, Path, tuple[int, int]], Path | None]


def pending_task_paths(
    pending_root: Path,
    root_identity: tuple[int, int],
) -> tuple[Path, ...]:
    """Enumerate a bounded snapshot of direct pending task manifests."""

    if not task_root_is_unchanged(pending_root, root_identity):
        raise ConfigurationError("AgentProvider pending task root changed during enumeration.")
    paths: list[Path] = []
    try:
        with os.scandir(pending_root) as entries:
            for entry in entries:
                if not entry.name.endswith(".json"):
                    continue
                if len(paths) >= MAX_AGENT_PENDING_TASKS:
                    raise ConfigurationError(
                        f"AgentProvider pending task limit is {MAX_AGENT_PENDING_TASKS}."
                    )
                paths.append(pending_root / entry.name)
    except OSError as exc:
        raise ConfigurationError("AgentProvider pending task directory cannot be read.") from exc
    if not task_root_is_unchanged(pending_root, root_identity):
        raise ConfigurationError("AgentProvider pending task root changed during enumeration.")
    return tuple(sorted(paths, key=lambda path: path.name))


def find_existing_task(
    prompt: str,
    workload_tag: str,
    *,
    target_hash: str,
    bound_root: tuple[Path, tuple[int, int]],
    direct_result_path: DirectResultPath,
) -> Path | None:
    """Find one existing task for an exact prompt, whether completed or pending."""

    pending_root, root_identity = bound_root
    prefix = f"{workload_tag}_"
    for task_path in pending_task_paths(pending_root, root_identity):
        if not task_path.name.startswith(prefix):
            continue
        task_text = read_task_text(
            task_path,
            pending_root,
            max_bytes=MAX_AGENT_TASK_BYTES,
            root_identity=root_identity,
        )
        if task_text is None:
            continue
        try:
            payload: object = json.loads(task_text)
        except (json.JSONDecodeError, RecursionError):
            continue
        if not isinstance(payload, dict):
            continue
        task_payload = cast("dict[str, object]", payload)
        task_id = task_payload.get("task_id")
        result_value = task_payload.get("result_path")
        max_tokens = task_payload.get("max_tokens")
        timeout_seconds = task_payload.get("timeout_seconds")
        if (
            task_payload.get("schema_version") != AGENT_TASK_SCHEMA_VERSION
            or task_payload.get("prompt_hash") != target_hash
            or task_payload.get("prompt") != prompt
            or task_payload.get("workload_tag") != workload_tag
            or not isinstance(task_id, str)
            or len(task_id) != 12
            or any(character not in "0123456789abcdef" for character in task_id)
            or task_path.name != f"{workload_tag}_{task_id}.json"
            or task_payload.get("expected_output_format") != "markdown"
            or not isinstance(result_value, str)
            or isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds <= 0
            or task_payload.get("max_result_bytes") != agent_result_byte_limit(max_tokens)
            or task_payload.get("worker_protocol") != WORKER_PROTOCOL_VERSION
            or task_payload.get("billing_class") != "host-managed"
        ):
            continue
        result_path = direct_result_path(
            Path(result_value),
            pending_root,
            root_identity,
        )
        if result_path is None or result_path.name != f"{workload_tag}_{task_id}_result.md":
            continue
        return task_path
    return None
