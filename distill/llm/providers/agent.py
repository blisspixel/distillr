# pyright: strict
"""Billing-unknown deferred agent execution via structured task files.

Instead of making API calls, the Agent provider writes Task_Files that an
external agentic assistant (Claude Code, Kiro, etc.) can pick up and process.
Uses SHA-256 content hashing for idempotent task lookup across retries.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from distill.llm.router import PendingTaskError
from distill.llm.types import LLM_Response
from distill.llm.usage import UsageAttemptSink


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

    def _find_existing_result(self, prompt: str, workload_tag: str) -> dict[str, Path] | None:
        """Find an existing pending task+result for this exact prompt.

        Uses the prompt_hash stored in each Task_File to match without
        re-reading every prompt body.  Returns ``{"task_path": Path,
        "result_path": Path}`` if a completed result exists, else ``None``.
        """
        target_hash = self._prompt_hash(prompt, workload_tag)
        if not self._pending_dir.exists():
            return None
        for task_path in self._pending_dir.glob(f"{workload_tag}_*.json"):
            try:
                task_data: dict[str, object] = json.loads(task_path.read_text(encoding="utf-8"))
                if task_data.get("prompt_hash") == target_hash:
                    result_path = Path(str(task_data["result_path"]))
                    if self._is_pending_result_path(result_path) and result_path.exists():
                        return {"task_path": task_path, "result_path": result_path}
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
        task_id = uuid.uuid4().hex[:12]
        workload_tag = self._workload_tag(call_type)
        task_filename = f"{workload_tag}_{task_id}.json"
        result_filename = f"{workload_tag}_{task_id}_result.md"

        task_path = self._pending_dir / task_filename
        result_path = self._pending_dir / result_filename

        self._ensure_task_dir(self._pending_dir, "pending")

        # Check if a result already exists for this prompt (idempotent re-call)
        existing = self._find_existing_result(prompt, workload_tag)
        if existing:
            result_text = existing["result_path"].read_text(encoding="utf-8")
            task_src = existing["task_path"]
            if task_src.exists():
                self._ensure_task_dir(self._completed_dir, "completed")
                shutil.move(str(task_src), str(self._completed_dir / task_src.name))
            return LLM_Response(
                text=result_text,
                input_tokens=0,
                output_tokens=0,
                model="agent",
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
        }
        task_path.write_text(
            json.dumps(task_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        raise PendingTaskError(
            f"Task awaiting agent processing: {task_path}",
            task_path=str(task_path),
        )
