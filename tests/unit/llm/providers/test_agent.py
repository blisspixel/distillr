# pyright: strict
"""Property and unit tests for AgentProvider.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.providers.agent import AgentProvider
from distill.llm.router import ConfigurationError, LLM_Response, PendingTaskError

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty printable strings for prompts and workload tags
_prompt_str = st.text(min_size=1, max_size=200)
_workload_tag = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters=""),
    min_size=1,
    max_size=20,
)
_result_text = st.text(
    alphabet=st.characters(blacklist_characters="\r", blacklist_categories=("Cs",)),
    min_size=1,
    max_size=500,
)


def _expected_prompt_hash(prompt: str, workload_tag: str) -> str:
    return hashlib.sha256(f"{workload_tag}:{prompt}".encode()).hexdigest()[:16]


class InspectableAgentProvider(AgentProvider):
    """Expose lookup helpers for branch-focused safety tests."""

    def find_existing_result_for_test(
        self, prompt: str, workload_tag: str
    ) -> dict[str, Path] | None:
        return self._find_existing_result(prompt, workload_tag)

    def task_root_for_test(self, task_dir: Path, directory_name: str) -> Path | None:
        return self._task_root(task_dir, directory_name)


# ---------------------------------------------------------------------------
# Property 9: Task_File structure completeness
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(prompt=_prompt_str, workload_tag=_workload_tag)
def test_task_file_structure(prompt: str, workload_tag: str) -> None:
    """Feature: llm-router-model-upgrade, Property 9: Task_File structure completeness

    For any prompt string and workload tag, when the AgentProvider writes a
    Task_File, the resulting JSON contains all required fields with correct values.

    **Validates: Requirements 11.2, 11.7**
    """
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = Path(tmp) / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(PendingTaskError):
            asyncio.run(provider.call("agent", prompt, call_type=workload_tag))

        # Find the written task file
        pending_dir = ops_dir / "tasks" / "pending"
        task_files = list(pending_dir.glob("*.json"))
        assert len(task_files) == 1, f"Expected 1 task file, found {len(task_files)}"

        task_data: dict[str, object] = json.loads(task_files[0].read_text(encoding="utf-8"))
        stored_workload_tag = str(task_data["workload_tag"])

        # All required fields present
        assert task_data.get("task_id")
        assert stored_workload_tag
        assert all(separator not in stored_workload_tag for separator in ("/", "\\", ":"))
        assert ".." not in stored_workload_tag
        assert task_data["prompt"] == prompt
        assert task_data.get("expected_output_format")
        assert task_data.get("result_path")
        assert task_data.get("_instruction")
        assert task_data.get("prompt_hash")

        # prompt_hash matches expected value
        expected_hash = _expected_prompt_hash(prompt, stored_workload_tag)
        assert task_data["prompt_hash"] == expected_hash


# ---------------------------------------------------------------------------
# Property 10: Agent_Provider result round-trip
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(prompt=_prompt_str, workload_tag=_workload_tag, result_text=_result_text)
def test_result_round_trip(prompt: str, workload_tag: str, result_text: str) -> None:
    """Feature: llm-router-model-upgrade, Property 10: Agent_Provider result round-trip

    For any non-empty result text, if a result file is written to the path
    specified in a pending Task_File, calling the AgentProvider returns an
    LLM_Response with text equal to the written result, zero tokens, and
    model="agent".

    **Validates: Requirements 11.4**
    """
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = Path(tmp) / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        # First call: write the task file
        with pytest.raises(PendingTaskError):
            asyncio.run(provider.call("agent", prompt, call_type=workload_tag))

        # Find the task file and write the result
        pending_dir = ops_dir / "tasks" / "pending"
        task_files = list(pending_dir.glob("*.json"))
        assert len(task_files) == 1

        task_data: dict[str, object] = json.loads(task_files[0].read_text(encoding="utf-8"))
        result_path = Path(str(task_data["result_path"]))
        result_path.write_text(result_text, encoding="utf-8")

        # Second call: should find the result and return it
        response = asyncio.run(provider.call("agent", prompt, call_type=workload_tag))

        assert isinstance(response, LLM_Response)
        assert response.text == result_text
        assert response.input_tokens == 0
        assert response.output_tokens == 0
        assert response.model == "agent"


# ---------------------------------------------------------------------------
# Unit tests — AgentProvider lifecycle
# ---------------------------------------------------------------------------


class TestAgentProviderLifecycle:
    """Test AgentProvider task file writing, reading, and lifecycle."""

    def test_empty_ops_dir_is_rejected(self) -> None:
        """Agent tasks must never default to ./tasks under the cwd."""
        with pytest.raises(ConfigurationError, match="non-empty ops_dir"):
            AgentProvider(ops_dir="")

    def test_router_reasoning_effort_argument_is_accepted(self, tmp_path: Path) -> None:
        """Router may pass reasoning_effort; agent provider ignores it safely."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(PendingTaskError):
            asyncio.run(
                provider.call(
                    "agent",
                    "test prompt",
                    call_type="analysis",
                    reasoning_effort="medium",
                )
            )

        assert (ops_dir / "tasks" / "pending").exists()

    def test_task_file_written_to_correct_directory(self, tmp_path: Path) -> None:
        """Task file is written to <ops_dir>/tasks/pending/."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(PendingTaskError):
            asyncio.run(provider.call("agent", "test prompt", call_type="analysis"))

        pending_dir = ops_dir / "tasks" / "pending"
        assert pending_dir.exists()
        task_files = list(pending_dir.glob("analysis_*.json"))
        assert len(task_files) == 1

    def test_pending_task_error_raised_with_task_path(self, tmp_path: Path) -> None:
        """PendingTaskError is raised with the correct task path."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(PendingTaskError) as exc_info:
            asyncio.run(provider.call("agent", "test prompt", call_type="analysis"))

        assert exc_info.value.task_path
        assert "analysis_" in exc_info.value.task_path
        assert exc_info.value.task_path.endswith(".json")

    def test_existing_result_lookup_returns_none_without_pending_dir(self, tmp_path: Path) -> None:
        """Existing-result lookup does not create or require pending/."""
        provider = InspectableAgentProvider(ops_dir=str(tmp_path / "ops"))

        assert provider.find_existing_result_for_test("test prompt", "analysis") is None

    def test_task_root_rejects_unexpected_directory_name(self, tmp_path: Path) -> None:
        """Only canonical task subdirectory names are valid roots."""
        ops_dir = tmp_path / "ops"
        provider = InspectableAgentProvider(ops_dir=str(ops_dir))

        assert provider.task_root_for_test(ops_dir / "tasks" / "unexpected", "pending") is None

    def test_default_workload_tag_is_unknown(self, tmp_path: Path) -> None:
        """Missing call_type writes an unknown-tagged task instead of an empty name."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(PendingTaskError) as exc_info:
            asyncio.run(provider.call("agent", "test prompt"))

        task_path = Path(exc_info.value.task_path)
        task_data: dict[str, object] = json.loads(task_path.read_text(encoding="utf-8"))
        result_path = Path(str(task_data["result_path"]))

        assert task_path.name.startswith("unknown_")
        assert task_data["workload_tag"] == "unknown"
        assert task_data["prompt_hash"] == _expected_prompt_hash("test prompt", "unknown")
        assert result_path.name.startswith("unknown_")
        assert result_path.name.endswith("_result.md")
        assert list((ops_dir / "tasks" / "pending").glob("unknown_*.json"))

    @pytest.mark.parametrize(
        "call_type",
        ["../escape", "..\\escape", "/tmp/escape", "C:\\temp\\escape", "analysis/sub"],
    )
    def test_call_type_is_sanitized_before_file_use(self, tmp_path: Path, call_type: str) -> None:
        """call_type cannot escape pending/ through task or result filenames."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(PendingTaskError) as exc_info:
            asyncio.run(provider.call("agent", "test prompt", call_type=call_type))

        pending_dir = ops_dir / "tasks" / "pending"
        pending_root = pending_dir.resolve(strict=False)
        task_path = Path(exc_info.value.task_path).resolve(strict=False)
        task_data: dict[str, object] = json.loads(task_path.read_text(encoding="utf-8"))
        workload_tag = str(task_data["workload_tag"])
        result_path = Path(str(task_data["result_path"])).resolve(strict=False)

        assert task_path.is_relative_to(pending_root)
        assert result_path.is_relative_to(pending_root)
        assert all(separator not in workload_tag for separator in ("/", "\\", ":"))
        assert ".." not in workload_tag
        assert list(pending_dir.glob("*.json")) == [Path(exc_info.value.task_path)]

    def test_corrupt_pending_task_files_are_ignored(self, tmp_path: Path) -> None:
        """Malformed or incomplete pending tasks do not block a fresh task write."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))
        pending_dir = ops_dir / "tasks" / "pending"
        pending_dir.mkdir(parents=True)
        prompt = "same prompt"
        workload_tag = "analysis"
        prompt_hash = _expected_prompt_hash(prompt, workload_tag)

        (pending_dir / "analysis_bad_json.json").write_text("{not json", encoding="utf-8")
        (pending_dir / "analysis_missing_result_path.json").write_text(
            json.dumps({"prompt_hash": prompt_hash}),
            encoding="utf-8",
        )
        (pending_dir / "analysis_no_result_file.json").write_text(
            json.dumps(
                {
                    "prompt_hash": prompt_hash,
                    "result_path": str(pending_dir / "missing_result.md"),
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(PendingTaskError):
            asyncio.run(provider.call("agent", prompt, call_type=workload_tag))

        task_files = list(pending_dir.glob("analysis_*.json"))
        assert len(task_files) == 4

    def test_matching_task_result_paths_must_stay_in_pending_dir(self, tmp_path: Path) -> None:
        """Matching pending tasks cannot replay results from outside pending/."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))
        pending_dir = ops_dir / "tasks" / "pending"
        pending_dir.mkdir(parents=True)
        prompt = "same prompt"
        workload_tag = "analysis"
        prompt_hash = _expected_prompt_hash(prompt, workload_tag)

        outside_absolute_result = tmp_path / "outside_absolute_result.md"
        outside_absolute_result.write_text("external absolute result", encoding="utf-8")
        dotdot_result = tmp_path / "outside_dotdot_result.md"
        dotdot_result.write_text("external parent result", encoding="utf-8")
        dotdot_escape_path = pending_dir / ".." / ".." / ".." / dotdot_result.name

        attack_result_paths = [outside_absolute_result, dotdot_escape_path]
        symlink_result_path = pending_dir / "analysis_symlink_result.md"
        try:
            symlink_result_path.symlink_to(outside_absolute_result)
        except (NotImplementedError, OSError):
            symlink_result_path = None
        if symlink_result_path is not None:
            attack_result_paths.append(symlink_result_path)

        for index, result_path in enumerate(attack_result_paths):
            (pending_dir / f"analysis_attack_{index}.json").write_text(
                json.dumps(
                    {
                        "prompt_hash": prompt_hash,
                        "result_path": str(result_path),
                    }
                ),
                encoding="utf-8",
            )

        with pytest.raises(PendingTaskError) as exc_info:
            asyncio.run(provider.call("agent", prompt, call_type=workload_tag))

        new_task_path = Path(exc_info.value.task_path)
        new_task_data: dict[str, object] = json.loads(new_task_path.read_text(encoding="utf-8"))
        new_result_path = Path(str(new_task_data["result_path"])).resolve(strict=False)
        assert new_result_path.is_relative_to(pending_dir.resolve(strict=False))
        assert new_result_path.name.endswith("_result.md")
        assert not (ops_dir / "tasks" / "completed").exists()

    def test_pending_task_directory_symlink_is_rejected(self, tmp_path: Path) -> None:
        """pending/ must not be a symlink to another directory."""
        ops_dir = tmp_path / "ops"
        pending_dir = ops_dir / "tasks" / "pending"
        external_pending = tmp_path / "external_pending"
        pending_dir.parent.mkdir(parents=True)
        external_pending.mkdir()
        try:
            pending_dir.symlink_to(external_pending, target_is_directory=True)
        except (NotImplementedError, OSError):
            pytest.skip("directory symlinks are not available on this platform")

        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(ConfigurationError, match="pending task directory"):
            asyncio.run(provider.call("agent", "test prompt", call_type="analysis"))

        assert not list(external_pending.iterdir())

    def test_completed_task_directory_symlink_is_rejected(self, tmp_path: Path) -> None:
        """completed/ must not be a symlink during task archival."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(PendingTaskError):
            asyncio.run(provider.call("agent", "test prompt", call_type="synthesis"))

        pending_dir = ops_dir / "tasks" / "pending"
        task_files = list(pending_dir.glob("synthesis_*.json"))
        assert len(task_files) == 1
        task_data: dict[str, object] = json.loads(task_files[0].read_text(encoding="utf-8"))
        Path(str(task_data["result_path"])).write_text("completed result", encoding="utf-8")

        completed_dir = ops_dir / "tasks" / "completed"
        external_completed = tmp_path / "external_completed"
        external_completed.mkdir()
        try:
            completed_dir.symlink_to(external_completed, target_is_directory=True)
        except (NotImplementedError, OSError):
            pytest.skip("directory symlinks are not available on this platform")

        with pytest.raises(ConfigurationError, match="completed task directory"):
            asyncio.run(provider.call("agent", "test prompt", call_type="synthesis"))

        assert task_files[0].exists()
        assert not list(external_completed.iterdir())

    def test_completed_task_moved_to_completed_dir(self, tmp_path: Path) -> None:
        """After reading a result, the task file is moved to completed/."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        # Write the task file
        with pytest.raises(PendingTaskError):
            asyncio.run(provider.call("agent", "test prompt", call_type="synthesis"))

        # Find task file and write result
        pending_dir = ops_dir / "tasks" / "pending"
        task_files = list(pending_dir.glob("synthesis_*.json"))
        assert len(task_files) == 1

        task_data: dict[str, object] = json.loads(task_files[0].read_text(encoding="utf-8"))
        result_path = Path(str(task_data["result_path"]))
        result_path.write_text("completed result", encoding="utf-8")

        task_name = task_files[0].name

        # Second call: reads result and moves task
        response = asyncio.run(provider.call("agent", "test prompt", call_type="synthesis"))

        assert response.text == "completed result"

        # Task file should be in completed/, not pending/
        completed_dir = ops_dir / "tasks" / "completed"
        assert (completed_dir / task_name).exists()
        # Original task file should be gone from pending
        assert not task_files[0].exists()
