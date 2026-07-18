"""CLI tests for the host-session worker surface."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from distill import cli
from distill.commands import root as root_commands
from distill.commands import worker as worker_commands
from distill.config import DistillConfig
from distill.llm.providers.agent import AgentProvider
from distill.llm.router import PendingTaskError

runner = CliRunner()


@pytest.fixture
def worker_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistillConfig:
    config = DistillConfig(distill_output_dir=tmp_path / "library")
    monkeypatch.setattr(worker_commands, "get_config", lambda: config)
    monkeypatch.setattr(root_commands, "get_config", lambda: config)
    return config


def _seed(config: DistillConfig, prompt: str = "Write markdown") -> tuple[str, Path]:
    ops_dir = config.library_dir / ".distill"
    provider = AgentProvider(str(ops_dir))
    with pytest.raises(PendingTaskError) as raised:
        asyncio.run(provider.call("agent", prompt, call_type="analysis", max_tokens=32))
    task_path = Path(raised.value.task_path)
    task_id = json.loads(task_path.read_text(encoding="utf-8"))["task_id"]
    return task_id, task_path


def _data(output: str) -> dict[str, object]:
    envelope = json.loads(output)
    assert envelope["status"] == "ok"
    return envelope["data"]


def test_worker_empty_list_and_claim_are_clean_noops(worker_config: DistillConfig) -> None:
    listed = runner.invoke(cli.app, ["--json", "worker", "list"])
    assert listed.exit_code == 0
    assert _data(listed.output) == {"tasks": [], "count": 0}

    claimed = runner.invoke(cli.app, ["--json", "worker", "claim", "--host", "codex"])
    assert claimed.exit_code == 0
    assert _data(claimed.output) == {"claimed": False, "reason": "no_pending_tasks"}

    human = runner.invoke(cli.app, ["worker", "list"])
    assert human.exit_code == 0
    assert "No deferred worker tasks" in human.output

    human_claim = runner.invoke(cli.app, ["worker", "claim", "--host", "codex"])
    assert human_claim.exit_code == 0
    assert "No eligible unclaimed worker tasks" in human_claim.output


def test_worker_cli_claim_list_submit_flow(worker_config: DistillConfig) -> None:
    task_id, _task_path = _seed(worker_config)

    human_list = runner.invoke(cli.app, ["worker", "list"])
    assert human_list.exit_code == 0
    assert task_id in human_list.output
    assert "pending" in human_list.output

    claimed = runner.invoke(
        cli.app,
        [
            "--json",
            "worker",
            "claim",
            "--host",
            "codex",
            "--worker-id",
            "cli-test",
        ],
    )
    assert claimed.exit_code == 0
    claim = _data(claimed.output)
    assert claim["claimed"] is True
    assert claim["submit_command"] == [
        "distill",
        "--json",
        "worker",
        "submit",
        task_id,
    ]
    assert claim["claim_token_env"] == "DISTILL_WORKER_CLAIM_TOKEN"
    assert str(claim["claim_token"]) not in json.dumps(claim["submit_command"])
    Path(str(claim["result_path"])).write_text("# Complete\n", encoding="utf-8")

    submitted = runner.invoke(
        cli.app,
        [
            "--json",
            "worker",
            "submit",
            task_id,
            "--model",
            "gpt-test",
            "--input-tokens",
            "10",
            "--output-tokens",
            "3",
        ],
        env={"DISTILL_WORKER_CLAIM_TOKEN": str(claim["claim_token"])},
    )
    assert submitted.exit_code == 0
    submission = _data(submitted.output)
    assert submission["submitted"] is True
    assert submission["model"] == "gpt-test"

    completed = runner.invoke(cli.app, ["--json", "worker", "list"])
    rows = _data(completed.output)["tasks"]
    assert rows[0]["status"] == "completed"


def test_worker_human_claim_submit_and_abandon_flow(worker_config: DistillConfig) -> None:
    task_id, _task_path = _seed(worker_config, "First human task")
    claimed = runner.invoke(cli.app, ["worker", "claim", "--host", "codex"])
    assert claimed.exit_code == 0
    assert f"Claimed task {task_id}" in claimed.output
    assert "Billing is host-managed" in claimed.output
    assert "Distill has not proved this session is no-metered" in claimed.output
    assert "DISTILL_WORKER_CLAIM_TOKEN" in claimed.output
    assert "process arguments" in claimed.output
    token_match = re.search(r"Claim token: (\S+)", claimed.output)
    assert token_match is not None
    token = token_match.group(1)
    workspaces = list((worker_config.library_dir / ".distill" / "tasks" / "work").iterdir())
    assert len(workspaces) == 1
    (workspaces[0] / "result.md").write_text("Human result", encoding="utf-8")

    submitted = runner.invoke(
        cli.app,
        ["worker", "submit", task_id],
        env={"DISTILL_WORKER_CLAIM_TOKEN": token},
    )
    assert submitted.exit_code == 0
    assert f"Submitted task {task_id}" in submitted.output
    assert "Published result:" in submitted.output
    assert "Receipt:" in submitted.output

    second_id, _second_path = _seed(worker_config, "Second human task")
    second = runner.invoke(cli.app, ["--json", "worker", "claim", "--host", "claude"])
    second_claim = _data(second.output)
    abandoned = runner.invoke(
        cli.app,
        [
            "worker",
            "abandon",
            second_id,
            "--reason",
            "manual stop",
        ],
        env={"DISTILL_WORKER_CLAIM_TOKEN": str(second_claim["claim_token"])},
    )
    assert abandoned.exit_code == 0
    assert f"Released task {second_id}" in abandoned.output
    assert "Receipt:" in abandoned.output


def test_worker_cli_abandon_and_error_envelopes(worker_config: DistillConfig) -> None:
    task_id, _task_path = _seed(worker_config)
    claimed = runner.invoke(
        cli.app,
        ["--json", "worker", "claim", "--host", "claude"],
    )
    claim = _data(claimed.output)

    wrong = runner.invoke(
        cli.app,
        [
            "--json",
            "worker",
            "abandon",
            task_id,
            "--claim-token",
            "wrong-token-value-123456789",
            "--reason",
            "test",
        ],
    )
    assert wrong.exit_code == 1
    wrong_envelope = json.loads(wrong.output)
    assert wrong_envelope["status"] == "error"
    assert wrong_envelope["data"]["reason"] == "worker_task_conflict"

    abandoned = runner.invoke(
        cli.app,
        [
            "--json",
            "worker",
            "abandon",
            task_id,
            "--claim-token",
            str(claim["claim_token"]),
            "--reason",
            "quota exhausted",
        ],
    )
    assert abandoned.exit_code == 0
    assert _data(abandoned.output)["abandoned"] is True

    missing = runner.invoke(
        cli.app,
        [
            "--json",
            "worker",
            "submit",
            "000000000000",
            "--claim-token",
            "valid-token-value-1234567890",
        ],
    )
    assert missing.exit_code == 5
    assert json.loads(missing.output)["data"]["reason"] == "worker_task_not_found"


def test_worker_release_expired_requires_explicit_yes(worker_config: DistillConfig) -> None:
    task_id, _task_path = _seed(worker_config)
    result = runner.invoke(
        cli.app,
        ["--json", "worker", "release-expired", task_id],
    )
    assert result.exit_code == 0
    assert _data(result.output) == {
        "released": False,
        "approved": False,
        "task_id": task_id,
        "next": f"distill worker release-expired {task_id} --yes",
    }

    human = runner.invoke(cli.app, ["worker", "release-expired", task_id])
    assert human.exit_code == 0
    assert "No claim was released" in human.output


def test_worker_release_expired_executes_and_lists_expiry(worker_config: DistillConfig) -> None:
    task_id, task_path = _seed(worker_config)
    claimed = runner.invoke(cli.app, ["--json", "worker", "claim", "--host", "codex"])
    assert claimed.exit_code == 0
    claim_path = task_path.with_suffix(".claim")
    payload = json.loads(claim_path.read_text(encoding="utf-8"))
    payload["claimed_at"] = "2020-01-01T00:00:00+00:00"
    payload["lease_expires_at"] = "2020-01-01T00:01:00+00:00"
    claim_path.write_text(json.dumps(payload), encoding="utf-8")

    listed = runner.invoke(cli.app, ["worker", "list"])
    assert listed.exit_code == 0
    assert "expired" in listed.output
    assert "2020-01-01T00:01:00+00:00" in listed.output

    released = runner.invoke(
        cli.app,
        ["--json", "worker", "release-expired", task_id, "--yes"],
    )
    assert released.exit_code == 0
    assert _data(released.output)["released"] is True

    claimed_again = runner.invoke(
        cli.app,
        ["--json", "worker", "claim", "--host", "claude"],
    )
    assert claimed_again.exit_code == 0
    payload = json.loads(claim_path.read_text(encoding="utf-8"))
    payload["claimed_at"] = "2020-01-02T00:00:00+00:00"
    payload["lease_expires_at"] = "2020-01-02T00:01:00+00:00"
    claim_path.write_text(json.dumps(payload), encoding="utf-8")
    human_release = runner.invoke(
        cli.app,
        ["worker", "release-expired", task_id, "--yes"],
    )
    assert human_release.exit_code == 0
    assert f"Released expired claim for task {task_id}" in human_release.output
    assert "Receipt:" in human_release.output


def test_worker_invalid_and_base_errors_have_stable_exit_codes(
    worker_config: DistillConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = runner.invoke(
        cli.app,
        [
            "--json",
            "worker",
            "submit",
            "bad",
            "--claim-token",
            "valid-token-value-1234567890",
        ],
    )
    assert invalid.exit_code == 3
    assert json.loads(invalid.output)["data"]["reason"] == "worker_task_invalid"

    human_missing = runner.invoke(
        cli.app,
        [
            "worker",
            "submit",
            "000000000000",
            "--claim-token",
            "valid-token-value-1234567890",
        ],
    )
    assert human_missing.exit_code == 5
    assert "no pending task directory exists" in human_missing.output

    monkeypatch.setattr(worker_commands, "json_mode_active", lambda: False)
    with pytest.raises(typer.Exit) as raised:
        worker_commands._exit_worker_error(worker_commands.WorkerTaskError("base failure"))
    assert raised.value.exit_code == 1


def test_worker_help_is_registered(worker_config: DistillConfig) -> None:
    result = runner.invoke(cli.app, ["worker", "--help"])
    assert result.exit_code == 0
    assert "Claim and complete deferred tasks" in result.output
    assert "release-expired" in result.output
