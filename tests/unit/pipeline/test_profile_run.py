from __future__ import annotations

import json
import subprocess

from distill.pipeline.profile_preview import ProfilePreviewCandidate, ProfilePreviewResult
from distill.pipeline.profile_run import (
    CommandExecution,
    _coerce_text,
    _library_relative,
    execute_command,
    profile_run_state_path,
    run_profile_preview,
)


def _preview() -> ProfilePreviewResult:
    return ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="no-metered",
        ordering="test order",
        fresh_item_limit=3,
        candidates=[
            ProfilePreviewCandidate(
                kind="youtube_video",
                title="Exact video",
                url="https://youtube.com/watch?v=v1",
                source="@Example",
                source_label="Example",
                identity="youtube:v1",
                command=[
                    "distill",
                    "--cost-mode",
                    "no-metered",
                    "video",
                    "https://youtube.com/watch?v=v1",
                    "--topic",
                    "agent-loops",
                ],
            ),
            ProfilePreviewCandidate(
                kind="query",
                title="agent loops",
                url="",
                source="agent loops",
                source_label="saved query",
                identity="query:agent loops",
                command=[
                    "distill",
                    "--cost-mode",
                    "no-metered",
                    "latest",
                    "agent loops",
                    "--topic",
                    "agent-loops",
                    "--preview",
                ],
            ),
        ],
    )


def test_profile_run_without_approval_only_returns_plan(tmp_path):
    calls: list[list[str]] = []

    result = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=False,
        executor=lambda command, _timeout: calls.append(command) or CommandExecution(0, 0.1),
    )

    assert result.health_status == "approval_required"
    assert result.pending_count == 2
    assert calls == []
    assert not profile_run_state_path(tmp_path, "agent-loops").exists()
    action = result.to_dict()["next_actions"][0]
    assert action["id"] == "profile.agent.loops.run"
    assert action["kind"] == "profile_run"
    assert action["approval"] == "operator"
    assert action["estimated_cost_usd"] == 0.0
    assert action["command"] == [
        "distill",
        "--cost-mode",
        "no-metered",
        "profile",
        "run",
        "agent-loops",
        "--yes",
    ]
    assert action["loop"]["acceptance_metric"] == "verifier_passed"
    assert action["verifier"]["command"] == [
        "distill",
        "--cost-mode",
        "no-metered",
        "--json",
        "profile",
        "run",
        "agent-loops",
    ]


def test_profile_run_marks_exact_items_complete_but_keeps_seeds_repeatable(tmp_path):
    calls: list[list[str]] = []

    def executor(command: list[str], _timeout: int) -> CommandExecution:
        calls.append(command)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    first = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert first.succeeded_count == 2
    assert first.health_status == "ok"
    assert first.to_dict()["pending_count"] == 0
    assert len(calls) == 2

    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "youtube_video:youtube:v1" in state["completed"]
    assert "query:query:agent loops" not in state["completed"]
    cost_row = json.loads((tmp_path / ".distill" / "cost_log.jsonl").read_text(encoding="utf-8"))
    assert cost_row["command"] == "profile-run"
    assert cost_row["actual_cost"] == 0.0
    assert cost_row["metadata"]["profile"] == "agent-loops"
    assert cost_row["metadata"]["succeeded_count"] == "2"

    second = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=False,
        executor=executor,
    )

    statuses = {command.key: command.status for command in second.commands}
    assert statuses["youtube_video:youtube:v1"] == "skipped"
    assert statuses["query:query:agent loops"] == "pending"


def test_profile_run_approved_run_skips_completed_exact_items(tmp_path):
    calls: list[list[str]] = []

    def executor(command: list[str], _timeout: int) -> CommandExecution:
        calls.append(command)
        return CommandExecution(exit_code=0, elapsed_seconds=0.1)

    run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )
    calls.clear()

    result = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    statuses = {command.key: command.status for command in result.commands}
    assert statuses["youtube_video:youtube:v1"] == "skipped"
    assert statuses["query:query:agent loops"] == "succeeded"
    assert len(calls) == 1


def test_profile_run_with_only_completed_items_is_complete(tmp_path):
    preview = ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="no-metered",
        ordering="test order",
        fresh_item_limit=1,
        candidates=[_preview().candidates[0]],
    )
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schema_version": "profile-run-state.v1",
                "completed": {"youtube_video:youtube:v1": {"exit_code": 0}},
            }
        ),
        encoding="utf-8",
    )

    result = run_profile_preview(preview, library_dir=tmp_path, approved=False)

    assert result.selected_count == 0
    assert result.health_status == "complete"
    assert result.to_dict()["next_actions"] == []


