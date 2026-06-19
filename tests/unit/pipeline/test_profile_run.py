from __future__ import annotations

import json

from distill.pipeline.profile_preview import ProfilePreviewCandidate, ProfilePreviewResult
from distill.pipeline.profile_run import (
    CommandExecution,
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
