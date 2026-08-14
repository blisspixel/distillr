# pyright: strict
"""Property and unit tests for AgentProvider.

Feature: llm-router-model-upgrade
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from distill.llm.providers import _agent_files as agent_files_mod
from distill.llm.providers import agent as agent_mod
from distill.llm.providers.agent import AgentProvider
from distill.llm.router import ConfigurationError, LLM_Response, PendingTaskError
from distill.llm.usage import LLMUsageAttempt, usage_attempts_from_exception
from distill.worker.tasks import AgentTaskQueue

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
).filter(lambda text: bool(text.strip()))


def _expected_prompt_hash(prompt: str, workload_tag: str) -> str:
    return hashlib.sha256(f"{workload_tag}:{prompt}".encode()).hexdigest()[:16]


def _submit_task_result(
    ops_dir: Path,
    result_text: str,
    *,
    model: str = "test-model",
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> tuple[Path, Path]:
    """Complete the first pending task through the supported worker protocol."""

    queue = AgentTaskQueue(ops_dir)
    claim = queue.claim(host="pytest", worker_id="test-worker")
    assert claim is not None
    task_id = str(claim["task_id"])
    result_path = Path(str(claim["result_path"]))
    result_path.write_text(result_text, encoding="utf-8")
    queue.submit(
        task_id,
        claim_token=str(claim["claim_token"]),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    task_path = next((ops_dir / "tasks" / "pending").glob(f"*_{task_id}.json"))
    published_result = ops_dir / "tasks" / "pending" / f"{task_path.stem}_result.md"
    return task_path, published_result


def _published_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized if normalized.endswith("\n") else f"{normalized}\n"


class InspectableAgentProvider(AgentProvider):
    """Expose lookup helpers for branch-focused safety tests."""

    def find_existing_result_for_test(
        self, prompt: str, workload_tag: str
    ) -> tuple[Path, str] | None:
        return self._find_existing_result(prompt, workload_tag, max_result_bytes=1_000_000)

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
        assert task_data["timeout_seconds"] == 300

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
    LLM_Response with text equal to the written result and conservative usage
    provenance for the admitted external task.

    **Validates: Requirements 11.4**
    """
    with tempfile.TemporaryDirectory() as tmp:
        ops_dir = Path(tmp) / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        # First call: write the task file
        with pytest.raises(PendingTaskError):
            asyncio.run(provider.call("agent", prompt, call_type=workload_tag))

        # Complete the task through the ownership-bound worker protocol.
        pending_dir = ops_dir / "tasks" / "pending"
        task_files = list(pending_dir.glob("*.json"))
        assert len(task_files) == 1
        _submit_task_result(ops_dir, result_text)

        # Second call: should find the result and return it
        response = asyncio.run(provider.call("agent", prompt, call_type=workload_tag))

        assert isinstance(response, LLM_Response)
        assert response.text == _published_text(result_text)
        assert response.input_tokens > 0
        assert response.output_tokens > 0
        assert response.model == "test-model"
        assert response.provider_name == "pytest"
        assert response.provider_type == "host-managed"
        assert response.usage_source == "conservative"
        assert len(response.usage_attempts) == 1
        assert response.usage_attempts[0].usage_source == "conservative"


