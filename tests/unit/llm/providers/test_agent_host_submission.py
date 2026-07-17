"""Safety tests for AgentProvider host-session receipt replay."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from distill.llm.providers import _agent_submission as agent_submission_mod
from distill.llm.providers._agent_files import validated_task_root
from distill.llm.providers.agent import AgentProvider

TASK_ID = "0123456789ab"
PROMPT_HASH = "prompt-hash"
RESULT = "Host result\n"


def _payload() -> dict[str, object]:
    result_bytes = RESULT.encode()
    return {
        "schema_version": "agent-worker-submission.v1",
        "protocol": "agent-worker.v1",
        "task_id": TASK_ID,
        "workload": "analysis",
        "prompt_hash": PROMPT_HASH,
        "claim_token_hash": "a" * 64,
        "host": "codex",
        "worker_id": "interactive",
        "model": "gpt-host",
        "claimed_at": "2026-07-15T12:00:00+00:00",
        "submitted_at": "2026-07-15T12:00:01+00:00",
        "elapsed_ms": 1000,
        "result_sha256": f"sha256:{hashlib.sha256(result_bytes).hexdigest()}",
        "result_bytes": len(result_bytes),
        "usage": {
            "input_tokens": 10,
            "output_tokens": 3,
            "source": "host-reported",
        },
        "billing": {
            "class": "host-managed",
            "no_metered_proven": False,
            "proof": "unavailable",
        },
        "files_read": ["prompt.md", "task.json"],
        "files_written": ["result.md"],
        "published_result": f"analysis_{TASK_ID}_result.md",
    }


def _receipt(tmp_path: Path) -> tuple[AgentProvider, Path, tuple[Path, tuple[int, int]]]:
    ops_dir = tmp_path / "ops"
    pending = ops_dir / "tasks" / "pending"
    pending.mkdir(parents=True)
    task_path = pending / f"analysis_{TASK_ID}.json"
    task_path.write_text("{}", encoding="utf-8")
    task_path.with_suffix(".submission").write_text(
        json.dumps(_payload()),
        encoding="utf-8",
    )
    bound = validated_task_root(pending)
    assert bound is not None
    return AgentProvider(str(ops_dir)), task_path, bound


def test_host_submission_can_bind_its_current_pending_root(tmp_path: Path) -> None:
    provider, task_path, _bound = _receipt(tmp_path)

    receipt = provider._read_host_submission(task_path, RESULT, PROMPT_HASH)

    assert receipt is not None
    assert receipt.host == "codex"


def test_host_submission_rejects_missing_or_changed_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, task_path, bound = _receipt(tmp_path)
    monkeypatch.setattr(provider, "_task_root", lambda *_args: None)
    with pytest.raises(ValueError, match="root is unavailable"):
        provider._read_host_submission(task_path, RESULT, PROMPT_HASH)

    monkeypatch.setattr(agent_submission_mod, "task_root_is_unchanged", lambda *_args: False)
    with pytest.raises(ValueError, match="root changed"):
        provider._read_host_submission(
            task_path,
            RESULT,
            PROMPT_HASH,
            bound_root=bound,
        )


def test_host_submission_rejects_outside_or_unreadable_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _task_path, bound = _receipt(tmp_path)
    outside = tmp_path / f"analysis_{TASK_ID}.json"
    outside.write_text("{}", encoding="utf-8")
    outside.with_suffix(".submission").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="outside the pending root"):
        provider._read_host_submission(
            outside,
            RESULT,
            PROMPT_HASH,
            bound_root=bound,
        )

    monkeypatch.setattr(agent_submission_mod, "read_task_text", lambda *_args, **_kwargs: None)
    with pytest.raises(ValueError, match="unsafe or unreadable"):
        provider._read_host_submission(
            bound[0] / f"analysis_{TASK_ID}.json",
            RESULT,
            PROMPT_HASH,
            bound_root=bound,
        )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not-json", "not valid JSON"),
        ("[]", "must be a JSON object"),
    ],
)
def test_host_submission_rejects_malformed_json(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    provider, task_path, bound = _receipt(tmp_path)
    task_path.with_suffix(".submission").write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        provider._read_host_submission(
            task_path,
            RESULT,
            PROMPT_HASH,
            bound_root=bound,
        )


def test_host_submission_wraps_receipt_inspection_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, task_path, _bound = _receipt(tmp_path)
    receipt_path = task_path.with_suffix(".submission")
    real_lstat = Path.lstat

    def fail_receipt_lstat(path: Path):
        if path == receipt_path:
            raise OSError("inspection failed")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_receipt_lstat)
    with pytest.raises(ValueError, match="cannot be inspected"):
        provider._read_host_submission(task_path, RESULT, PROMPT_HASH)
