"""Durable cost ownership for every write-enabled MCP tool call."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from distill.config import DistillConfig
from distill.library import Library
from distill.mcp.server import capped_tracker, set_tracker_estimated_cost, write_tool
from distill.pipeline.costs import CostTracker, TokenUsage


def _config(tmp_path: Path, *, budget: float = 0.0) -> DistillConfig:
    return DistillConfig(
        xai_api_key="test-key",
        distill_output_dir=tmp_path / "library",
        distill_mcp_max_spend_per_call=budget,
    )


def _usage() -> TokenUsage:
    return TokenUsage(
        call_type="mcp-test",
        prompt_tokens=1_000_000,
        completion_tokens=1,
        model="grok-4.3",
    )


def _record_usage() -> None:
    capped_tracker().record(_usage())


def _cost_rows(config: DistillConfig) -> list[dict[str, object]]:
    path = config.library_dir / ".distill" / "cost_log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _record_tracker_usage(tracker: CostTracker) -> None:
    tracker.record(
        TokenUsage(
            call_type="mcp-test",
            prompt_tokens=1_000_000,
            completion_tokens=1,
            model="grok-4.3",
        )
    )


def test_write_tool_persists_registered_tracker_once_on_success(tmp_path: Path) -> None:
    config = _config(tmp_path)
    saves: list[tuple[Path, str, CostTracker]] = []

    @write_tool("cost_probe")
    def probe() -> str:
        _record_usage()
        return "ok"

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch(
            "distill.mcp.server.save_run_log",
            side_effect=lambda path, command, tracker, **kwargs: saves.append(
                (path, command, tracker)
            ),
        ),
    ):
        assert probe() == "ok"

    assert len(saves) == 1
    assert saves[0][0] == config.library_dir
    assert saves[0][1] == "cost_probe"
    assert len(saves[0][2].entries) == 1


def test_write_tool_persists_before_budget_response(tmp_path: Path) -> None:
    config = _config(tmp_path, budget=0.01)
    saves: list[CostTracker] = []

    @write_tool("cost_probe")
    def probe() -> str:
        _record_usage()
        return "unreachable"

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch(
            "distill.mcp.server.save_run_log",
            side_effect=lambda path, command, tracker, **kwargs: saves.append(tracker),
        ),
    ):
        payload = json.loads(probe())

    assert payload["status"] == "budget_exceeded"
    assert len(saves) == 1
    assert len(saves[0].entries) == 1


def test_write_tool_persists_before_generic_failure(tmp_path: Path) -> None:
    config = _config(tmp_path)
    saves: list[CostTracker] = []

    @write_tool("cost_probe")
    def probe() -> str:
        _record_usage()
        raise RuntimeError("provider failed")

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch(
            "distill.mcp.server.save_run_log",
            side_effect=lambda path, command, tracker, **kwargs: saves.append(tracker),
        ),
        pytest.raises(RuntimeError, match="provider failed"),
    ):
        probe()

    assert len(saves) == 1
    assert len(saves[0].entries) == 1


def test_async_write_tool_uses_the_same_durable_lifecycle(tmp_path: Path) -> None:
    config = _config(tmp_path)
    saves: list[CostTracker] = []

    @write_tool("async_cost_probe")
    async def probe() -> str:
        _record_usage()
        return "ok"

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch(
            "distill.mcp.server.save_run_log",
            side_effect=lambda path, command, tracker, **kwargs: saves.append(tracker),
        ),
    ):
        assert asyncio.run(probe()) == "ok"

    assert len(saves) == 1
    assert len(saves[0].entries) == 1


def test_async_cancellation_persists_usage_before_propagating(tmp_path: Path) -> None:
    config = _config(tmp_path)
    saves: list[CostTracker] = []

    @write_tool("cancelled_cost_probe")
    async def probe() -> str:
        _record_usage()
        raise asyncio.CancelledError

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch(
            "distill.mcp.server.save_run_log",
            side_effect=lambda path, command, tracker, **kwargs: saves.append(tracker),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        asyncio.run(probe())

    assert len(saves) == 1
    assert len(saves[0].entries) == 1


def test_write_tool_without_a_tracker_writes_no_cost_row(tmp_path: Path) -> None:
    config = _config(tmp_path)

    @write_tool("free_probe")
    def probe() -> str:
        return "ok"

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch("distill.mcp.server.save_run_log") as save,
    ):
        assert probe() == "ok"

    save.assert_not_called()


def test_write_tool_preserves_ledger_command_and_estimate(tmp_path: Path) -> None:
    config = _config(tmp_path)

    @write_tool("protocol_name", ledger_command="history-name")
    def probe() -> str:
        tracker = capped_tracker()
        set_tracker_estimated_cost(tracker, 1.25)
        return "ok"

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch("distill.mcp.server.save_run_log") as save,
    ):
        assert probe() == "ok"

    save.assert_called_once_with(
        config.library_dir,
        "history-name",
        save.call_args.args[2],
        estimated_cost=1.25,
    )


def test_success_fails_closed_when_ledger_write_fails(tmp_path: Path) -> None:
    config = _config(tmp_path)

    @write_tool("cost_probe")
    def probe() -> str:
        capped_tracker()
        return "must not escape"

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch("distill.mcp.server.save_run_log", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        probe()


def test_budget_outcome_survives_ledger_failure_and_reports_it(tmp_path: Path) -> None:
    config = _config(tmp_path, budget=0.01)

    @write_tool("cost_probe")
    def probe() -> str:
        _record_usage()
        return "unreachable"

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch("distill.mcp.server.save_run_log", side_effect=OSError("disk full")),
    ):
        payload = json.loads(probe())

    assert payload["status"] == "budget_exceeded"
    assert payload["accounting_status"] == "failed"
    assert "inspect local logs" in payload["accounting_error"]


def test_search_videos_success_persists_reranking_usage(tmp_path: Path) -> None:
    from distill.mcp.tools import discover as discover_tool

    config = _config(tmp_path)
    video = SimpleNamespace(
        video_id="v1",
        title="Grounded ranking",
        channel_name="Channel",
        upload_date="20260714",
        url="https://youtube.com/watch?v=v1",
        duration=120,
        view_count=10,
        channel_url="https://youtube.com/@channel",
    )
    ranked = SimpleNamespace(
        video=video,
        final_score=0.9,
        rationale="relevant",
        selected_by="llm",
    )

    def rank(query, candidates, cfg, tracker, *, limit):
        assert query == "query"
        assert candidates == [video]
        assert cfg is config
        assert limit == 1
        _record_tracker_usage(tracker)
        return [ranked]

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch.object(discover_tool, "_search_candidates", return_value=[video]),
        patch.object(discover_tool, "_rank_candidates", side_effect=rank),
    ):
        payload = json.loads(discover_tool.search_videos("query", limit=1))

    assert payload["results"][0]["title"] == "Grounded ranking"
    rows = _cost_rows(config)
    assert len(rows) == 1
    assert rows[0]["command"] == "search-videos"
    assert rows[0]["grok_calls"] == 1
    assert rows[0]["actual_cost"] > 0


def test_resynthesize_topic_success_persists_usage(tmp_path: Path) -> None:
    from distill.mcp.tools import reports as reports_tool

    config = _config(tmp_path)
    Library(config).add_channel("topic", "https://youtube.com/@channel", "Channel")

    def synthesize_channel(topic, channel, cfg, tracker=None):
        assert (topic, channel, cfg) == ("topic", "Channel", config)
        assert tracker is not None
        _record_tracker_usage(tracker)
        return "channel synthesis"

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch("distill.pipeline.synthesis.topic.synthesize_channel", synthesize_channel),
        patch("distill.pipeline.synthesis.topic.synthesize_topic", return_value="topic"),
        patch("distill.pipeline.synthesis.corpus.synthesize_corpus", return_value=""),
    ):
        payload = json.loads(reports_tool.resynthesize_topic("topic"))

    assert payload["results"][0] == {"channel": "Channel", "status": "ok"}
    rows = _cost_rows(config)
    assert len(rows) == 1
    assert rows[0]["command"] == "resynthesize-topic"
    assert rows[0]["grok_calls"] == 1


def test_report_failure_persists_usage_before_error_response(tmp_path: Path) -> None:
    from distill.mcp.tools import reports as reports_tool

    config = DistillConfig(
        gemini_api_key="test-key",
        distill_output_dir=tmp_path / "library",
    )

    def fail_report(*, tracker, **kwargs):
        _record_tracker_usage(tracker)
        raise RuntimeError("report failed")

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch(
            "distill.pipeline.report.accordion.run_accordion_research",
            side_effect=fail_report,
        ),
    ):
        payload = json.loads(reports_tool.generate_report("topic"))

    assert payload == {"error": "report failed"}
    rows = _cost_rows(config)
    assert len(rows) == 1
    assert rows[0]["command"] == "report"
    assert rows[0]["grok_calls"] == 1


def test_catch_up_budget_stop_persists_crossing_usage(tmp_path: Path) -> None:
    from distill.mcp.tools import watch as watch_tool

    config = _config(tmp_path, budget=0.01)
    lib = Library(config)
    lib.add_to_watchlist(
        "https://youtube.com/@channel",
        "Channel",
        topic="topic",
        days=7,
    )
    video = SimpleNamespace(video_id="v1", title="Video")

    def accrue_usage(*args, **kwargs) -> None:
        tracker = args[4]
        _record_tracker_usage(tracker)

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch.object(watch_tool, "load_config", return_value=config),
        patch.object(watch_tool, "library", return_value=lib),
        patch.object(watch_tool, "model_available", return_value=True),
        patch("distill.ingestors.youtube.discovery.discover_videos", return_value=[video]),
        patch("distill.cli_shared.ensure_channel_context", side_effect=accrue_usage),
    ):
        payload = json.loads(watch_tool.catch_up())

    assert payload["status"] == "budget_exceeded"
    rows = _cost_rows(config)
    assert len(rows) == 1
    assert rows[0]["command"] == "catch-up"
    assert rows[0]["grok_calls"] == 1
    assert rows[0]["actual_cost"] > config.distill_mcp_max_spend_per_call


def test_catch_up_provider_failure_persists_usage_before_propagating(tmp_path: Path) -> None:
    from distill.mcp.tools import watch as watch_tool

    config = _config(tmp_path)
    lib = Library(config)
    lib.add_to_watchlist(
        "https://youtube.com/@channel",
        "Channel",
        topic="topic",
        days=7,
    )
    video = SimpleNamespace(video_id="v1", title="Video")

    def accrue_usage(*args, **kwargs) -> None:
        tracker = args[4]
        _record_tracker_usage(tracker)

    with (
        patch("distill.mcp.server._config", return_value=config),
        patch.object(watch_tool, "load_config", return_value=config),
        patch.object(watch_tool, "library", return_value=lib),
        patch.object(watch_tool, "model_available", return_value=True),
        patch("distill.ingestors.youtube.discovery.discover_videos", return_value=[video]),
        patch("distill.cli_shared.ensure_channel_context", side_effect=accrue_usage),
        patch("distill.cli_shared.process_video", side_effect=RuntimeError("provider failed")),
        pytest.raises(RuntimeError, match="provider failed"),
    ):
        watch_tool.catch_up()

    rows = _cost_rows(config)
    assert len(rows) == 1
    assert rows[0]["command"] == "catch-up"
    assert rows[0]["grok_calls"] == 1


def test_mcp_cost_total_is_scoped_when_external_cost_is_unavailable() -> None:
    """MCP must not publish a confident total for runs with unknown external cost.

    ``project_cost_log_row`` dropped the writer's ``external_cost_status`` and
    ``actual_cost_scope`` markers, so a host-managed or remote-local run (which
    records 0 direct spend) was summed and reported as a clean, complete total --
    while ``distill costs`` correctly reported the narrower scope.
    """
    import json
    from pathlib import Path

    from distill.mcp.tools.costs import _cost_result  # pyright: ignore[reportPrivateUsage]
    from distill.pipeline.cost_history import CostLogScan, project_cost_log_row

    row = project_cost_log_row(
        {
            "timestamp": "2026-07-24T00:00:00Z",
            "command": "corpus",
            "actual_cost": 0.0,
            "external_cost_status": "unavailable",
            "actual_cost_scope": "distill-direct-charges",
        }
    )
    assert row["external_cost_status"] == "unavailable"
    assert row["actual_cost_scope"] == "distill-direct-charges"

    payload = json.loads(_cost_result([row], CostLogScan(), Path("cost_log.jsonl")))

    assert payload["status"] == "warning"
    assert payload["total_scope"] == "distill-direct-charges"
    assert payload["external_cost_status"] == "unavailable"
    assert "external cost is unavailable" in payload["message"]


def test_mcp_cost_total_stays_complete_for_fully_known_runs() -> None:
    """A run with fully known cost keeps the unqualified scope and ok status."""
    import json
    from pathlib import Path

    from distill.mcp.tools.costs import _cost_result  # pyright: ignore[reportPrivateUsage]
    from distill.pipeline.cost_history import CostLogScan, project_cost_log_row

    row = project_cost_log_row(
        {"timestamp": "2026-07-24T00:00:00Z", "command": "papers", "actual_cost": 1.25}
    )
    payload = json.loads(_cost_result([row], CostLogScan(), Path("cost_log.jsonl")))

    assert payload["status"] == "ok"
    assert payload["total_scope"] == "returned_valid_runs"
    assert payload["external_cost_status"] == "complete"
    assert payload["total_cost"] == 1.25
