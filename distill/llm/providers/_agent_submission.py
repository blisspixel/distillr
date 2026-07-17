# pyright: strict
"""Bounded host-session receipt loading for deferred agent results."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from distill.llm.providers._agent_files import (
    read_task_text,
    task_root_is_unchanged,
    validated_task_root,
)
from distill.llm.providers._agent_protocol import (
    MAX_AGENT_SIDECAR_BYTES,
    HostSubmission,
    validate_host_submission,
)

TaskRootResolver = Callable[[Path, str], Path | None]


def read_host_submission(
    task_path: Path,
    result_text: str,
    prompt_hash: str,
    *,
    pending_dir: Path,
    task_root: TaskRootResolver,
    bound_root: tuple[Path, tuple[int, int]] | None = None,
) -> HostSubmission | None:
    """Read and validate optional host-session metadata for a result."""

    submission_path = task_path.with_suffix(".submission")
    try:
        submission_path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("agent submission receipt cannot be inspected") from exc
    if bound_root is None:
        pending_root = task_root(pending_dir, "pending")
        validated_root = None if pending_root is None else validated_task_root(pending_root)
        if validated_root is None:
            raise ValueError("agent submission root is unavailable")
        pending_root, root_identity = validated_root
    else:
        pending_root, root_identity = bound_root
        if not task_root_is_unchanged(pending_root, root_identity):
            raise ValueError("agent submission root changed before receipt validation")
    if task_path.parent != pending_root:
        raise ValueError("agent submission task is outside the pending root")
    text = read_task_text(
        submission_path,
        pending_root,
        max_bytes=MAX_AGENT_SIDECAR_BYTES,
        root_identity=root_identity,
    )
    if text is None:
        raise ValueError("agent submission receipt is unsafe or unreadable")
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("agent submission receipt is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("agent submission receipt must be a JSON object")
    task_id = task_path.stem.rsplit("_", 1)[-1]
    return validate_host_submission(
        cast(Mapping[str, object], payload),
        task_id=task_id,
        prompt_hash=prompt_hash,
        result_text=result_text,
    )
