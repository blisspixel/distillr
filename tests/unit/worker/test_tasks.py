"""Tests for the scratch-only host-session worker protocol."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from distill.llm.providers.agent import AgentProvider, agent_result_byte_limit
from distill.llm.router import PendingTaskError
from distill.worker import _contracts as worker_contracts
from distill.worker import tasks as worker_tasks
from distill.worker.tasks import (
    AgentTaskQueue,
    WorkerTaskConflict,
    WorkerTaskInvalid,
    WorkerTaskNotFound,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
TOKEN = "worker-claim-token-value-1234567890"


def _seed_task(
    ops_dir: Path,
    *,
    prompt: str = "Return a receipt-backed markdown answer.",
    workload: str = "analysis",
    max_tokens: int = 64,
) -> tuple[str, Path, AgentProvider]:
    provider = AgentProvider(str(ops_dir))
    with pytest.raises(PendingTaskError) as raised:
        asyncio.run(
            provider.call(
                "agent",
                prompt,
                call_type=workload,
                max_tokens=max_tokens,
            )
        )
    task_path = Path(raised.value.task_path)
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    return payload["task_id"], task_path, provider


def _queue(ops_dir: Path, *, now=NOW, tokens: list[str] | None = None) -> AgentTaskQueue:
    token_values = iter(tokens or [TOKEN])
    return AgentTaskQueue(
        ops_dir,
        now=lambda: now,
        token_factory=lambda: next(token_values),
    )


def test_claim_submit_replay_and_status_lifecycle(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, _task_path, provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)

    pending = queue.list_tasks()
    assert pending[0]["status"] == "pending"
    assert "prompt" not in pending[0]

    claim = queue.claim(host="Codex", worker_id="Session.1")
    assert claim is not None
    assert claim["task_id"] == task_id
    assert claim["host"] == "codex"
    assert claim["worker_id"] == "session.1"
    assert claim["billing"]["no_metered_proven"] is False
    assert claim["allowed_write_paths"] == [claim["result_path"]]
    assert Path(claim["prompt_path"]).read_text(encoding="utf-8").startswith("Return")
    assert json.loads(Path(claim["task_path"]).read_text(encoding="utf-8"))[
        "allowed_write_paths"
    ] == ["result.md"]
    assert queue.claim(host="codex") is None

    claimed = queue.list_tasks()[0]
    assert claimed["status"] == "claimed"
    assert claimed["claim"]["lease_expired"] is False
    assert claimed["claim"]["host"] == "codex"

    Path(claim["result_path"]).write_bytes(b"# Result\r\n\r\nGrounded answer.\r\n")
    submitted = queue.submit(
        task_id,
        claim_token=claim["claim_token"],
        model="gpt-test",
        input_tokens=123,
        output_tokens=17,
    )
    assert submitted["submitted"] is True
    assert submitted["idempotent"] is False
    assert submitted["usage"] == {
        "input_tokens": 123,
        "output_tokens": 17,
        "source": "host-reported",
    }
    assert submitted["billing"] == {
        "class": "host-managed",
        "no_metered_proven": False,
        "proof": "unavailable",
    }
    assert Path(submitted["published_result_path"]).read_bytes() == (
        b"# Result\n\nGrounded answer.\n"
    )

    replay = asyncio.run(
        provider.call(
            "agent",
            "Return a receipt-backed markdown answer.",
            call_type="analysis",
            max_tokens=64,
        )
    )
    assert replay.text == "# Result\n\nGrounded answer.\n"
    assert replay.model == "gpt-test"
    assert replay.provider_name == "codex"
    assert replay.provider_type == "host-managed"
    assert replay.input_tokens == 123
    assert replay.output_tokens == 17
    assert replay.usage_source == "host-reported"

    duplicate = queue.submit(task_id, claim_token=claim["claim_token"])
    assert duplicate["idempotent"] is True
    assert duplicate["model"] == "gpt-test"
    assert queue.list_tasks()[0]["status"] == "completed"
    assert queue.claim(host="codex") is None
    with pytest.raises(WorkerTaskConflict, match="completed tasks"):
        queue.abandon(task_id, claim_token=claim["claim_token"], reason="too late")
    with pytest.raises(WorkerTaskConflict, match="completed or submitting"):
        queue.release_expired(task_id)


def test_unreported_host_usage_is_conservative_but_host_managed(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, _task_path, provider = _seed_task(ops_dir, prompt="Short answer")
    queue = _queue(ops_dir)
    claim = queue.claim(host="claude")
    assert claim is not None
    Path(claim["result_path"]).write_text("Done", encoding="utf-8")
    submitted = queue.submit(task_id, claim_token=claim["claim_token"])
    assert submitted["usage"]["source"] == "host-managed-unavailable"

    response = asyncio.run(
        provider.call("agent", "Short answer", call_type="analysis", max_tokens=64)
    )
    assert response.model == "host:claude"
    assert response.provider_name == "claude"
    assert response.provider_type == "host-managed"
    assert response.usage_source == "conservative"
    assert response.input_tokens > 0
    assert response.output_tokens == 64


def test_empty_queue_filter_and_claim_argument_validation(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    queue = _queue(ops_dir)
    assert queue.list_tasks() == []
    assert queue.claim(host="codex") is None
    with pytest.raises(WorkerTaskInvalid, match="non-empty ops"):
        AgentTaskQueue("")

    _seed_task(ops_dir, workload="analysis")
    assert queue.claim(host="codex", workload="synthesis") is None

    invalid_calls = [
        {"host": "../codex"},
        {"host": "codex", "worker_id": "bad worker"},
        {"host": "codex", "workload": "../analysis"},
        {"host": "codex", "lease_seconds": 59},
        {"host": "codex", "lease_seconds": 604_801},
        {"host": "codex", "lease_seconds": True},
    ]
    for kwargs in invalid_calls:
        with pytest.raises(WorkerTaskInvalid):
            queue.claim(**kwargs)


def test_abandon_releases_claim_and_allows_reclaim(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, _task_path, _provider = _seed_task(ops_dir)
    second_token = "second-worker-claim-token-123456789"
    queue = _queue(ops_dir, tokens=[TOKEN, second_token])
    first = queue.claim(host="grok")
    assert first is not None

    with pytest.raises(WorkerTaskConflict, match="does not own"):
        queue.submit(task_id, claim_token="wrong-token-value-123456")
    with pytest.raises(WorkerTaskConflict, match="does not own"):
        queue.abandon(
            task_id,
            claim_token="wrong-token-value-123456",
            reason="wrong owner",
        )

    abandoned = queue.abandon(
        task_id,
        claim_token=first["claim_token"],
        reason="host quota exhausted",
    )
    assert abandoned["abandoned"] is True
    assert Path(abandoned["abandonment_receipt_path"]).exists()
    assert queue.list_tasks()[0]["status"] == "pending"

    second = queue.claim(host="antigravity")
    assert second is not None
    assert second["claim_token"] == second_token
    assert second["workspace"] != first["workspace"]
    with pytest.raises(WorkerTaskConflict, match="does not own"):
        queue.abandon(
            task_id,
            claim_token=first["claim_token"],
            reason="old claim",
        )


def test_release_expired_claim_requires_expiry(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, _task_path, _provider = _seed_task(ops_dir)
    current = [NOW]
    queue = AgentTaskQueue(
        ops_dir,
        now=lambda: current[0],
        token_factory=lambda: TOKEN,
    )
    claim = queue.claim(host="codex", lease_seconds=60)
    assert claim is not None
    with pytest.raises(WorkerTaskConflict, match="remains active"):
        queue.release_expired(task_id)

    current[0] = NOW + timedelta(seconds=61)
    assert queue.list_tasks()[0]["claim"]["lease_expired"] is True
    released = queue.release_expired(task_id)
    assert released["released"] is True
    assert Path(released["release_receipt_path"]).exists()
    assert queue.list_tasks()[0]["status"] == "pending"
    with pytest.raises(WorkerTaskNotFound, match="no active claim"):
        queue.release_expired(task_id)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing required paths"),
        ("unexpected", "unexpected paths"),
        ("empty", "non-whitespace"),
        ("prompt", "staged prompt changed"),
        ("task", "staged task metadata changed"),
    ],
)
def test_submit_rejects_workspace_contract_violations(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    ops_dir = tmp_path / mutation / ".distill"
    task_id, _task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    claim = queue.claim(host="codex")
    assert claim is not None
    workspace = Path(claim["workspace"])
    result = Path(claim["result_path"])
    if mutation == "missing":
        pass
    elif mutation == "unexpected":
        result.write_text("valid", encoding="utf-8")
        (workspace / "notes.txt").write_text("unexpected", encoding="utf-8")
    elif mutation == "empty":
        result.write_text(" \n", encoding="utf-8")
    elif mutation == "prompt":
        result.write_text("valid", encoding="utf-8")
        Path(claim["prompt_path"]).write_text("changed", encoding="utf-8")
    else:
        result.write_text("valid", encoding="utf-8")
        Path(claim["task_path"]).write_text("{}", encoding="utf-8")

    with pytest.raises((WorkerTaskConflict, WorkerTaskInvalid), match=message):
        queue.submit(task_id, claim_token=claim["claim_token"])


def test_submit_rejects_result_and_submission_conflicts(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    claim = queue.claim(host="codex")
    assert claim is not None
    Path(claim["result_path"]).write_text("worker result", encoding="utf-8")

    task_payload = json.loads(task_path.read_text(encoding="utf-8"))
    Path(task_payload["result_path"]).write_text("other result", encoding="utf-8")
    with pytest.raises(WorkerTaskConflict, match="different published result"):
        queue.submit(task_id, claim_token=claim["claim_token"])

    Path(task_payload["result_path"]).unlink()
    queue.submit(task_id, claim_token=claim["claim_token"])
    submission_path = task_path.with_suffix(".submission")
    payload = json.loads(submission_path.read_text(encoding="utf-8"))
    payload["claim_token_hash"] = "0" * 64
    submission_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkerTaskConflict, match="another claim"):
        queue.submit(task_id, claim_token=claim["claim_token"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "agent-task.v999", "unsupported schema"),
        ("expected_output_format", "json", "markdown output"),
        ("prompt_hash", "wrong", "prompt hash"),
        ("max_result_bytes", 9999, "result size limit"),
        ("created_at", 123, "creation timestamp"),
        ("max_tokens", 0, "positive integer"),
        ("timeout_seconds", False, "positive integer"),
        ("result_path", "outside.md", "outside the queue contract"),
        ("result_path", None, "no valid result path"),
        ("workload_tag", "bad workload", "invalid workload"),
    ],
)
def test_invalid_task_contract_is_reported_and_not_claimed(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    ops_dir = tmp_path / field / ".distill"
    _task_id, task_path, _provider = _seed_task(ops_dir)
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    payload[field] = value
    task_path.write_text(json.dumps(payload), encoding="utf-8")
    queue = _queue(ops_dir)
    row = queue.list_tasks()[0]
    assert row["status"] == "invalid"
    assert message in row["error"]
    with pytest.raises(WorkerTaskInvalid, match=message):
        queue.claim(host="codex")


def test_task_filename_identity_and_duplicate_lookup_are_rejected(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, task_path, _provider = _seed_task(ops_dir)
    renamed = task_path.with_name(f"wrong_{task_id}.json")
    task_path.rename(renamed)
    queue = _queue(ops_dir)
    assert "declared identity" in queue.list_tasks()[0]["error"]
    with pytest.raises(WorkerTaskNotFound):
        queue.submit(task_id, claim_token=TOKEN)


def test_invalid_submit_arguments_and_missing_resources(tmp_path: Path) -> None:
    queue = _queue(tmp_path / ".distill")
    with pytest.raises(WorkerTaskInvalid, match="task id"):
        queue.submit("bad", claim_token=TOKEN)
    with pytest.raises(WorkerTaskInvalid, match="claim token"):
        queue.submit("0123456789ab", claim_token="short")
    with pytest.raises(WorkerTaskNotFound, match="no pending"):
        queue.submit("0123456789ab", claim_token=TOKEN)

    ops_dir = tmp_path / "seeded" / ".distill"
    task_id, _task_path, _provider = _seed_task(ops_dir)
    seeded = _queue(ops_dir)
    claim = seeded.claim(host="codex")
    assert claim is not None
    Path(claim["result_path"]).write_text("valid", encoding="utf-8")
    with pytest.raises(WorkerTaskInvalid, match="supplied together"):
        seeded.submit(task_id, claim_token=claim["claim_token"], input_tokens=1)
    with pytest.raises(WorkerTaskInvalid, match="model"):
        seeded.submit(task_id, claim_token=claim["claim_token"], model="bad\nmodel")
    with pytest.raises(WorkerTaskInvalid, match="reason"):
        seeded.abandon(task_id, claim_token=claim["claim_token"], reason="")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("extra", True, "fields do not match"),
        ("schema_version", "wrong", "unsupported schema"),
        ("protocol", "wrong", "unsupported protocol"),
        ("task_id", "000000000000", "identity mismatch"),
        ("claim_token_hash", "bad", "token hash"),
        ("host", "bad host", "claim host"),
        ("host", "Codex", "not canonical"),
        ("workspace", "wrong", "workspace mismatch"),
        ("prompt_sha256", "bad", "staging hash"),
        ("lease_expires_at", NOW.isoformat(), "claim lease"),
        ("billing_class", "included-plan", "billing metadata"),
        ("no_metered_proven", True, "billing metadata"),
        ("allowed_write_paths", ["other.md"], "write boundary"),
    ],
)
def test_invalid_claim_receipts_are_reported(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    ops_dir = tmp_path / field / ".distill"
    _task_id, task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    claim = queue.claim(host="codex")
    assert claim is not None
    claim_path = task_path.with_suffix(".claim")
    payload = json.loads(claim_path.read_text(encoding="utf-8"))
    payload[field] = value
    claim_path.write_text(json.dumps(payload), encoding="utf-8")
    row = queue.list_tasks()[0]
    assert row["status"] == "invalid"
    assert message in row["error"]


def test_claim_receipt_rejects_invalid_json_and_timestamps(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    _task_id, task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    assert queue.claim(host="codex") is not None
    claim_path = task_path.with_suffix(".claim")
    claim_path.write_text("not json", encoding="utf-8")
    assert "not valid JSON" in queue.list_tasks()[0]["error"]

    original = _queue(tmp_path / "other" / ".distill")
    _other_id, other_path, _provider = _seed_task(tmp_path / "other" / ".distill")
    assert original.claim(host="codex") is not None
    other_claim = other_path.with_suffix(".claim")
    data = json.loads(other_claim.read_text(encoding="utf-8"))
    data["claimed_at"] = "not-a-time"
    other_claim.write_text(json.dumps(data), encoding="utf-8")
    assert "ISO 8601" in original.list_tasks()[0]["error"]

    third_ops = tmp_path / "third" / ".distill"
    _third_id, third_path, _provider = _seed_task(third_ops)
    third = _queue(third_ops)
    assert third.claim(host="codex") is not None
    third_claim = third_path.with_suffix(".claim")
    data = json.loads(third_claim.read_text(encoding="utf-8"))
    data["claimed_at"] = "2026-07-15T12:00:00"
    third_claim.write_text(json.dumps(data), encoding="utf-8")
    assert "timezone" in third.list_tasks()[0]["error"]


def test_claim_setup_failure_rolls_back_claim_and_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops_dir = tmp_path / ".distill"
    _task_id, task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    real_write = worker_tasks.write_task_bytes
    calls = 0

    def fail_staging(path, root, identity, content):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("staging failed")
        return real_write(path, root, identity, content)

    monkeypatch.setattr(worker_tasks, "write_task_bytes", fail_staging)
    with pytest.raises(OSError, match="staging failed"):
        queue.claim(host="codex")
    assert not task_path.with_suffix(".claim").exists()
    work_root = ops_dir / "tasks" / "work"
    assert not work_root.exists() or list(work_root.iterdir()) == []


def test_claim_collision_is_a_clean_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ops_dir = tmp_path / ".distill"
    _task_id, _task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    real_write = worker_tasks.write_task_bytes

    def collide(path, root, identity, content):
        if path.suffix == ".claim":
            raise FileExistsError(path)
        return real_write(path, root, identity, content)

    monkeypatch.setattr(worker_tasks, "write_task_bytes", collide)
    assert queue.claim(host="codex") is None


def test_workspace_and_result_safety_fail_closed(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, _task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    claim = queue.claim(host="codex")
    assert claim is not None
    Path(claim["prompt_path"]).unlink()
    Path(claim["task_path"]).unlink()
    Path(claim["workspace"]).rmdir()
    with pytest.raises(WorkerTaskInvalid, match="workspace is unsafe"):
        queue.submit(task_id, claim_token=claim["claim_token"])

    second_ops = tmp_path / "unsafe-result" / ".distill"
    _second_id, second_path, _provider = _seed_task(second_ops)
    task = json.loads(second_path.read_text(encoding="utf-8"))
    result_path = Path(task["result_path"])
    outside = tmp_path / "outside-result.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        result_path.symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlinks unavailable: {exc}")
    row = _queue(second_ops).list_tasks()[0]
    assert row["status"] == "invalid"
    assert "unsafe or oversized" in row["error"]


def test_release_and_abandon_detect_claim_removal_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ops_dir = tmp_path / "abandon" / ".distill"
    task_id, _task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    claim = queue.claim(host="codex")
    assert claim is not None
    monkeypatch.setattr(worker_tasks, "remove_task_file", lambda *_args, **_kwargs: False)
    with pytest.raises(WorkerTaskConflict, match="claim changed"):
        queue.abandon(task_id, claim_token=claim["claim_token"], reason="race")

    monkeypatch.undo()
    expired_ops = tmp_path / "expired" / ".distill"
    expired_id, _task_path, _provider = _seed_task(expired_ops)
    current = [NOW]
    expired = AgentTaskQueue(
        expired_ops,
        now=lambda: current[0],
        token_factory=lambda: TOKEN,
    )
    assert expired.claim(host="codex", lease_seconds=60) is not None
    current[0] += timedelta(seconds=61)
    monkeypatch.setattr(worker_tasks, "remove_task_file", lambda *_args, **_kwargs: False)
    with pytest.raises(WorkerTaskConflict, match="claim changed"):
        expired.release_expired(expired_id)


def test_internal_validation_helpers_cover_malformed_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(WorkerTaskInvalid, match="must be a string"):
        worker_tasks._required_text({"field": 1}, "field")
    with pytest.raises(WorkerTaskInvalid, match="non-empty"):
        worker_tasks._required_text({"field": " "}, "field")
    with pytest.raises(WorkerTaskInvalid, match="JSON object"):
        worker_tasks._json_mapping("[]", label="value")
    with pytest.raises(WorkerTaskInvalid, match="valid JSON"):
        worker_tasks._json_mapping("not-json", label="value")
    with pytest.raises(WorkerTaskInvalid, match="between 0"):
        worker_tasks._validate_usage(-1, 2)
    with pytest.raises(WorkerTaskInvalid, match="between 0"):
        worker_tasks._validate_usage(1, True)
    monkeypatch.setattr(worker_contracts, "MAX_AGENT_RESULT_BYTES", 4)
    with pytest.raises(WorkerTaskInvalid, match="global result size"):
        worker_tasks._normalized_result_bytes("12345")

    missing_created = {
        "task_id": "0123456789ab",
        "workload_tag": "analysis",
        "prompt": "prompt",
        "prompt_hash": AgentProvider._prompt_hash("prompt", "analysis"),
        "schema_version": "agent-task.v1",
        "expected_output_format": "markdown",
    }
    path = tmp_path / "analysis_0123456789ab.json"
    identity = worker_tasks._validated_task_identity(missing_created, path)
    assert identity[:2] == ("0123456789ab", "analysis")
    assert worker_tasks._optional_creation_timestamp(missing_created, path) == ""
    assert worker_tasks._staged_prompt_bytes("prompt\n") == b"prompt\n"

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real_iterdir = Path.iterdir

    def fail_for_workspace(candidate: Path):
        if candidate == workspace:
            raise OSError("enumeration failed")
        return real_iterdir(candidate)

    monkeypatch.setattr(Path, "iterdir", fail_for_workspace)
    with pytest.raises(WorkerTaskInvalid, match="cannot be enumerated"):
        worker_tasks._validate_workspace_names(workspace)
    monkeypatch.setattr(Path, "iterdir", real_iterdir)

    task = worker_tasks._PendingTask(
        task_id="0123456789ab",
        workload="analysis",
        prompt="prompt",
        prompt_hash=missing_created["prompt_hash"],
        task_path=path,
        task_bytes=b"{}",
        result_path=tmp_path / "analysis_0123456789ab_result.md",
        max_tokens=64,
        max_result_bytes=1024,
        timeout_seconds=60,
        created_at="",
    )
    monkeypatch.setattr(worker_contracts, "read_task_text", lambda *_args, **_kwargs: None)
    with pytest.raises(WorkerTaskInvalid, match="unsafe or oversized"):
        worker_tasks._read_workspace_files(
            workspace,
            worker_tasks._BoundRoot(workspace, (0, 0)),
            task,
        )


def test_submit_requires_one_claim_and_one_task_identity(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    with pytest.raises(WorkerTaskNotFound, match="no active claim"):
        queue.submit(task_id, claim_token=TOKEN)

    payload = json.loads(task_path.read_text(encoding="utf-8"))
    payload["workload_tag"] = "synthesis"
    payload["prompt_hash"] = AgentProvider._prompt_hash(payload["prompt"], "synthesis")
    duplicate = task_path.with_name(f"synthesis_{task_id}.json")
    payload["result_path"] = str(duplicate.with_name(f"synthesis_{task_id}_result.md"))
    duplicate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WorkerTaskInvalid, match="multiple pending tasks"):
        queue.submit(task_id, claim_token=TOKEN)


def test_submit_rejects_clock_rollback_in_generated_receipt(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, _task_path, _provider = _seed_task(ops_dir)
    current = [NOW]
    queue = AgentTaskQueue(
        ops_dir,
        now=lambda: current[0],
        token_factory=lambda: TOKEN,
    )
    claim = queue.claim(host="codex")
    assert claim is not None
    Path(claim["result_path"]).write_text("result", encoding="utf-8")
    current[0] = NOW - timedelta(seconds=1)

    with pytest.raises(WorkerTaskInvalid, match="predates its claim"):
        queue.submit(task_id, claim_token=claim["claim_token"])


@pytest.mark.parametrize("mutation", ["prompt", "task"])
def test_submit_rechecks_staged_files_against_current_pending_task(
    tmp_path: Path,
    mutation: str,
) -> None:
    ops_dir = tmp_path / mutation / ".distill"
    task_id, task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    claim = queue.claim(host="codex")
    assert claim is not None
    Path(claim["result_path"]).write_text("result", encoding="utf-8")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    if mutation == "prompt":
        task["prompt"] = "A changed pending prompt"
        task["prompt_hash"] = AgentProvider._prompt_hash(task["prompt"], "analysis")
        claim_path = task_path.with_suffix(".claim")
        claim_payload = json.loads(claim_path.read_text(encoding="utf-8"))
        claim_payload["prompt_hash"] = task["prompt_hash"]
        claim_path.write_text(json.dumps(claim_payload), encoding="utf-8")
        message = "prompt no longer matches"
    else:
        task["max_tokens"] = 65
        task["max_result_bytes"] = agent_result_byte_limit(65)
        message = "metadata no longer matches"
    task_path.write_text(json.dumps(task), encoding="utf-8")

    with pytest.raises(WorkerTaskConflict, match=message):
        queue.submit(task_id, claim_token=claim["claim_token"])


def test_submit_rejects_semantically_invalid_existing_receipt(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    task_id, task_path, _provider = _seed_task(ops_dir)
    queue = _queue(ops_dir)
    claim = queue.claim(host="codex")
    assert claim is not None
    Path(claim["result_path"]).write_text("result", encoding="utf-8")
    queue.submit(task_id, claim_token=claim["claim_token"])
    submission_path = task_path.with_suffix(".submission")
    payload = json.loads(submission_path.read_text(encoding="utf-8"))
    payload["billing"]["proof"] = "claimed"
    submission_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WorkerTaskConflict, match="invalid submission receipt"):
        queue.submit(task_id, claim_token=claim["claim_token"])


def test_worker_clock_requires_timezone(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    _seed_task(ops_dir)
    queue = AgentTaskQueue(
        ops_dir,
        now=lambda: datetime(2026, 7, 15, 12, 0),
        token_factory=lambda: TOKEN,
    )
    with pytest.raises(WorkerTaskInvalid, match="timezone-aware"):
        queue.claim(host="codex")
