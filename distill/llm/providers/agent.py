# pyright: strict
"""Agent provider — zero-cost deferred execution via structured task files.

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

from distill.llm.router import LLM_Response, PendingTaskError


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
                    if result_path.exists():
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
    ) -> LLM_Response:
        """Check for existing result or write a new task file.

        If a result file exists for this prompt (idempotent re-call), reads
        the result, moves the task to ``completed/``, and returns an
        ``LLM_Response``.  Otherwise writes a Task_File and raises
        ``PendingTaskError``.
        """
        task_id = uuid.uuid4().hex[:12]
        workload_tag = call_type or "unknown"
        task_filename = f"{workload_tag}_{task_id}.json"
        result_filename = f"{workload_tag}_{task_id}_result.md"

        task_path = self._pending_dir / task_filename
        result_path = self._pending_dir / result_filename

        # Check if a result already exists for this prompt (idempotent re-call)
        existing = self._find_existing_result(prompt, workload_tag)
        if existing:
            result_text = existing["result_path"].read_text(encoding="utf-8")
            task_src = existing["task_path"]
            if task_src.exists():
                self._completed_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(task_src), str(self._completed_dir / task_src.name))
            return LLM_Response(
                text=result_text,
                input_tokens=0,
                output_tokens=0,
                model="agent",
            )

        # Write the task file with prompt_hash for idempotent lookup
        self._pending_dir.mkdir(parents=True, exist_ok=True)
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
