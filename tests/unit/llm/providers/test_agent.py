# pyright: strict
"""Property and unit tests for AgentProvider.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
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


# ---------------------------------------------------------------------------
# Property 9: Task_File structure completeness
# ---------------------------------------------------------------------------


@settings(max_examples=100)
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
        task_files = list(pending_dir.glob(f"{workload_tag}_*.json"))
        assert len(task_files) == 1, f"Expected 1 task file, found {len(task_files)}"

        task_data: dict[str, object] = json.loads(task_files[0].read_text(encoding="utf-8"))

        # All required fields present
        assert task_data.get("task_id")
        assert task_data["workload_tag"] == workload_tag
        assert task_data["prompt"] == prompt
        assert task_data.get("expected_output_format")
        assert task_data.get("result_path")
        assert task_data.get("_instruction")
        assert task_data.get("prompt_hash")

        # prompt_hash matches expected value
        expected_hash = AgentProvider._prompt_hash(prompt, workload_tag)
        assert task_data["prompt_hash"] == expected_hash


# ---------------------------------------------------------------------------
# Property 10: Agent_Provider result round-trip
# ---------------------------------------------------------------------------


@settings(max_examples=100)
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
        task_files = list(pending_dir.glob(f"{workload_tag}_*.json"))
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
