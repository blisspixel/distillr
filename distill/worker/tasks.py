"""Secure claim and submission service for deferred host-session tasks."""

from __future__ import annotations

import hmac
import re
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from distill.llm.providers._agent_directories import (
    create_task_directory,
    remove_task_directory,
)
from distill.llm.providers._agent_files import (
    read_task_text,
    remove_task_file,
    task_root_is_unchanged,
    validated_task_root,
    write_task_bytes,
)
from distill.llm.providers._agent_protocol import (
    MAX_AGENT_SIDECAR_BYTES,
    WORKER_ABANDONMENT_SCHEMA_VERSION,
    WORKER_CLAIM_SCHEMA_VERSION,
    WORKER_PROTOCOL_VERSION,
    WORKER_SUBMISSION_SCHEMA_VERSION,
    validate_host_submission,
)
from distill.llm.providers.agent import (
    MAX_AGENT_TASK_BYTES,
    AgentProvider,
    agent_result_byte_limit,
)
from distill.worker._contracts import (
    WorkerTaskConflict,
    WorkerTaskError,
    WorkerTaskInvalid,
    WorkerTaskNotFound,
    _claim_token_hash,
    _json_bytes,
    _json_mapping,
    _normalized_result_bytes,
    _optional_creation_timestamp,
    _read_workspace_files,
    _required_positive_int,
    _required_text,
    _required_timestamp,
    _sha256,
    _staged_prompt_bytes,
    _validate_declared_result_limit,
    _validate_existing_submission,
    _validate_usage,
    _validate_workspace_names,
    _validated_label,
    _validated_model,
    _validated_reason,
    _validated_task_id,
    _validated_task_identity,
    _validated_workload_filter,
)
from distill.worker._models import BoundRoot as _BoundRoot
from distill.worker._models import Claim as _Claim
from distill.worker._models import PendingTask as _PendingTask

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


