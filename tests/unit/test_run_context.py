from __future__ import annotations

import asyncio
import json
import math
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from distill.llm.router import LLM_Response, RouterConfig, call
from distill.llm.run_context import (
    current_run_id,
    mark_current_run_outcome,
    phase_scope,
    run_scope,
    update_current_run,
    write_phase_record,
)
from distill.pipeline.costs import CostTracker, TokenUsage, save_run_log


def _rows(ops_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (ops_dir / "phase_telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_run_and_nested_phase_share_nonempty_id(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"

    with run_scope(invocation_type="cli", command="cli") as context:
        update_current_run(command="papers", ops_dir=ops_dir)
        assert current_run_id() == context.run_id
        with phase_scope(
            "acquire",
            wait_class="acquisition",
            artifact_count=2,
            byte_count=128,
        ):
            pass

    rows = _rows(ops_dir)
    assert len(rows) == 2
    assert {str(row["run_id"]) for row in rows} == {context.run_id}
    assert uuid.UUID(context.run_id).version == 4
    assert rows[0]["phase"] == "acquire"
    assert rows[0]["artifact_count"] == 2
    assert rows[0]["byte_count"] == 128
    assert rows[0]["wait_class"] == "acquisition"
    assert rows[1]["phase"] == "command"
    assert all(float(row["elapsed_seconds"]) >= 0 for row in rows)
    assert all(float(row["cpu_seconds"]) >= 0 for row in rows)
    assert current_run_id() == ""


def test_phase_error_records_type_and_resets_context(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"

    with (
        pytest.raises(ValueError, match="private detail"),
        run_scope(invocation_type="cli", command="audit", ops_dir=ops_dir),
        phase_scope("scan", wait_class="filesystem"),
    ):
        raise ValueError("private detail")

    rows = _rows(ops_dir)
    assert [row["outcome"] for row in rows] == ["error", "error"]
    assert [row["error_type"] for row in rows] == ["ValueError", "ValueError"]
    assert "private detail" not in json.dumps(rows)
    assert current_run_id() == ""


def test_structured_outcome_overrides_clean_return(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"

    with run_scope(invocation_type="mcp", command="ingest", ops_dir=ops_dir):
        mark_current_run_outcome("refused")

    assert _rows(ops_dir)[0]["outcome"] == "refused"


def test_explicit_run_id_and_zero_exit_are_success(tmp_path: Path) -> None:
    ops_dir = tmp_path / "ops"

    with (
        pytest.raises(SystemExit) as raised,
        run_scope(
            invocation_type="cli",
            command="help",
            ops_dir=ops_dir,
            run_id="fixed-run",
        ),
    ):
        raise SystemExit(0)

    assert raised.value.code == 0
    row = _rows(ops_dir)[0]
    assert row["run_id"] == "fixed-run"
    assert row["outcome"] == "success"


def test_async_run_contexts_are_isolated(tmp_path: Path) -> None:
    async def worker(name: str) -> str:
        with run_scope(
            invocation_type="mcp",
            command=name,
            ops_dir=tmp_path / name,
        ) as context:
            await asyncio.sleep(0)
            assert current_run_id() == context.run_id
            return context.run_id

    async def collect() -> tuple[str, str]:
        first, second = await asyncio.gather(worker("first"), worker("second"))
        return first, second

    first, second = asyncio.run(collect())
    assert first != second
    assert _rows(tmp_path / "first")[0]["run_id"] == first
    assert _rows(tmp_path / "second")[0]["run_id"] == second


def test_telemetry_write_failure_is_nonfatal(tmp_path: Path) -> None:
    not_a_directory = tmp_path / "occupied"
    not_a_directory.write_text("file", encoding="utf-8")

    with run_scope(
        invocation_type="cli",
        command="audit",
        ops_dir=not_a_directory,
    ):
        pass

    # Exercise the public fail-soft writer directly with an otherwise valid row.
    # The record is taken from a successful run so the test does not duplicate
    # the schema construction here.
    good_ops = tmp_path / "good"
    with run_scope(invocation_type="cli", command="audit", ops_dir=good_ops):
        pass
    from distill.llm.run_context import PhaseTelemetryRecord

    row = PhaseTelemetryRecord(
        run_id="run",
        invocation_type="cli",
        command="audit",
        phase="scan",
        elapsed_seconds=0.1,
        cpu_seconds=0.1,
        outcome="success",
        wait_class="filesystem",
    )
    write_phase_record(not_a_directory, row)


def test_phase_writer_isolates_an_unterminated_tail(tmp_path: Path) -> None:
    from distill.llm.run_context import PhaseTelemetryRecord

    ops_dir = tmp_path / ".distill"
    ops_dir.mkdir()
    path = ops_dir / "phase_telemetry.jsonl"
    path.write_bytes(b'{"torn":')
    write_phase_record(
        ops_dir,
        PhaseTelemetryRecord(
            run_id="run",
            invocation_type="cli",
            command="audit",
            phase="scan",
            elapsed_seconds=0.1,
            cpu_seconds=0.1,
            outcome="success",
            wait_class="filesystem",
        ),
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == '{"torn":'
    assert json.loads(lines[1])["run_id"] == "run"


def test_phase_writer_drops_nonfinite_evidence_without_breaking_run(tmp_path: Path) -> None:
    from distill.llm.run_context import PhaseTelemetryRecord

    ops_dir = tmp_path / ".distill"
    write_phase_record(
        ops_dir,
        PhaseTelemetryRecord(
            run_id="run",
            invocation_type="cli",
            command="audit",
            phase="scan",
            elapsed_seconds=math.nan,
            cpu_seconds=0.1,
            outcome="success",
            wait_class="filesystem",
        ),
    )

    assert not (ops_dir / "phase_telemetry.jsonl").exists()


def test_command_phase_provider_and_cost_rows_share_run_id(tmp_path: Path) -> None:
    ops_dir = tmp_path / ".distill"
    provider = AsyncMock()
    provider.call.return_value = LLM_Response(
        text="analysis",
        input_tokens=12,
        output_tokens=7,
        model="grok-4.3",
    )
    config = RouterConfig(xai_api_key="test", ops_dir=str(ops_dir))

    with run_scope(
        invocation_type="cli",
        command="paper",
        ops_dir=ops_dir,
    ) as context:
        tracker = CostTracker()
        with (
            phase_scope("analysis", wait_class="provider"),
            patch("distill.llm.router._get_provider", return_value=provider),
        ):
            response = call(config, "analysis", "not persisted")
        tracker.record(TokenUsage.from_response(response, call_type="analysis"))
        save_run_log(tmp_path, "paper", tracker)

    provider_row = json.loads(
        (ops_dir / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    cost_row = json.loads((ops_dir / "cost_log.jsonl").read_text(encoding="utf-8").splitlines()[0])
    phase_rows = _rows(ops_dir)

    assert provider_row["run_id"] == context.run_id
    assert cost_row["run_id"] == context.run_id
    assert {row["run_id"] for row in phase_rows} == {context.run_id}
    assert "not persisted" not in json.dumps([provider_row, cost_row, *phase_rows])