def test_usage_is_accepted_before_pending_task_becomes_visible(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    pending_dir = ops_dir / "tasks" / "pending"
    provider = AgentProvider(str(ops_dir))
    emitted: list[LLMUsageAttempt] = []

    def record(attempt: LLMUsageAttempt) -> None:
        assert list(pending_dir.glob("*.json")) == []
        emitted.append(attempt)

    with pytest.raises(PendingTaskError):
        asyncio.run(
            provider.call(
                "agent",
                "test prompt",
                call_type="analysis",
                max_tokens=64,
                usage_sink=record,
            )
        )

    assert len(emitted) == 1
    assert emitted[0].provider_name == "agent"
    assert emitted[0].provider_type == "host-managed"
    assert emitted[0].usage_source == "conservative"
    assert emitted[0].input_tokens > 0
    assert emitted[0].output_tokens == 64
    assert len(list(pending_dir.glob("*.json"))) == 1


def test_repeated_pending_call_reuses_one_task_identity(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    provider = AgentProvider(str(ops_dir))

    with pytest.raises(PendingTaskError) as first:
        asyncio.run(provider.call("agent", "same prompt", call_type="analysis"))
    with pytest.raises(PendingTaskError) as second:
        asyncio.run(provider.call("agent", "same prompt", call_type="analysis"))

    assert second.value.task_path == first.value.task_path
    assert "already awaiting" in str(second.value)
    assert len(list((ops_dir / "tasks" / "pending").glob("*.json"))) == 1


def test_concurrent_pending_calls_publish_one_task(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    provider = AgentProvider(str(ops_dir))

    def call_provider() -> str:
        with pytest.raises(PendingTaskError) as raised:
            asyncio.run(provider.call("agent", "same prompt", call_type="analysis"))
        return raised.value.task_path

    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(lambda _index: call_provider(), range(2)))

    assert paths[0] == paths[1]
    assert len(list((ops_dir / "tasks" / "pending").glob("*.json"))) == 1


def test_result_without_worker_receipt_remains_pending(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    provider = AgentProvider(str(ops_dir))

    with pytest.raises(PendingTaskError) as created:
        asyncio.run(provider.call("agent", "same prompt", call_type="analysis"))
    task_path = Path(created.value.task_path)
    task_data: dict[str, object] = json.loads(task_path.read_text(encoding="utf-8"))
    Path(str(task_data["result_path"])).write_text("unreceipted", encoding="utf-8")

    with pytest.raises(PendingTaskError, match="valid worker submission receipt") as replay:
        asyncio.run(provider.call("agent", "same prompt", call_type="analysis"))

    assert replay.value.task_path == str(task_path)
    assert len(list((ops_dir / "tasks" / "pending").glob("*.json"))) == 1


def test_pending_queue_capacity_fails_closed_before_task_write(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    pending_dir = ops_dir / "tasks" / "pending"
    pending_dir.mkdir(parents=True)
    for index in range(agent_mod.MAX_AGENT_PENDING_TASKS):
        (pending_dir / f"invalid_{index:03d}.json").write_text("{}", encoding="utf-8")
    provider = AgentProvider(str(ops_dir))

    with pytest.raises(ConfigurationError, match="pending task limit"):
        asyncio.run(provider.call("agent", "new prompt", call_type="analysis"))

    assert len(list(pending_dir.glob("*.json"))) == agent_mod.MAX_AGENT_PENDING_TASKS


def test_task_write_rejects_regular_directory_replacement_before_publication(
    tmp_path: Path,
) -> None:
    ops_dir = tmp_path / "ops"
    pending_dir = ops_dir / "tasks" / "pending"
    original_dir = tmp_path / "original-pending"
    provider = AgentProvider(str(ops_dir))
    emitted: list[LLMUsageAttempt] = []

    def replace_pending(attempt: LLMUsageAttempt) -> None:
        emitted.append(attempt)
        pending_dir.rename(original_dir)
        pending_dir.mkdir()

    with pytest.raises(OSError, match="task root changed") as raised:
        asyncio.run(
            provider.call(
                "agent",
                "SECRET PROMPT",
                call_type="analysis",
                usage_sink=replace_pending,
            )
        )

    assert usage_attempts_from_exception(raised.value) == tuple(emitted)
    assert list(pending_dir.iterdir()) == []
    assert list(original_dir.iterdir()) == []


def test_task_write_rejects_symlink_replacement_before_publication(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    pending_dir = ops_dir / "tasks" / "pending"
    original_dir = tmp_path / "original-pending"
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    provider = AgentProvider(str(ops_dir))

    def replace_pending(_attempt: LLMUsageAttempt) -> None:
        pending_dir.rename(original_dir)
        try:
            pending_dir.symlink_to(external_dir, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            original_dir.rename(pending_dir)
            pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(OSError, match="task root changed"):
        asyncio.run(
            provider.call(
                "agent",
                "SECRET PROMPT",
                call_type="analysis",
                usage_sink=replace_pending,
            )
        )

    assert list(external_dir.iterdir()) == []
    assert list(original_dir.iterdir()) == []


def test_task_write_cleans_external_temp_after_mid_open_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops_dir = tmp_path / "ops"
    pending_dir = ops_dir / "tasks" / "pending"
    original_dir = tmp_path / "original-pending"
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    probe_link = tmp_path / "symlink-probe"
    try:
        probe_link.symlink_to(external_dir, target_is_directory=True)
        probe_link.unlink()
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    provider = AgentProvider(str(ops_dir))
    real_open = agent_files_mod.os.open
    swapped = False

    def swap_during_temporary_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path).name.endswith(".tmp"):
            pending_dir.rename(original_dir)
            pending_dir.symlink_to(external_dir, target_is_directory=True)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(agent_files_mod.os, "open", swap_during_temporary_open)

    with pytest.raises(OSError, match="task root changed"):
        asyncio.run(provider.call("agent", "SECRET PROMPT", call_type="analysis"))

    assert swapped
    assert list(external_dir.iterdir()) == []
    assert list(original_dir.iterdir()) == []


def test_task_write_publishes_complete_owner_only_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops_dir = tmp_path / "ops"
    pending_dir = ops_dir / "tasks" / "pending"
    provider = AgentProvider(str(ops_dir))
    real_write = agent_files_mod._write_task_content
    real_link = agent_files_mod.os.link
    observed_content: list[bytes] = []

    def record_complete_write(descriptor: int, content: bytes):
        revision = real_write(descriptor, content)
        observed_content.append(content)
        return revision

    def inspect_atomic_link(source, destination, *args, **kwargs):
        destination_dir_fd = kwargs.get("dst_dir_fd")
        assert observed_content
        try:
            if destination_dir_fd is None:
                destination_exists = Path(destination).exists()
            else:
                agent_files_mod.os.stat(
                    destination,
                    dir_fd=destination_dir_fd,
                    follow_symlinks=False,
                )
                destination_exists = True
        except FileNotFoundError:
            destination_exists = False
        assert not destination_exists
        assert isinstance(json.loads(observed_content[-1]), dict)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(agent_files_mod, "_write_task_content", record_complete_write)
    monkeypatch.setattr(agent_files_mod.os, "link", inspect_atomic_link)

    with pytest.raises(PendingTaskError) as raised:
        asyncio.run(provider.call("agent", "test prompt", call_type="analysis"))

    task_path = Path(raised.value.task_path)
    assert observed_content == [task_path.read_bytes()]
    assert list(pending_dir.glob(".*.tmp")) == []
    if agent_files_mod.os.name != "nt":
        assert agent_files_mod.stat.S_IMODE(task_path.stat().st_mode) & 0o077 == 0


def test_task_writer_refuses_a_preexisting_leaf(tmp_path: Path) -> None:
    root = tmp_path / "pending"
    root.mkdir()
    validated_root = agent_files_mod.validated_task_root(root)
    assert validated_root is not None
    root, root_identity = validated_root
    task_path = root / "analysis_existing.json"
    task_path.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError):
        agent_files_mod.write_task_bytes(task_path, root, root_identity, b"replacement")

    assert task_path.read_text(encoding="utf-8") == "original"
    assert list(root.glob(".*.tmp")) == []


def test_task_writer_rejects_a_non_child_destination(tmp_path: Path) -> None:
    root = tmp_path / "pending"
    root.mkdir()
    validated_root = agent_files_mod.validated_task_root(root)
    assert validated_root is not None
    root, root_identity = validated_root

    with pytest.raises(OSError, match="not a direct child"):
        agent_files_mod.write_task_bytes(
            tmp_path / "outside.json",
            root,
            root_identity,
            b"secret",
        )

    assert list(root.iterdir()) == []


def test_task_content_writer_rejects_no_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "task.tmp"
    descriptor = agent_files_mod.os.open(
        target,
        agent_files_mod.os.O_WRONLY
        | agent_files_mod.os.O_CREAT
        | getattr(agent_files_mod.os, "O_BINARY", 0),
        0o600,
    )
    monkeypatch.setattr(agent_files_mod.os, "write", lambda *_args: 0)
    try:
        with pytest.raises(OSError, match="made no progress"):
            agent_files_mod._write_task_content(descriptor, b"secret")
    finally:
        agent_files_mod.os.close(descriptor)


def test_task_content_writer_rejects_an_incomplete_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "task.tmp"
    descriptor = agent_files_mod.os.open(
        target,
        agent_files_mod.os.O_WRONLY
        | agent_files_mod.os.O_CREAT
        | getattr(agent_files_mod.os, "O_BINARY", 0),
        0o600,
    )
    monkeypatch.setattr(agent_files_mod.os, "write", lambda _fd, content: len(content))
    try:
        with pytest.raises(OSError, match="write was incomplete"):
            agent_files_mod._write_task_content(descriptor, b"secret")
    finally:
        agent_files_mod.os.close(descriptor)


def test_bound_child_cleanup_reports_unlink_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "pending"
    root.mkdir()
    child = root / "task.tmp"
    child.write_bytes(b"content")
    validated_root = agent_files_mod.validated_task_root(root)
    assert validated_root is not None
    root, root_identity = validated_root

    def fail_unlink(*_args, **_kwargs) -> None:
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    assert not agent_files_mod._unlink_bound_child(root, root_identity, child.name, -1)
    monkeypatch.undo()
    child.unlink()


def test_task_writer_rejects_file_identity_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "pending"
    root.mkdir()
    validated_root = agent_files_mod.validated_task_root(root)
    assert validated_root is not None
    root, root_identity = validated_root
    real_write = agent_files_mod._write_task_content

    def change_identity(descriptor: int, content: bytes) -> tuple[int, int, int, int, int]:
        revision = real_write(descriptor, content)
        return revision[0], revision[1] + 1, revision[2], revision[3], revision[4]

    monkeypatch.setattr(agent_files_mod, "_write_task_content", change_identity)

    with pytest.raises(OSError, match="file changed during write"):
        agent_files_mod.write_task_bytes(
            root / "analysis_changed.json",
            root,
            root_identity,
            b"secret",
        )

    assert list(root.iterdir()) == []


def test_task_writer_rejects_root_identity_change_after_content_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "pending"
    root.mkdir()
    validated_root = agent_files_mod.validated_task_root(root)
    assert validated_root is not None
    root, root_identity = validated_root
    real_write = agent_files_mod._write_task_content
    real_identity_check = agent_files_mod.task_root_is_unchanged
    identity_changed = False

    def swap_after_write(
        descriptor: int,
        content: bytes,
    ) -> tuple[int, int, int, int, int]:
        nonlocal identity_changed
        revision = real_write(descriptor, content)
        identity_changed = True
        return revision

    def check_identity(path: Path, identity: tuple[int, int]) -> bool:
        return not identity_changed and real_identity_check(path, identity)

    monkeypatch.setattr(agent_files_mod, "_write_task_content", swap_after_write)
    monkeypatch.setattr(agent_files_mod, "task_root_is_unchanged", check_identity)

    with pytest.raises(OSError, match="task root changed"):
        agent_files_mod.write_task_bytes(
            root / "analysis_changed.json",
            root,
            root_identity,
            b"secret",
        )

    assert list(root.iterdir()) == []


def test_task_writer_removes_a_final_file_that_fails_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "pending"
    root.mkdir()
    validated_root = agent_files_mod.validated_task_root(root)
    assert validated_root is not None
    root, root_identity = validated_root
    task_path = root / "analysis_invalid.json"
    real_safety_check = agent_files_mod._unsafe_task_file

    def reject_final(path: Path, file_stat) -> bool:
        return path == task_path or real_safety_check(path, file_stat)

    monkeypatch.setattr(agent_files_mod, "_unsafe_task_file", reject_final)

    with pytest.raises(OSError, match="during task publication"):
        agent_files_mod.write_task_bytes(task_path, root, root_identity, b"secret")

    assert list(root.iterdir()) == []


def test_cached_result_reuses_admitted_usage_identity(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    provider = AgentProvider(str(ops_dir))
    admitted: list[LLMUsageAttempt] = []

    with pytest.raises(PendingTaskError):
        asyncio.run(
            provider.call(
                "agent",
                "test prompt",
                call_type="analysis",
                max_tokens=64,
                usage_sink=admitted.append,
            )
        )

    _submit_task_result(ops_dir, "done")
    collected: list[LLMUsageAttempt] = []

    response = asyncio.run(
        provider.call(
            "agent",
            "test prompt",
            call_type="analysis",
            max_tokens=64,
            usage_sink=collected.append,
        )
    )

    assert collected == list(response.usage_attempts)
    assert len(collected) == 1
    assert collected[0].attempt_id == admitted[0].attempt_id
    assert response.usage_source == "conservative"


def test_cached_result_rejects_oversized_or_hardlinked_files(tmp_path: Path) -> None:
    for attack in ("oversized", "hardlink"):
        ops_dir = tmp_path / attack / "ops"
        provider = AgentProvider(str(ops_dir))
        with pytest.raises(PendingTaskError):
            asyncio.run(
                provider.call(
                    "agent",
                    "test prompt",
                    call_type="analysis",
                    max_tokens=1,
                )
            )
        task_path = next((ops_dir / "tasks" / "pending").glob("*.json"))
        task_data: dict[str, object] = json.loads(task_path.read_text(encoding="utf-8"))
        result_path = Path(str(task_data["result_path"]))
        if attack == "oversized":
            result_path.write_bytes(b"x" * 4_097)
        else:
            outside = tmp_path / attack / "outside-secret.md"
            outside.write_text("outside agent result secret", encoding="utf-8")
            try:
                result_path.hardlink_to(outside)
            except OSError as exc:
                pytest.skip(f"hard links unavailable: {exc}")

        with pytest.raises(PendingTaskError):
            asyncio.run(
                provider.call(
                    "agent",
                    "test prompt",
                    call_type="analysis",
                    max_tokens=1,
                )
            )


def test_task_reader_rejects_parent_directory_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    task_path = pending_dir / "analysis_result.md"
    task_path.write_text("trusted result", encoding="utf-8")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / task_path.name).write_text("outside result", encoding="utf-8")
    original_dir = tmp_path / "original-pending"
    real_open = agent_files_mod.os.open
    swapped = False

    def swap_parent_before_file_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path).name == task_path.name:
            pending_dir.rename(original_dir)
            try:
                pending_dir.symlink_to(outside_dir, target_is_directory=True)
            except OSError as exc:
                original_dir.rename(pending_dir)
                pytest.skip(f"directory symlinks unavailable: {exc}")
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(agent_files_mod.os, "open", swap_parent_before_file_open)

    assert agent_files_mod.read_task_text(task_path, pending_dir, max_bytes=1_000) is None
    assert swapped


def test_task_reader_rejects_root_replaced_during_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    task_path = pending_dir / "analysis_result.md"
    task_path.write_text("trusted result", encoding="utf-8")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / task_path.name).write_text("outside result", encoding="utf-8")
    original_dir = tmp_path / "original-pending"
    real_resolve = Path.resolve
    swapped = False

    def swap_root_before_resolve(path: Path, *args, **kwargs):
        nonlocal swapped
        if not swapped and path == pending_dir:
            pending_dir.rename(original_dir)
            try:
                pending_dir.symlink_to(outside_dir, target_is_directory=True)
            except OSError as exc:
                original_dir.rename(pending_dir)
                pytest.skip(f"directory symlinks unavailable: {exc}")
            swapped = True
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", swap_root_before_resolve)

    assert agent_files_mod.read_task_text(task_path, pending_dir, max_bytes=1_000) is None
    assert swapped


def test_task_reader_rejects_invalid_paths_limits_and_encoding(tmp_path: Path) -> None:
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    task_path = pending_dir / "analysis_result.md"
    task_path.write_bytes(b"\xff")
    outside_path = tmp_path / "outside_result.md"
    outside_path.write_text("outside result", encoding="utf-8")

    assert agent_files_mod.read_task_text(task_path, pending_dir, max_bytes=-1) is None
    assert agent_files_mod.read_task_text(outside_path, pending_dir, max_bytes=1_000) is None
    assert agent_files_mod.read_task_text(task_path, pending_dir, max_bytes=1_000) is None
    assert agent_files_mod.read_task_text(task_path, tmp_path / "missing", max_bytes=1_000) is None
    validated_root = agent_files_mod.validated_task_root(pending_dir)
    assert validated_root is not None
    root, root_identity = validated_root
    wrong_identity = root_identity[0], root_identity[1] + 1
    assert (
        agent_files_mod.read_task_text(
            task_path,
            root,
            max_bytes=1_000,
            root_identity=wrong_identity,
        )
        is None
    )


def test_task_reader_rejects_file_replaced_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    task_path = pending_dir / "analysis_result.md"
    task_path.write_text("trusted result", encoding="utf-8")
    replacement = tmp_path / "replacement.md"
    replacement.write_text("changed result", encoding="utf-8")
    real_fstat = agent_files_mod.os.fstat
    regular_file_stats = 0

    def replace_after_stream_read(descriptor):
        nonlocal regular_file_stats
        file_stat = real_fstat(descriptor)
        if agent_files_mod.stat.S_ISREG(file_stat.st_mode):
            regular_file_stats += 1
            if regular_file_stats == 2:
                replacement.replace(task_path)
        return file_stat

    monkeypatch.setattr(agent_files_mod.os, "fstat", replace_after_stream_read)

    assert agent_files_mod.read_task_text(task_path, pending_dir, max_bytes=1_000) is None
    assert regular_file_stats == 2


def test_existing_result_lookup_skips_unreadable_task_file(tmp_path: Path) -> None:
    provider = InspectableAgentProvider(str(tmp_path / "ops"))
    pending_dir = tmp_path / "ops" / "tasks" / "pending"
    pending_dir.mkdir(parents=True)
    (pending_dir / "analysis_unsafe.json").write_bytes(b"x" * (1_048_576 + 1))

    assert provider.find_existing_result_for_test("test prompt", "analysis") is None


def test_existing_result_lookup_binds_one_pending_directory_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops_dir = tmp_path / "ops"
    provider = InspectableAgentProvider(str(ops_dir))
    pending_dir = ops_dir / "tasks" / "pending"
    pending_dir.mkdir(parents=True)
    prompt = "test prompt"
    task_path = pending_dir / "analysis_bound.json"
    result_path = pending_dir / "analysis_bound_result.md"
    task_document = json.dumps(
        {
            "prompt_hash": _expected_prompt_hash(prompt, "analysis"),
            "result_path": str(result_path),
        }
    )
    task_path.write_text(task_document, encoding="utf-8")
    result_path.write_text("trusted result", encoding="utf-8")
    original_dir = tmp_path / "original-pending"
    real_read = agent_mod.read_task_text
    swapped = False

    def swap_after_task_read(
        path: Path,
        root: Path,
        *,
        max_bytes: int,
        root_identity: tuple[int, int] | None = None,
    ) -> str | None:
        nonlocal swapped
        result = real_read(
            path,
            root,
            max_bytes=max_bytes,
            root_identity=root_identity,
        )
        if not swapped and path.suffix == ".json" and result is not None:
            pending_dir.rename(original_dir)
            pending_dir.mkdir()
            (pending_dir / task_path.name).write_text(task_document, encoding="utf-8")
            (pending_dir / result_path.name).write_text("attacker result", encoding="utf-8")
            swapped = True
        return result

    monkeypatch.setattr(agent_mod, "read_task_text", swap_after_task_read)

    assert provider.find_existing_result_for_test(prompt, "analysis") is None
    assert swapped


def test_task_reader_rejects_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    task_path = pending_dir / "analysis_result.md"
    task_path.write_text("result", encoding="utf-8")
    real_open = agent_files_mod.os.open

    def fail_file_open(path, flags, *args, **kwargs):
        if Path(path).name == task_path.name:
            raise OSError("simulated open failure")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(agent_files_mod.os, "open", fail_file_open)

    assert agent_files_mod.read_task_text(task_path, pending_dir, max_bytes=1_000) is None


def test_task_reader_rejects_root_change_after_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    task_path = pending_dir / "analysis_result.md"
    task_path.write_text("result", encoding="utf-8")
    real_check = agent_files_mod.task_root_is_unchanged
    calls = 0

    def fail_final_check(root, identity):
        nonlocal calls
        calls += 1
        return calls < 3 and real_check(root, identity)

    monkeypatch.setattr(agent_files_mod, "task_root_is_unchanged", fail_final_check)

    assert agent_files_mod.read_task_text(task_path, pending_dir, max_bytes=1_000) is None
    assert calls == 3


def test_pending_result_path_rejects_missing_root_and_resolution_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AgentProvider(str(tmp_path / "ops"))
    result_path = tmp_path / "ops" / "tasks" / "pending" / "analysis_result.md"
    monkeypatch.setattr(provider, "_task_root", lambda *_args: None)
    assert not provider._is_pending_result_path(result_path)

    pending_root = result_path.parent.resolve(strict=False)
    monkeypatch.setattr(provider, "_task_root", lambda *_args: pending_root)
    real_resolve = Path.resolve

    def fail_result_resolution(path: Path, *args, **kwargs):
        if path == result_path.parent:
            raise OSError("simulated resolution failure")
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_result_resolution)
    assert not provider._is_pending_result_path(result_path)


def test_cached_result_without_receipt_is_rejected_after_task_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AgentProvider(str(tmp_path / "ops"))
    missing_task = tmp_path / "already-removed.json"
    monkeypatch.setattr(
        provider,
        "_find_existing_result",
        lambda *_args, **_kwargs: (missing_task, "completed result"),
    )

    with pytest.raises(PendingTaskError, match="valid worker submission receipt") as raised:
        asyncio.run(provider.call("agent", "test prompt", call_type="analysis"))

    assert raised.value.task_path == str(missing_task)
    assert not missing_task.exists()


def test_existing_result_lookup_ignores_nonmatching_task(tmp_path: Path) -> None:
    provider = InspectableAgentProvider(str(tmp_path / "ops"))
    pending_dir = tmp_path / "ops" / "tasks" / "pending"
    pending_dir.mkdir(parents=True)
    task_path = pending_dir / "analysis_unrelated.json"
    task_path.write_text(
        json.dumps(
            {
                "prompt_hash": "not-the-target",
                "result_path": str(pending_dir / "analysis_unrelated_result.md"),
            }
        ),
        encoding="utf-8",
    )

    assert provider.find_existing_result_for_test("test prompt", "analysis") is None


def test_agent_rejects_oversized_task_before_usage_admission(tmp_path: Path) -> None:
    provider = AgentProvider(str(tmp_path / "ops"))
    admitted: list[LLMUsageAttempt] = []

    with pytest.raises(ValueError, match="serialized agent task exceeds"):
        asyncio.run(
            provider.call(
                "agent",
                "x" * (1_048_576 + 1),
                call_type="analysis",
                usage_sink=admitted.append,
            )
        )

    assert admitted == []
    assert list((tmp_path / "ops" / "tasks" / "pending").glob("*.json")) == []


@pytest.mark.parametrize(("argument", "value"), (("max_tokens", 0), ("timeout", 0)))
def test_agent_call_rejects_nonpositive_limits(tmp_path: Path, argument: str, value: int) -> None:
    provider = AgentProvider(str(tmp_path / "ops"))

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(provider.call("agent", "test prompt", **{argument: value}))


def test_cached_result_is_preserved_when_accounting_rejects(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    provider = AgentProvider(str(ops_dir))

    with pytest.raises(PendingTaskError):
        asyncio.run(provider.call("agent", "test prompt", call_type="analysis"))

    task_path, _result_path = _submit_task_result(ops_dir, "done")

    def reject(_attempt: LLMUsageAttempt) -> None:
        raise RuntimeError("ledger unavailable")

    with pytest.raises(RuntimeError, match="ledger unavailable"):
        asyncio.run(
            provider.call(
                "agent",
                "test prompt",
                call_type="analysis",
                usage_sink=reject,
            )
        )

    assert task_path.exists()


def test_cached_result_does_not_mutate_a_replaced_pending_directory(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"
    provider = AgentProvider(str(ops_dir))

    with pytest.raises(PendingTaskError):
        asyncio.run(provider.call("agent", "test prompt", call_type="analysis"))

    pending_dir = ops_dir / "tasks" / "pending"
    task_path, _result_path = _submit_task_result(ops_dir, "trusted result")
    original_dir = tmp_path / "original-pending"

    def replace_pending(_attempt: LLMUsageAttempt) -> None:
        pending_dir.rename(original_dir)
        pending_dir.mkdir()
        (pending_dir / task_path.name).write_text("replacement marker", encoding="utf-8")

    response = asyncio.run(
        provider.call(
            "agent",
            "test prompt",
            call_type="analysis",
            usage_sink=replace_pending,
        )
    )

    assert response.text == "trusted result\n"
    assert (pending_dir / task_path.name).read_text(encoding="utf-8") == "replacement marker"
    assert (original_dir / task_path.name).exists()


def test_task_write_failure_preserves_preaccepted_usage_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ops_dir = tmp_path / "ops"
    provider = AgentProvider(str(ops_dir))
    emitted: list[LLMUsageAttempt] = []

    def fail_task_write(*_args, **_kwargs) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(agent_mod, "write_task_bytes", fail_task_write)

    with pytest.raises(OSError, match="disk full") as raised:
        asyncio.run(
            provider.call(
                "agent",
                "test prompt",
                call_type="analysis",
                usage_sink=emitted.append,
            )
        )

    assert usage_attempts_from_exception(raised.value) == tuple(emitted)
    assert len(emitted) == 1
    assert list((ops_dir / "tasks" / "pending").glob("*.json")) == []


def test_task_directory_is_rechecked_after_creation(tmp_path: Path, monkeypatch) -> None:
    provider = AgentProvider(str(tmp_path / "ops"))
    safe_root = tmp_path / "ops" / "tasks" / "pending"
    roots = iter((safe_root, None))
    monkeypatch.setattr(provider, "_task_root", lambda *_args: next(roots))

    with pytest.raises(ConfigurationError, match="pending task directory"):
        provider._ensure_task_dir(safe_root, "pending")


def test_task_root_fails_closed_when_path_resolution_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ops_dir = tmp_path / "ops"
    provider = InspectableAgentProvider(str(ops_dir))
    original_resolve = Path.resolve

    def fail_ops_resolution(path: Path, *args, **kwargs) -> Path:
        if path == ops_dir:
            raise OSError("path unavailable")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_ops_resolution)

    assert provider.task_root_for_test(ops_dir / "tasks" / "pending", "pending") is None


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
        (pending_dir / "analysis_list.json").write_text("[]", encoding="utf-8")
        (pending_dir / "analysis_scalar.json").write_text('"task"', encoding="utf-8")
        (pending_dir / "analysis_deeply_nested.json").write_text(
            "[" * 5_000 + "]" * 5_000,
            encoding="utf-8",
        )
        for suffix, result_path in (("list_path", []), ("object_path", {"path": "result"})):
            (pending_dir / f"analysis_{suffix}.json").write_text(
                json.dumps({"prompt_hash": prompt_hash, "result_path": result_path}),
                encoding="utf-8",
            )
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
        assert len(task_files) == 9

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

        internal_target = pending_dir / "analysis_internal_target.md"
        internal_target.write_text("internal symlink target", encoding="utf-8")
        internal_symlink = pending_dir / "analysis_internal_symlink_result.md"
        try:
            internal_symlink.symlink_to(internal_target)
        except (NotImplementedError, OSError):
            internal_symlink = None
        if internal_symlink is not None:
            attack_result_paths.append(internal_symlink)

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

    def test_completed_task_remains_a_replayable_receipt(self, tmp_path: Path) -> None:
        """A completed task remains available for deterministic replay."""
        ops_dir = tmp_path / "ops"
        provider = AgentProvider(ops_dir=str(ops_dir))

        with pytest.raises(PendingTaskError):
            asyncio.run(provider.call("agent", "test prompt", call_type="synthesis"))

        pending_dir = ops_dir / "tasks" / "pending"
        task_files = list(pending_dir.glob("synthesis_*.json"))
        assert len(task_files) == 1

        _task_path, result_path = _submit_task_result(ops_dir, "completed result")

        first = asyncio.run(provider.call("agent", "test prompt", call_type="synthesis"))
        second = asyncio.run(provider.call("agent", "test prompt", call_type="synthesis"))

        assert first.text == second.text == "completed result\n"
        assert task_files[0].exists()
        assert result_path.exists()
        assert list(pending_dir.glob("synthesis_*.json")) == task_files
        assert not (ops_dir / "tasks" / "completed").exists()
