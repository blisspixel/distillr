# pyright: strict
"""Billing-unknown deferred agent execution via structured task files.

Instead of making API calls, the Agent provider writes Task_Files that an
external agentic assistant (Claude Code, Kiro, etc.) can pick up and process.
Uses SHA-256 content hashing for idempotent task lookup across retries.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from pathlib import Path

from distill.llm.providers._usage import conservative_usage
from distill.llm.router import PendingTaskError
from distill.llm.types import LLM_Response
from distill.llm.usage import (
    LLMUsageAttempt,
    UsageAttemptSink,
    attach_usage_attempts,
    emit_usage_attempt,
)

_MAX_AGENT_TASK_BYTES = 1 * 1024 * 1024
_MAX_AGENT_RESULT_BYTES = 16 * 1024 * 1024
_RESULT_BYTES_PER_TOKEN = 16


def _task_file_revision(file_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_nlink,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )


def _unsafe_task_file(path: Path, file_stat: os.stat_result) -> bool:
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(file_stat, "st_file_attributes", 0))
    return (
        stat.S_ISLNK(file_stat.st_mode)
        or not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_nlink != 1
        or bool(reparse_flag and attributes & reparse_flag)
        or (hasattr(path, "is_junction") and path.is_junction())
    )


def _unsafe_task_directory(path: Path, directory_stat: os.stat_result) -> bool:
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    attributes = int(getattr(directory_stat, "st_file_attributes", 0))
    return (
        stat.S_ISLNK(directory_stat.st_mode)
        or not stat.S_ISDIR(directory_stat.st_mode)
        or bool(reparse_flag and attributes & reparse_flag)
        or (hasattr(path, "is_junction") and path.is_junction())
    )


def _directory_identity(directory_stat: os.stat_result) -> tuple[int, int]:
    return directory_stat.st_dev, directory_stat.st_ino


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.absolute())) == os.path.normcase(str(right.absolute()))


def _validated_task_root(root: Path) -> tuple[Path, tuple[int, int]] | None:
    """Resolve a stable, non-link task root and return its directory identity."""

    try:
        root_absolute = root.absolute()
        initial_stat = root_absolute.lstat()
        if _unsafe_task_directory(root_absolute, initial_stat):
            return None
        identity = _directory_identity(initial_stat)
        root_resolved = root_absolute.resolve(strict=True)
        current_stat = root_absolute.lstat()
    except (OSError, RuntimeError, ValueError):
        return None
    if (
        not _same_path(root_resolved, root_absolute)
        or _unsafe_task_directory(root_absolute, current_stat)
        or _directory_identity(current_stat) != identity
    ):
        return None
    return root_absolute, identity


def _task_root_is_unchanged(root: Path, identity: tuple[int, int]) -> bool:
    current = _validated_task_root(root)
    return current is not None and current[1] == identity


def _close_task_descriptors(*descriptors: int) -> None:
    for descriptor in descriptors:
        if descriptor >= 0:
            os.close(descriptor)


def _open_task_file(
    path: Path,
    root: Path,
    root_identity: tuple[int, int],
    *,
    max_bytes: int,
) -> tuple[int, int, tuple[int, int, int, int, int]] | None:
    descriptor = -1
    directory_descriptor = -1
    accepted = False
    try:
        if not _same_path(path.parent, root) or not _task_root_is_unchanged(root, root_identity):
            return None
        initial_stat = path.lstat()
        if _unsafe_task_file(path, initial_stat) or initial_stat.st_size > max_bytes:
            return None
        revision = _task_file_revision(initial_stat)
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        supports_openat = os.open in os.supports_dir_fd
        if supports_openat:
            directory_descriptor = os.open(root, directory_flags)
            if _directory_identity(os.fstat(directory_descriptor)) != root_identity:
                return None
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if supports_openat:
            descriptor = os.open(path.name, flags, dir_fd=directory_descriptor)
        else:
            descriptor = os.open(path, flags)
        descriptor_stat = os.fstat(descriptor)
        current_stat = path.lstat()
        if (
            not _task_root_is_unchanged(root, root_identity)
            or _unsafe_task_file(path, descriptor_stat)
            or _task_file_revision(descriptor_stat) != revision
            or _task_file_revision(current_stat) != revision
        ):
            return None
        accepted = True
        return descriptor, directory_descriptor, revision
    except (OSError, RuntimeError, ValueError):
        return None
    finally:
        if not accepted:
            _close_task_descriptors(descriptor, directory_descriptor)


def _read_task_text(path: Path, root: Path, *, max_bytes: int) -> str | None:
    """Read one direct task child while detecting links, swaps, and size overruns."""

    if max_bytes < 0:
        return None
    validated_root = _validated_task_root(root)
    if validated_root is None:
        return None
    root_path, root_identity = validated_root
    opened = _open_task_file(path, root_path, root_identity, max_bytes=max_bytes)
    if opened is None:
        return None
    descriptor, directory_descriptor, revision = opened
    try:
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            content = stream.read(max_bytes + 1)
            descriptor_after = os.fstat(stream.fileno())
        final_stat = path.lstat()
        if (
            len(content) > max_bytes
            or not _task_root_is_unchanged(root_path, root_identity)
            or _task_file_revision(descriptor_after) != revision
            or _task_file_revision(final_stat) != revision
        ):
            return None
        return content.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    finally:
        _close_task_descriptors(descriptor, directory_descriptor)


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
        self._completed_dir = self._ops_dir / "tasks" / "completed"

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

    def _usage_attempt(
        self,
        *,
        prompt: str,
        workload_tag: str,
        task_filename: str,
        max_tokens: int,
    ) -> LLMUsageAttempt:
        """Build stable conservative evidence for one deferred external task."""

        prompt_hash = self._prompt_hash(prompt, workload_tag)
        attempt_id = hashlib.sha256(f"agent:{prompt_hash}:{task_filename}".encode()).hexdigest()
        input_tokens, output_tokens = conservative_usage(
            prompt=prompt,
            max_tokens=max_tokens,
        )
        return LLMUsageAttempt(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model="agent",
            provider_name="agent",
            provider_type="cloud",
            usage_source="conservative",
            outcome="success",
            attempt_id=attempt_id,
        )

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

    def _is_pending_result_path(self, result_path: Path) -> bool:
        """Return whether a task result path is inside the pending task root."""
        try:
            pending_root = self._task_root(self._pending_dir, "pending")
            if pending_root is None:
                return False
            resolved_result = result_path.resolve(strict=False)
        except OSError:
            return False
        return result_path.name.endswith("_result.md") and resolved_result.is_relative_to(
            pending_root
        )

    def _find_existing_result(
        self,
        prompt: str,
        workload_tag: str,
        *,
        max_result_bytes: int,
    ) -> tuple[Path, str] | None:
        """Find an existing pending task+result for this exact prompt.

        Uses the prompt_hash stored in each Task_File to match without
        re-reading every prompt body.  Returns ``{"task_path": Path,
        "result_path": Path}`` if a completed result exists, else ``None``.
        """
        target_hash = self._prompt_hash(prompt, workload_tag)
        pending_root = self._task_root(self._pending_dir, "pending")
        if pending_root is None or not self._pending_dir.exists():
            return None
        for task_path in self._pending_dir.glob(f"{workload_tag}_*.json"):
            try:
                task_text = _read_task_text(
                    task_path,
                    pending_root,
                    max_bytes=_MAX_AGENT_TASK_BYTES,
                )
                if task_text is None:
                    continue
                task_data: dict[str, object] = json.loads(task_text)
                if task_data.get("prompt_hash") == target_hash:
                    result_path = Path(str(task_data["result_path"]))
                    if self._is_pending_result_path(result_path) and result_path.exists():
                        result_text = _read_task_text(
                            result_path,
                            pending_root,
                            max_bytes=max_result_bytes,
                        )
                        if result_text is not None:
                            return task_path, result_text.replace("\r\n", "\n").replace("\r", "\n")
            except (json.JSONDecodeError, KeyError, OSError):
                continue
        return None

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

        If a result file exists for this prompt (idempotent re-call), reads
        the result, moves the task to ``completed/``, and returns an
        ``LLM_Response``.  Otherwise writes a Task_File and raises
        ``PendingTaskError``.
        """
        if isinstance(max_tokens, bool) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if isinstance(timeout, bool) or timeout <= 0:
            raise ValueError("timeout must be a positive integer")
        task_id = uuid.uuid4().hex[:12]
        workload_tag = self._workload_tag(call_type)
        task_filename = f"{workload_tag}_{task_id}.json"
        result_filename = f"{workload_tag}_{task_id}_result.md"

        task_path = self._pending_dir / task_filename
        result_path = self._pending_dir / result_filename

        self._ensure_task_dir(self._pending_dir, "pending")

        # Check if a result already exists for this prompt (idempotent re-call)
        max_result_bytes = min(
            _MAX_AGENT_RESULT_BYTES,
            max(4_096, max_tokens * _RESULT_BYTES_PER_TOKEN),
        )
        existing = self._find_existing_result(
            prompt,
            workload_tag,
            max_result_bytes=max_result_bytes,
        )
        if existing:
            task_src, result_text = existing
            attempts: list[LLMUsageAttempt] = []
            attempt = emit_usage_attempt(
                attempts,
                self._usage_attempt(
                    prompt=prompt,
                    workload_tag=workload_tag,
                    task_filename=task_src.name,
                    max_tokens=max_tokens,
                ),
                usage_sink,
            )
            if task_src.exists():
                self._ensure_task_dir(self._completed_dir, "completed")
                shutil.move(str(task_src), str(self._completed_dir / task_src.name))
            return LLM_Response(
                text=result_text,
                input_tokens=attempt.input_tokens,
                output_tokens=attempt.output_tokens,
                model="agent",
                usage_source="conservative",
                usage_attempts=tuple(attempts),
            )

        # Write the task file with prompt_hash for idempotent lookup
        task_data: dict[str, object] = {
            "_instruction": (
                "This is a distillr task file. Process the prompt below and write "
                "the result to the result_path file. The result should be plain "
                "markdown text matching the expected_output_format."
            ),
            "task_id": task_id,
            "prompt_hash": self._prompt_hash(prompt, workload_tag),
            "workload_tag": workload_tag,
            "prompt": prompt,
            "expected_output_format": "markdown",
            "result_path": str(result_path),
            "max_tokens": max_tokens,
            "timeout_seconds": timeout,
        }
        task_bytes = json.dumps(task_data, indent=2, ensure_ascii=False).encode("utf-8")
        if len(task_bytes) > _MAX_AGENT_TASK_BYTES:
            raise ValueError(
                f"serialized agent task exceeds the {_MAX_AGENT_TASK_BYTES:,}-byte limit"
            )
        attempts = []
        emit_usage_attempt(
            attempts,
            self._usage_attempt(
                prompt=prompt,
                workload_tag=workload_tag,
                task_filename=task_filename,
                max_tokens=max_tokens,
            ),
            usage_sink,
        )
        try:
            task_path.write_bytes(task_bytes)
        except Exception as exc:
            attach_usage_attempts(exc, attempts)
            raise

        pending = PendingTaskError(
            f"Task awaiting agent processing: {task_path}",
            task_path=str(task_path),
        )
        attach_usage_attempts(pending, attempts)
        raise pending
