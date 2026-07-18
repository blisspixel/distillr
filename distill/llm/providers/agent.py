# pyright: strict
"""Billing-unknown deferred agent execution via structured task files.

Instead of making API calls, the Agent provider writes Task_Files that an
external agentic assistant (Claude Code, Kiro, etc.) can pick up and process.
Uses SHA-256 content hashing for idempotent task lookup across retries.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from distill.llm.providers._agent_files import (
    read_task_text,
    task_root_is_unchanged,
    validated_task_root,
    write_task_bytes,
)
from distill.llm.providers._agent_pending import find_existing_task, pending_task_paths
from distill.llm.providers._agent_protocol import (
    AGENT_TASK_SCHEMA_VERSION,
    MAX_AGENT_PENDING_TASKS,
    MAX_AGENT_TASK_BYTES,
    WORKER_TRANSITION_LOCK_NAME,
    HostSubmission,
    agent_result_byte_limit,
)
from distill.llm.providers._agent_submission import read_host_submission
from distill.llm.providers._agent_transition import serialized_agent_call
from distill.llm.providers._usage import deferred_usage_attempt
from distill.llm.router import ConfigurationError, PendingTaskError
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    UsageAttemptSink,
    attach_usage_attempts,
    emit_usage_attempt,
)


class AgentProvider:
    """Deferred execution provider — writes task files for external agents."""

    def __init__(self, ops_dir: str) -> None:
        # Fail closed when no ops_dir is configured. An empty string would
        # otherwise resolve to ``Path("")`` which produces ``tasks/pending``
        # under the *current working directory* — see the security report on
        # agent task disclosure. Prompts written by this provider contain
        # full transcripts/page text/synthesis context, so silently writing
        # them next to the user's shell cwd is unsafe. Callers must pass a
        # library-scoped path (typically ``<library_dir>/.distill``).
        if not ops_dir or not ops_dir.strip():
            from distill.llm.router import ConfigurationError

            raise ConfigurationError(
                "AgentProvider requires a non-empty ops_dir. "
                "Set DISTILL_OPS_DIR or pass ops_dir explicitly so task files "
                "are written under the library directory, not the cwd."
            )
        self._ops_dir = Path(ops_dir)
        self._pending_dir = self._ops_dir / "tasks" / "pending"
        self._transition_lock_path = self._ops_dir / "tasks" / WORKER_TRANSITION_LOCK_NAME

    @property
    def transition_lock_path(self) -> Path:
        """Return the lock shared with worker-side task transitions."""

        return self._transition_lock_path

    @staticmethod
    def _prompt_hash(prompt: str, workload_tag: str) -> str:
        """SHA-256 content hash of ``"{workload_tag}:{prompt}"`` for idempotency.

        Truncated to 16 hex chars — sufficient for collision avoidance within
        a single ops_dir.
        """
        return hashlib.sha256(f"{workload_tag}:{prompt}".encode()).hexdigest()[:16]

    @staticmethod
    def _workload_tag(call_type: str) -> str:
        """Convert call_type into a safe task filename prefix."""
        raw_tag = call_type.strip() or "unknown"
        tag = "".join(
            char if char.isascii() and (char.isalnum() or char in {"_", "-"}) else "_"
            for char in raw_tag
        ).strip("_-")
        return tag or "unknown"

    def _task_root(self, task_dir: Path, directory_name: str) -> Path | None:
        """Resolve a task subdirectory only when it remains under ops_dir/tasks."""
        try:
            tasks_dir = self._ops_dir / "tasks"
            if tasks_dir.is_symlink() or task_dir.is_symlink():
                return None
            ops_root = self._ops_dir.resolve(strict=False)
            resolved_task_dir = task_dir.resolve(strict=False)
        except OSError:
            return None
        if (
            resolved_task_dir.name != directory_name
            or resolved_task_dir.parent.name != "tasks"
            or not resolved_task_dir.is_relative_to(ops_root)
        ):
            return None
        return resolved_task_dir

    def _ensure_task_dir(self, task_dir: Path, directory_name: str) -> None:
        """Create a task subdirectory only when its resolved path is safe."""
        from distill.llm.router import ConfigurationError

        if self._task_root(task_dir, directory_name) is None:
            raise ConfigurationError(
                f"AgentProvider {directory_name} task directory must resolve "
                "inside ops_dir/tasks and must not be a symlink."
            )
        task_dir.mkdir(parents=True, exist_ok=True)
        if self._task_root(task_dir, directory_name) is None:
            raise ConfigurationError(
                f"AgentProvider {directory_name} task directory must resolve "
                "inside ops_dir/tasks and must not be a symlink."
            )

    @staticmethod
    def _direct_pending_result_path(
        result_path: Path,
        pending_root: Path,
        root_identity: tuple[int, int],
    ) -> Path | None:
        """Rebase a direct result child onto the validated canonical task root.

        Only the parent is resolved. Resolving the leaf would erase evidence
        that the declared result is a symlink before the no-follow reader can
        inspect it.
        """

        try:
            if not task_root_is_unchanged(pending_root, root_identity):
                return None
            resolved_parent = result_path.parent.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return None
        if (
            not result_path.name.endswith("_result.md")
            or resolved_parent != pending_root
            or not task_root_is_unchanged(pending_root, root_identity)
        ):
            return None
        return pending_root / result_path.name

    def _pending_result_path(self, result_path: Path) -> Path | None:
        """Validate a result path against the current pending-directory identity."""

        pending_root = self._task_root(self._pending_dir, "pending")
        if pending_root is None:
            return None
        validated_root = validated_task_root(pending_root)
        if validated_root is None:
            return None
        root_path, root_identity = validated_root
        return self._direct_pending_result_path(result_path, root_path, root_identity)

    def _bound_pending_root(self) -> tuple[Path, tuple[int, int]]:
        """Return the canonical pending root and its current directory identity."""

        from distill.llm.router import ConfigurationError

        pending_root = self._task_root(self._pending_dir, "pending")
        validated_root = None if pending_root is None else validated_task_root(pending_root)
        if validated_root is None:
            raise ConfigurationError(
                "AgentProvider pending task directory changed during validation."
            )
        return validated_root

    def _is_pending_result_path(self, result_path: Path) -> bool:
        """Return whether a task result path is a direct pending-root child."""

        return self._pending_result_path(result_path) is not None

    def _read_matching_result(
        self,
        task_path: Path,
        pending_root: Path,
        root_identity: tuple[int, int],
        target_hash: str,
        *,
        max_result_bytes: int,
    ) -> str | None:
        """Read a matching receipt without changing its bound directory identity."""

        try:
            task_text = read_task_text(
                task_path,
                pending_root,
                max_bytes=MAX_AGENT_TASK_BYTES,
                root_identity=root_identity,
            )
            if task_text is None:
                return None
            parsed_task: object = json.loads(task_text)
            if not isinstance(parsed_task, dict):
                return None
            task_data = cast(dict[str, object], parsed_task)
            if task_data.get("prompt_hash") != target_hash:
                return None
            declared_result_path = task_data.get("result_path")
            if not isinstance(declared_result_path, str):
                return None
            result_path = self._direct_pending_result_path(
                Path(declared_result_path),
                pending_root,
                root_identity,
            )
            if result_path is None:
                return None
            result_text = read_task_text(
                result_path,
                pending_root,
                max_bytes=max_result_bytes,
                root_identity=root_identity,
            )
            if result_text is None or not task_root_is_unchanged(pending_root, root_identity):
                return None
        except (
            json.JSONDecodeError,
            KeyError,
            OSError,
            RecursionError,
            RuntimeError,
            ValueError,
        ):
            return None
        return result_text.replace("\r\n", "\n").replace("\r", "\n")

    def _read_host_submission(
        self,
        task_path: Path,
        result_text: str,
        prompt_hash: str,
        *,
        bound_root: tuple[Path, tuple[int, int]] | None = None,
    ) -> HostSubmission | None:
        """Read and validate optional host-session metadata for a result."""

        return read_host_submission(
            task_path,
            result_text,
            prompt_hash,
            pending_dir=self._pending_dir,
            task_root=self._task_root,
            bound_root=bound_root,
        )

    def _find_existing_task(
        self,
        prompt: str,
        workload_tag: str,
        *,
        bound_root: tuple[Path, tuple[int, int]],
    ) -> Path | None:
        """Find one existing task for an exact prompt, whether completed or pending."""

        return find_existing_task(
            prompt,
            workload_tag,
            target_hash=self._prompt_hash(prompt, workload_tag),
            bound_root=bound_root,
            direct_result_path=self._direct_pending_result_path,
        )

    def _find_existing_result(
        self,
        prompt: str,
        workload_tag: str,
        *,
        max_result_bytes: int,
        bound_root: tuple[Path, tuple[int, int]] | None = None,
    ) -> tuple[Path, str] | None:
        """Find an existing pending task+result for this exact prompt.

        Uses the prompt_hash stored in each Task_File to match without
        re-reading every prompt body.  Returns ``{"task_path": Path,
        "result_path": Path}`` if a completed result exists, else ``None``.
        """
        target_hash = self._prompt_hash(prompt, workload_tag)
        if bound_root is None:
            pending_root = self._task_root(self._pending_dir, "pending")
            validated_root = None if pending_root is None else validated_task_root(pending_root)
            if validated_root is None:
                return None
            pending_root, root_identity = validated_root
        else:
            pending_root, root_identity = bound_root
            if not task_root_is_unchanged(pending_root, root_identity):
                return None
        # Iterate through the validated canonical root. Temporary directories on
        # macOS commonly have ``/var`` and ``/private/var`` aliases, and Windows
        # runners may expose an 8.3 path that resolves to a long path. Mixing the
        # lexical root with its canonical identity would make safe files appear
        # to have escaped the directory and strand replayable receipts.
        prefix = f"{workload_tag}_"
        for task_path in pending_task_paths(pending_root, root_identity):
            if not task_path.name.startswith(prefix):
                continue
            result_text = self._read_matching_result(
                task_path,
                pending_root,
                root_identity,
                target_hash,
                max_result_bytes=max_result_bytes,
            )
            if result_text is not None:
                return task_path, result_text
        return None

    @serialized_agent_call
    async def call(
        self,
        model: str,
        prompt: str,
        *,
        max_tokens: int = 8192,
        timeout: int = 300,
        retries: int = 2,
        temperature: float | None = None,
        call_type: str = "",
        reasoning_effort: str | None = None,
        usage_sink: UsageAttemptSink | None = None,
    ) -> LLM_Response:
        """Check for existing result or write a new task file.

        If a result file exists for this prompt (idempotent re-call), reads the
        result and returns an ``LLM_Response``. The task and result remain as a
        replayable receipt for later identical calls. Otherwise writes a
        Task_File and raises ``PendingTaskError``.
        """
        if isinstance(max_tokens, bool) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout must be a positive integer")
        task_id = uuid.uuid4().hex[:12]
        workload_tag = self._workload_tag(call_type)
        task_filename = f"{workload_tag}_{task_id}.json"
        result_filename = f"{workload_tag}_{task_id}_result.md"

        self._ensure_task_dir(self._pending_dir, "pending")
        pending_root, pending_identity = self._bound_pending_root()
        task_path = pending_root / task_filename
        result_path = pending_root / result_filename

        # Check if a result already exists for this prompt (idempotent re-call)
        max_result_bytes = agent_result_byte_limit(max_tokens)
        existing = self._find_existing_result(
            prompt,
            workload_tag,
            max_result_bytes=max_result_bytes,
            bound_root=(pending_root, pending_identity),
        )
        if existing:
            task_src, result_text = existing
            submission = self._read_host_submission(
                task_src,
                result_text,
                self._prompt_hash(prompt, workload_tag),
                bound_root=(pending_root, pending_identity),
            )
            if submission is None:
                pending = PendingTaskError(
                    f"Task result requires a valid worker submission receipt: {task_src}",
                    task_path=str(task_src),
                )
                raise pending
            attempts: list[LLMUsageAttempt] = []
            attempt = emit_usage_attempt(
                attempts,
                deferred_usage_attempt(
                    prompt=prompt,
                    prompt_hash=self._prompt_hash(prompt, workload_tag),
                    task_filename=task_src.name,
                    max_tokens=max_tokens,
                    submission=submission,
                ),
                usage_sink,
            )
            response_model = submission.model_label
            response_provider = submission.host
            response_provider_type = "host-managed"
            return LLM_Response(
                text=result_text,
                input_tokens=attempt.input_tokens,
                output_tokens=attempt.output_tokens,
                model=response_model,
                provider_name=response_provider,
                provider_type=response_provider_type,
                usage_source=attempt.usage_source,
                usage_attempts=tuple(attempts),
            )

        matching_task = self._find_existing_task(
            prompt,
            workload_tag,
            bound_root=(pending_root, pending_identity),
        )
        if matching_task is not None:
            pending = PendingTaskError(
                f"Task already awaiting agent processing: {matching_task}",
                task_path=str(matching_task),
            )
            raise pending
        if len(pending_task_paths(pending_root, pending_identity)) >= MAX_AGENT_PENDING_TASKS:
            raise ConfigurationError(
                f"AgentProvider pending task limit is {MAX_AGENT_PENDING_TASKS}."
            )

        # Write the task file with prompt_hash for idempotent lookup
        task_data: dict[str, object] = {
            "schema_version": AGENT_TASK_SCHEMA_VERSION,
            "_instruction": (
                "This is a distillr task file. Process the prompt below and write "
                "the result to the result_path file. The result should be plain "
                "markdown text matching the expected_output_format."
            ),
            "task_id": task_id,
            "created_at": datetime.now(UTC).isoformat(),
            "prompt_hash": self._prompt_hash(prompt, workload_tag),
            "workload_tag": workload_tag,
            "prompt": prompt,
            "expected_output_format": "markdown",
            "result_path": str(result_path),
            "max_result_bytes": max_result_bytes,
            "max_tokens": max_tokens,
            "timeout_seconds": timeout,
            "worker_protocol": "agent-worker.v1",
            "billing_class": "host-managed",
        }
        task_bytes = json.dumps(task_data, indent=2, ensure_ascii=False).encode("utf-8")
        if len(task_bytes) > MAX_AGENT_TASK_BYTES:
            raise ValueError(
                f"serialized agent task exceeds the {MAX_AGENT_TASK_BYTES:,}-byte limit"
            )
        attempts = []
        emit_usage_attempt(
            attempts,
            deferred_usage_attempt(
                prompt=prompt,
                prompt_hash=self._prompt_hash(prompt, workload_tag),
                task_filename=task_filename,
                max_tokens=max_tokens,
            ),
            usage_sink,
        )
        try:
            write_task_bytes(task_path, pending_root, pending_identity, task_bytes)
        except Exception as exc:
            attach_usage_attempts(exc, attempts)
            raise

        pending = PendingTaskError(
            f"Task awaiting agent processing: {task_path}",
            task_path=str(task_path),
        )
        attach_usage_attempts(pending, attempts)
        raise pending