def test_profile_run_failure_is_recorded_without_completion(tmp_path):
    def executor(_command: list[str], _timeout: int) -> CommandExecution:
        return CommandExecution(exit_code=2, elapsed_seconds=0.1, stderr_tail="failed")

    result = run_profile_preview(
        _preview(),
        library_dir=tmp_path,
        approved=True,
        executor=executor,
    )

    assert result.failed_count == 2
    assert result.health_status == "failed"
    action = result.to_dict()["next_actions"][0]
    assert action["id"] == "profile.agent.loops.retry"
    assert action["kind"] == "profile_run_retry"
    assert action["severity"] == "warning"
    assert action["loop"]["max_attempts"] == 3

    state = json.loads(profile_run_state_path(tmp_path, "agent-loops").read_text(encoding="utf-8"))
    assert state["completed"] == {}
    assert "youtube_video:youtube:v1" in state["last_failure"]
    assert state["attempts"][0]["execution"]["stderr_tail"] == "failed"


def test_profile_run_refuses_unparseable_state(tmp_path):
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{", encoding="utf-8")

    try:
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)
    except ValueError as exc:
        assert "not parseable" in str(exc)
    else:
        raise AssertionError("Expected unparseable state to fail closed")


def test_profile_run_refuses_non_object_and_wrong_schema_state(tmp_path):
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)

    state_path.write_text("[]", encoding="utf-8")
    try:
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)
    except ValueError as exc:
        assert "must be a JSON object" in str(exc)
    else:
        raise AssertionError("Expected non-object state to fail closed")

    state_path.write_text('{"schema_version": "unknown"}', encoding="utf-8")
    try:
        run_profile_preview(_preview(), library_dir=tmp_path, approved=False)
    except ValueError as exc:
        assert "Unsupported profile run state schema" in str(exc)
    else:
        raise AssertionError("Expected wrong schema to fail closed")


def test_profile_run_defaults_missing_state_collections_and_completed_shape(tmp_path):
    state_path = profile_run_state_path(tmp_path, "agent-loops")
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"schema_version": "profile-run-state.v1", "completed": []}),
        encoding="utf-8",
    )

    result = run_profile_preview(_preview(), library_dir=tmp_path, approved=False)

    assert result.selected_count == 2
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["completed"] == []


def test_profile_run_auto_cost_mode_and_command_hash_keys(tmp_path):
    preview = ProfilePreviewResult(
        schema_version="profile-preview.v1",
        profile="agent-loops",
        topic="agent-loops",
        cost_mode="auto",
        ordering="test order",
        fresh_item_limit=1,
        candidates=[
            ProfilePreviewCandidate(
                kind="domain",
                title="example.com",
                url="https://example.com",
                source="example.com",
                source_label="example.com",
                identity="",
                command=["distill", "site", "https://example.com", "--topic", "agent-loops"],
            )
        ],
    )

    result = run_profile_preview(
        preview,
        library_dir=tmp_path,
        approved=False,
        profile_ref="profiles/agent-loops.yaml",
    )

    action = result.to_dict()["next_actions"][0]
    assert result.commands[0].key.startswith("domain:command:")
    assert action["approval"] == "spend"
    assert action["estimated_cost_usd"] is None
    assert action["command"] == ["distill", "profile", "run", "profiles/agent-loops.yaml", "--yes"]
    assert action["verifier"]["command"] == [
        "distill",
        "--json",
        "profile",
        "run",
        "profiles/agent-loops.yaml",
    ]


def test_execute_command_normalizes_subprocess_outcomes(monkeypatch):
    def completed(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            3,
            stdout="x" * 4105,
            stderr="err",
        )

    monkeypatch.setattr("distill.pipeline.profile_run.subprocess.run", completed)
    failed = execute_command(["distill"], timeout_seconds=7)
    assert failed.exit_code == 3
    assert len(failed.stdout_tail) == 4000
    assert failed.stderr_tail == "err"

    def missing(_command, **_kwargs):
        raise FileNotFoundError("missing executable")

    monkeypatch.setattr("distill.pipeline.profile_run.subprocess.run", missing)
    missing_result = execute_command(["missing"], timeout_seconds=7)
    assert missing_result.exit_code == 127
    assert "missing executable" in missing_result.stderr_tail

    def timed_out(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, 7, output=b"partial")

    monkeypatch.setattr("distill.pipeline.profile_run.subprocess.run", timed_out)
    timeout = execute_command(["slow"], timeout_seconds=7)
    assert timeout.exit_code == 124
    assert timeout.stdout_tail == "partial"
    assert timeout.stderr_tail == "Timed out after 7s"
    assert timeout.timed_out is True


def test_profile_run_pure_fallback_helpers(tmp_path):
    assert _library_relative(tmp_path / "outside.json", tmp_path / "library") == str(
        tmp_path / "outside.json"
    )
    assert _coerce_text("already text") == "already text"