class AgentTaskQueue:
    """Operate the existing AgentProvider queue through a scratch-only protocol."""

    def __init__(
        self,
        ops_dir: Path | str,
        *,
        now: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        text = str(ops_dir).strip()
        if not text:
            raise WorkerTaskInvalid("worker queue requires a non-empty ops directory")
        self._ops_dir = Path(text)
        self._provider = AgentProvider(text)
        self._pending_dir = self._ops_dir / "tasks" / "pending"
        self._work_dir = self._ops_dir / "tasks" / "work"
        self._now = now or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return prompt-free status rows for every structurally visible task."""

        root = self._pending_root(create=False)
        if root is None:
            return []
        rows: list[dict[str, Any]] = []
        for path in self._task_paths(root):
            try:
                task = self._load_task(path, root)
                rows.append(self._task_status(task, root))
            except WorkerTaskError as exc:
                rows.append(
                    {
                        "status": "invalid",
                        "task_path": str(path),
                        "error": str(exc),
                    }
                )
        return rows

    def claim(
        self,
        *,
        host: str,
        worker_id: str = "interactive",
        workload: str = "",
        lease_seconds: int = 3600,
    ) -> dict[str, Any] | None:
        """Claim the first eligible task and stage its constrained workspace."""

        host = _validated_label(host, field="host")
        worker_id = _validated_label(worker_id, field="worker id")
        workload_filter = _validated_workload_filter(workload)
        if isinstance(lease_seconds, bool) or not 60 <= lease_seconds <= 604_800:
            raise WorkerTaskInvalid("lease seconds must be between 60 and 604800")

        root = self._pending_root(create=False)
        if root is None:
            return None
        for path in self._task_paths(root):
            task = self._load_task(path, root)
            if workload_filter and task.workload != workload_filter:
                continue
            if self._read_result(task, root) is not None:
                continue
            if self._claim_path(task).exists():
                self._load_claim(task, root)
                continue
            return self._claim_task(
                task,
                root,
                host=host,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
        return None

    def submit(
        self,
        task_id: str,
        *,
        claim_token: str,
        model: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Validate a claimed scratch result and publish it atomically."""

        task_id = _validated_task_id(task_id)
        token_hash = _claim_token_hash(claim_token)
        model = _validated_model(model)
        _validate_usage(input_tokens, output_tokens)
        root = self._required_pending_root()
        task = self._find_task(task_id, root)
        claim = self._required_claim(task, root, token_hash)
        workspace, workspace_root = self._workspace(claim)
        prompt_text, staged_task, result_text = self._validated_workspace(
            task,
            claim,
            workspace,
            workspace_root,
        )
        del prompt_text, staged_task

        result_bytes = _normalized_result_bytes(result_text)
        existing_result = self._read_result(task, root)
        if (
            existing_result is not None
            and _normalized_result_bytes(existing_result) != result_bytes
        ):
            raise WorkerTaskConflict("task already has a different published result")

        existing_submission = self._load_submission(task, root)
        if existing_submission is not None:
            _validate_existing_submission(task, claim, existing_submission, result_bytes)
            self._publish_result(task, root, result_bytes)
            return self._submission_result(
                task,
                claim,
                existing_submission,
                idempotent=True,
            )

        submitted_at = self._current_time()
        submission = self._submission_payload(
            task,
            claim,
            result_bytes,
            submitted_at=submitted_at,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        try:
            validate_host_submission(
                submission,
                task_id=task.task_id,
                prompt_hash=task.prompt_hash,
                result_text=result_bytes.decode("utf-8"),
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorkerTaskInvalid(f"generated submission receipt is invalid: {exc}") from exc
        submission_bytes = _json_bytes(submission)
        submission_path = self._submission_path(task)
        self._publish_receipt(
            submission_path,
            submission_bytes,
            root,
            receipt_name="submission",
        )
        self._publish_result(task, root, result_bytes)
        return self._submission_result(
            task,
            claim,
            submission,
            idempotent=existing_result is not None,
        )

    def _submission_result(
        self,
        task: _PendingTask,
        claim: _Claim,
        submission: Mapping[str, Any],
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {
            "submitted": True,
            "idempotent": idempotent,
            "task_id": task.task_id,
            "workload": task.workload,
            "host": claim.host,
            "worker_id": claim.worker_id,
            "model": submission.get("model", ""),
            "published_result_path": str(task.result_path),
            "submission_receipt_path": str(self._submission_path(task)),
            "result_sha256": submission["result_sha256"],
            "usage": submission["usage"],
            "billing": submission["billing"],
        }

    def abandon(
        self,
        task_id: str,
        *,
        claim_token: str,
        reason: str,
    ) -> dict[str, Any]:
        """Release a claim without publishing its scratch result."""

        task_id = _validated_task_id(task_id)
        token_hash = _claim_token_hash(claim_token)
        reason = _validated_reason(reason)
        root = self._required_pending_root()
        task = self._find_task(task_id, root)
        if self._read_result(task, root) is not None:
            raise WorkerTaskConflict("completed tasks cannot be abandoned")
        claim = self._required_claim(task, root, token_hash)
        abandoned_at = self._current_time()
        payload = {
            "schema_version": WORKER_ABANDONMENT_SCHEMA_VERSION,
            "protocol": WORKER_PROTOCOL_VERSION,
            "task_id": task.task_id,
            "prompt_hash": task.prompt_hash,
            "claim_token_hash": claim.token_hash,
            "host": claim.host,
            "worker_id": claim.worker_id,
            "workspace": claim.workspace_name,
            "reason": reason,
            "abandoned_at": abandoned_at.isoformat(),
        }
        event_path = root.path / f"{task.stem}.abandoned.{claim.token_hash[:16]}"
        self._publish_receipt(
            event_path,
            _json_bytes(payload),
            root,
            receipt_name="abandonment",
        )
        claim_path = self._claim_path(task)
        if not remove_task_file(
            claim_path,
            root.path,
            root.identity,
            expected_content=claim.raw_bytes,
        ):
            raise WorkerTaskConflict("claim changed before it could be released")
        return {
            "abandoned": True,
            "task_id": task.task_id,
            "workload": task.workload,
            "reason": reason,
            "abandonment_receipt_path": str(event_path),
        }

    def release_expired(self, task_id: str) -> dict[str, Any]:
        """Release an expired claim when no submission has started."""

        task_id = _validated_task_id(task_id)
        root = self._required_pending_root()
        task = self._find_task(task_id, root)
        if self._read_result(task, root) is not None or self._submission_path(task).exists():
            raise WorkerTaskConflict("a completed or submitting task cannot be released")
        claim = self._load_claim(task, root)
        if claim is None:
            raise WorkerTaskNotFound(f"task {task_id} has no active claim")
        now = self._current_time()
        if claim.lease_expires_at > now:
            raise WorkerTaskConflict(
                f"claim remains active until {claim.lease_expires_at.isoformat()}"
            )
        payload = {
            "schema_version": WORKER_ABANDONMENT_SCHEMA_VERSION,
            "protocol": WORKER_PROTOCOL_VERSION,
            "task_id": task.task_id,
            "prompt_hash": task.prompt_hash,
            "claim_token_hash": claim.token_hash,
            "host": claim.host,
            "worker_id": claim.worker_id,
            "workspace": claim.workspace_name,
            "reason": "expired lease released by operator",
            "abandoned_at": now.isoformat(),
            "release_class": "expired-claim",
        }
        event_path = root.path / f"{task.stem}.expired.{claim.token_hash[:16]}"
        self._publish_receipt(
            event_path,
            _json_bytes(payload),
            root,
            receipt_name="expired release",
        )
        if not remove_task_file(
            self._claim_path(task),
            root.path,
            root.identity,
            expected_content=claim.raw_bytes,
        ):
            raise WorkerTaskConflict("claim changed before it could be released")
        return {
            "released": True,
            "task_id": task.task_id,
            "expired_at": claim.lease_expires_at.isoformat(),
            "release_receipt_path": str(event_path),
        }

    def _pending_root(self, *, create: bool) -> _BoundRoot | None:
        if create:
            self._provider._ensure_task_dir(self._pending_dir, "pending")
        elif not self._pending_dir.exists():
            return None
        path = self._provider._task_root(self._pending_dir, "pending")
        validated = None if path is None else validated_task_root(path)
        if validated is None:
            if create:
                raise WorkerTaskInvalid("pending task directory is not safe")
            return None
        return _BoundRoot(*validated)

    def _required_pending_root(self) -> _BoundRoot:
        root = self._pending_root(create=False)
        if root is None:
            raise WorkerTaskNotFound("no pending task directory exists")
        return root

    def _work_root(self) -> _BoundRoot:
        self._provider._ensure_task_dir(self._work_dir, "work")
        path = self._provider._task_root(self._work_dir, "work")
        validated = None if path is None else validated_task_root(path)
        if validated is None:
            raise WorkerTaskInvalid("worker scratch directory is not safe")
        return _BoundRoot(*validated)

    def _task_paths(self, root: _BoundRoot) -> tuple[Path, ...]:
        try:
            paths = tuple(sorted(root.path.glob("*.json"), key=lambda path: path.name))
        except OSError as exc:
            raise WorkerTaskInvalid("pending task directory could not be enumerated") from exc
        if not task_root_is_unchanged(root.path, root.identity):
            raise WorkerTaskInvalid("pending task directory changed during enumeration")
        return paths

    def _load_task(self, path: Path, root: _BoundRoot) -> _PendingTask:
        text = read_task_text(
            path,
            root.path,
            max_bytes=MAX_AGENT_TASK_BYTES,
            root_identity=root.identity,
        )
        if text is None:
            raise WorkerTaskInvalid(f"unsafe or unreadable task file: {path.name}")
        payload = _json_mapping(text, label=f"task {path.name}")
        task_id, workload, prompt, prompt_hash = _validated_task_identity(payload, path)
        max_tokens = _required_positive_int(payload, "max_tokens")
        timeout_seconds = _required_positive_int(payload, "timeout_seconds")
        result_path = self._validated_result_path(
            payload,
            path,
            root,
            task_id=task_id,
            workload=workload,
        )
        max_result_bytes = agent_result_byte_limit(max_tokens)
        _validate_declared_result_limit(payload, path, max_result_bytes)
        created_at = _optional_creation_timestamp(payload, path)
        return _PendingTask(
            task_id=task_id,
            workload=workload,
            prompt=prompt,
            prompt_hash=prompt_hash,
            task_path=path,
            task_bytes=text.encode("utf-8"),
            result_path=result_path,
            max_tokens=max_tokens,
            max_result_bytes=max_result_bytes,
            timeout_seconds=timeout_seconds,
            created_at=created_at,
        )

    def _validated_result_path(
        self,
        payload: Mapping[str, Any],
        path: Path,
        root: _BoundRoot,
        *,
        task_id: str,
        workload: str,
    ) -> Path:
        result_value = payload.get("result_path")
        if not isinstance(result_value, str):
            raise WorkerTaskInvalid(f"task {path.name} has no valid result path")
        result_path = self._provider._direct_pending_result_path(
            Path(result_value),
            root.path,
            root.identity,
        )
        expected_result_name = f"{workload}_{task_id}_result.md"
        if result_path is None or result_path.name != expected_result_name:
            raise WorkerTaskInvalid(f"task {path.name} result path is outside the queue contract")
        return result_path

    def _find_task(self, task_id: str, root: _BoundRoot) -> _PendingTask:
        matches: list[_PendingTask] = []
        for path in self._task_paths(root):
            try:
                task = self._load_task(path, root)
            except WorkerTaskInvalid:
                continue
            if task.task_id == task_id:
                matches.append(task)
        if not matches:
            raise WorkerTaskNotFound(f"task not found: {task_id}")
        if len(matches) != 1:
            raise WorkerTaskInvalid(f"multiple pending tasks declare id {task_id}")
        return matches[0]

    def _task_status(self, task: _PendingTask, root: _BoundRoot) -> dict[str, Any]:
        result = self._read_result(task, root)
        claim = self._load_claim(task, root)
        status = "completed" if result is not None else ("claimed" if claim else "pending")
        row: dict[str, Any] = {
            "task_id": task.task_id,
            "workload": task.workload,
            "status": status,
            "created_at": task.created_at,
            "max_tokens": task.max_tokens,
            "timeout_seconds": task.timeout_seconds,
            "task_path": str(task.task_path),
        }
        if claim is not None:
            row["claim"] = {
                "host": claim.host,
                "worker_id": claim.worker_id,
                "claimed_at": claim.claimed_at.isoformat(),
                "lease_expires_at": claim.lease_expires_at.isoformat(),
                "lease_expired": claim.lease_expires_at <= self._current_time(),
                "workspace": str(self._work_dir / claim.workspace_name),
            }
        if result is not None:
            row["result_path"] = str(task.result_path)
            row["submission_receipt_path"] = str(self._submission_path(task))
        return row

    def _claim_task(
        self,
        task: _PendingTask,
        root: _BoundRoot,
        *,
        host: str,
        worker_id: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        claim_token = self._token_factory()
        token_hash = _claim_token_hash(claim_token)
        workspace_name = f"{task.task_id}-{token_hash[:16]}"
        claimed_at = self._current_time()
        prompt_bytes = _staged_prompt_bytes(task.prompt)
        staged_task = self._staged_task_payload(task)
        staged_task_bytes = _json_bytes(staged_task)
        payload = {
            "schema_version": WORKER_CLAIM_SCHEMA_VERSION,
            "protocol": WORKER_PROTOCOL_VERSION,
            "task_id": task.task_id,
            "prompt_hash": task.prompt_hash,
            "claim_token_hash": token_hash,
            "host": host,
            "worker_id": worker_id,
            "billing_class": "host-managed",
            "no_metered_proven": False,
            "claimed_at": claimed_at.isoformat(),
            "lease_expires_at": (claimed_at + timedelta(seconds=lease_seconds)).isoformat(),
            "workspace": workspace_name,
            "prompt_sha256": _sha256(prompt_bytes),
            "task_sha256": _sha256(staged_task_bytes),
            "allowed_write_paths": ["result.md"],
        }
        claim_bytes = _json_bytes(payload)
        claim_path = self._claim_path(task)
        try:
            write_task_bytes(claim_path, root.path, root.identity, claim_bytes)
        except FileExistsError:
            return None

        workspace_root: _BoundRoot | None = None
        workspace: _BoundRoot | None = None
        try:
            workspace_root = self._work_root()
            created = create_task_directory(
                workspace_root.path,
                workspace_root.identity,
                workspace_name,
            )
            workspace = _BoundRoot(*created)
            write_task_bytes(
                workspace.path / "prompt.md",
                workspace.path,
                workspace.identity,
                prompt_bytes,
            )
            write_task_bytes(
                workspace.path / "task.json",
                workspace.path,
                workspace.identity,
                staged_task_bytes,
            )
        except Exception:
            if workspace is not None and workspace_root is not None:
                self._rollback_workspace(
                    workspace,
                    workspace_root,
                    prompt_bytes=prompt_bytes,
                    task_bytes=staged_task_bytes,
                )
            remove_task_file(
                claim_path,
                root.path,
                root.identity,
                expected_content=claim_bytes,
            )
            raise

        workspace_path = workspace.path
        return {
            "claimed": True,
            "task_id": task.task_id,
            "workload": task.workload,
            "prompt_hash": task.prompt_hash,
            "claim_token": claim_token,
            "host": host,
            "worker_id": worker_id,
            "claimed_at": claimed_at.isoformat(),
            "lease_expires_at": payload["lease_expires_at"],
            "workspace": str(workspace_path),
            "prompt_path": str(workspace_path / "prompt.md"),
            "task_path": str(workspace_path / "task.json"),
            "result_path": str(workspace_path / "result.md"),
            "allowed_write_paths": [str(workspace_path / "result.md")],
            "submit_argv": [
                "distill",
                "--json",
                "worker",
                "submit",
                task.task_id,
                "--claim-token",
                claim_token,
            ],
            "billing": {
                "class": "host-managed",
                "no_metered_proven": False,
                "note": (
                    "The active host session may consume plan quota or credits. "
                    "Distill does not classify it as no-metered."
                ),
            },
        }

    def _staged_task_payload(self, task: _PendingTask) -> dict[str, Any]:
        return {
            "schema_version": WORKER_PROTOCOL_VERSION,
            "task_id": task.task_id,
            "workload": task.workload,
            "prompt_hash": task.prompt_hash,
            "expected_output_format": "markdown",
            "max_tokens": task.max_tokens,
            "max_result_bytes": task.max_result_bytes,
            "timeout_seconds": task.timeout_seconds,
            "prompt_path": "prompt.md",
            "result_path": "result.md",
            "allowed_write_paths": ["result.md"],
            "submission_rule": (
                "Write only result.md in this workspace, then submit it through "
                "the distill worker command. Do not edit corpus artifacts directly."
            ),
            "billing": {
                "class": "host-managed",
                "no_metered_proven": False,
            },
        }

    def _rollback_workspace(
        self,
        workspace: _BoundRoot,
        workspace_root: _BoundRoot,
        *,
        prompt_bytes: bytes,
        task_bytes: bytes,
    ) -> None:
        remove_task_file(
            workspace.path / "prompt.md",
            workspace.path,
            workspace.identity,
            expected_content=prompt_bytes,
        )
        remove_task_file(
            workspace.path / "task.json",
            workspace.path,
            workspace.identity,
            expected_content=task_bytes,
        )
        remove_task_directory(
            workspace.path,
            workspace_root.path,
            workspace_root.identity,
            workspace.identity,
        )

    def _load_claim(self, task: _PendingTask, root: _BoundRoot) -> _Claim | None:
        text = self._read_optional_sidecar(
            self._claim_path(task),
            root,
            label=f"claim for task {task.task_id}",
        )
        if text is None:
            return None
        payload = _json_mapping(text, label=f"claim for task {task.task_id}")
        return _claim_from_payload(task, payload, text.encode("utf-8"))

    def _read_optional_sidecar(
        self,
        path: Path,
        root: _BoundRoot,
        *,
        label: str,
    ) -> str | None:
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise WorkerTaskInvalid(f"{label} cannot be inspected") from exc
        text = read_task_text(
            path,
            root.path,
            max_bytes=MAX_AGENT_SIDECAR_BYTES,
            root_identity=root.identity,
        )
        if text is None:
            raise WorkerTaskInvalid(f"{label} is unsafe or unreadable")
        return text

    def _load_submission(
        self,
        task: _PendingTask,
        root: _BoundRoot,
    ) -> dict[str, Any] | None:
        text = self._read_optional_sidecar(
            self._submission_path(task),
            root,
            label=f"submission for task {task.task_id}",
        )
        if text is None:
            return None
        return _json_mapping(text, label=f"submission for task {task.task_id}")

    def _required_claim(
        self,
        task: _PendingTask,
        root: _BoundRoot,
        token_hash: str,
    ) -> _Claim:
        claim = self._load_claim(task, root)
        if claim is None:
            raise WorkerTaskNotFound(f"task {task.task_id} has no active claim")
        if not hmac.compare_digest(claim.token_hash, token_hash):
            raise WorkerTaskConflict("claim token does not own this task")
        return claim

    def _workspace(self, claim: _Claim) -> tuple[Path, _BoundRoot]:
        work_root = self._work_root()
        workspace = work_root.path / claim.workspace_name
        validated = validated_task_root(workspace)
        if validated is None or validated[0].parent != work_root.path:
            raise WorkerTaskInvalid(f"worker workspace is unsafe for task {claim.task_id}")
        if not task_root_is_unchanged(work_root.path, work_root.identity):
            raise WorkerTaskInvalid("worker scratch root changed during validation")
        return validated[0], _BoundRoot(*validated)

    def _validated_workspace(
        self,
        task: _PendingTask,
        claim: _Claim,
        workspace: Path,
        root: _BoundRoot,
    ) -> tuple[str, str, str]:
        _validate_workspace_names(workspace)
        prompt, staged_task, result = _read_workspace_files(workspace, root, task)
        self._verify_staged_workspace(task, claim, prompt, staged_task)
        if not result.strip():
            raise WorkerTaskInvalid("worker result must contain non-whitespace markdown")
        if not task_root_is_unchanged(root.path, root.identity):
            raise WorkerTaskInvalid("worker workspace changed during validation")
        return prompt, staged_task, result

    def _verify_staged_workspace(
        self,
        task: _PendingTask,
        claim: _Claim,
        prompt: str,
        staged_task: str,
    ) -> None:
        if not hmac.compare_digest(_sha256(prompt.encode("utf-8")), claim.prompt_sha256):
            raise WorkerTaskConflict("staged prompt changed after the task was claimed")
        if not hmac.compare_digest(_sha256(staged_task.encode("utf-8")), claim.task_sha256):
            raise WorkerTaskConflict("staged task metadata changed after the task was claimed")
        if prompt != _staged_prompt_bytes(task.prompt).decode("utf-8"):
            raise WorkerTaskConflict("staged prompt no longer matches the pending task")
        staged_payload = _json_mapping(staged_task, label="staged worker task")
        if staged_payload != self._staged_task_payload(task):
            raise WorkerTaskConflict("staged task metadata no longer matches the pending task")

    def _submission_payload(
        self,
        task: _PendingTask,
        claim: _Claim,
        result_bytes: bytes,
        *,
        submitted_at: datetime,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> dict[str, Any]:
        usage_source = "host-reported" if input_tokens is not None else "host-managed-unavailable"
        elapsed_ms = max(0, int((submitted_at - claim.claimed_at).total_seconds() * 1000))
        return {
            "schema_version": WORKER_SUBMISSION_SCHEMA_VERSION,
            "protocol": WORKER_PROTOCOL_VERSION,
            "task_id": task.task_id,
            "workload": task.workload,
            "prompt_hash": task.prompt_hash,
            "claim_token_hash": claim.token_hash,
            "host": claim.host,
            "worker_id": claim.worker_id,
            "model": model,
            "claimed_at": claim.claimed_at.isoformat(),
            "submitted_at": submitted_at.isoformat(),
            "elapsed_ms": elapsed_ms,
            "result_sha256": _sha256(result_bytes),
            "result_bytes": len(result_bytes),
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "source": usage_source,
            },
            "billing": {
                "class": "host-managed",
                "no_metered_proven": False,
                "proof": "unavailable",
            },
            "files_read": ["prompt.md", "task.json"],
            "files_written": ["result.md"],
            "published_result": task.result_path.name,
        }

    def _publish_receipt(
        self,
        path: Path,
        content: bytes,
        root: _BoundRoot,
        *,
        receipt_name: str,
    ) -> None:
        try:
            write_task_bytes(path, root.path, root.identity, content)
            return
        except FileExistsError:
            pass
        existing = read_task_text(
            path,
            root.path,
            max_bytes=MAX_AGENT_SIDECAR_BYTES,
            root_identity=root.identity,
        )
        if existing is None or existing.encode("utf-8") != content:
            raise WorkerTaskConflict(f"task already has a different {receipt_name} receipt")

    def _publish_result(self, task: _PendingTask, root: _BoundRoot, content: bytes) -> None:
        try:
            write_task_bytes(task.result_path, root.path, root.identity, content)
            return
        except FileExistsError:
            pass
        existing = self._read_result(task, root)
        if existing is None or _normalized_result_bytes(existing) != content:
            raise WorkerTaskConflict("task already has a different published result")

    def _read_result(self, task: _PendingTask, root: _BoundRoot) -> str | None:
        try:
            task.result_path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise WorkerTaskInvalid(f"result cannot be inspected for task {task.task_id}") from exc
        result = read_task_text(
            task.result_path,
            root.path,
            max_bytes=task.max_result_bytes,
            root_identity=root.identity,
        )
        if result is None:
            raise WorkerTaskInvalid(f"result is unsafe or oversized for task {task.task_id}")
        return result.replace("\r\n", "\n").replace("\r", "\n")

    def _current_time(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise WorkerTaskInvalid("worker clock must return a timezone-aware timestamp")
        return value.astimezone(UTC)

    @staticmethod
    def _claim_path(task: _PendingTask) -> Path:
        return task.task_path.with_suffix(".claim")

    @staticmethod
    def _submission_path(task: _PendingTask) -> Path:
        return task.task_path.with_suffix(".submission")


def _claim_from_payload(
    task: _PendingTask,
    payload: Mapping[str, Any],
    raw_bytes: bytes,
) -> _Claim:
    _validate_claim_envelope(task, payload)
    token_hash, host, worker_id, workspace_name, prompt_sha256, task_sha256 = _validated_claim_text(
        task, payload
    )
    claimed_at = _required_timestamp(payload, "claimed_at")
    lease_expires_at = _required_timestamp(payload, "lease_expires_at")
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
    if set(payload) != _CLAIM_FIELDS:
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
    token_hash = _required_text(payload, "claim_token_hash")
    host = _required_text(payload, "host")
    worker_id = _required_text(payload, "worker_id")
    workspace_name = _required_text(payload, "workspace")
    prompt_sha256 = _required_text(payload, "prompt_sha256")
    task_sha256 = _required_text(payload, "task_sha256")
    if not _TOKEN_HASH_RE.fullmatch(token_hash):
        raise WorkerTaskInvalid(f"claim token hash is invalid for task {task.task_id}")
    if host != _validated_label(host, field="claim host"):
        raise WorkerTaskInvalid(f"claim host is not canonical for task {task.task_id}")
    if worker_id != _validated_label(worker_id, field="claim worker id"):
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
