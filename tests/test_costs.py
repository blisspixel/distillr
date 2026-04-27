"""Tests for distill.costs."""

import json

from distill.costs import CostTracker, TokenUsage, estimate_run_cost, save_run_log


def test_cost_tracker_summary_and_formatting():
    tracker = CostTracker()
    tracker.record(
        TokenUsage(
            prompt_tokens=1000,
            completion_tokens=500,
            model="grok-4-1-fast-reasoning",
            call_type="pass1",
        )
    )
    tracker.record_gemini_query()

    summary = tracker.summary_dict()

    assert summary["grok_calls"] == 1
    assert summary["gemini_queries"] == 1
    assert tracker.format_cost().startswith("$")


def test_save_run_log_writes_breakdown(tmp_path):
    tracker = CostTracker()
    tracker.record(
        TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            model="grok-4-1-fast-reasoning",
            call_type="pass1",
        )
    )
    tracker.record(
        TokenUsage(
            prompt_tokens=40,
            completion_tokens=20,
            model="grok-4-1-fast-reasoning",
            call_type="pass1",
        )
    )

    save_run_log(
        tmp_path,
        "learn",
        tracker,
        estimated_cost=0.12,
        full_videos=2,
        shorts=1,
        elapsed_seconds=12.3,
    )

    entry = json.loads((tmp_path / "cost_log.jsonl").read_text(encoding="utf-8").strip())
    assert entry["command"] == "learn"
    assert entry["by_call_type"]["pass1"]["calls"] == 2


def test_estimate_run_cost_includes_accordion():
    text = estimate_run_cost(2, 1, accordion=True)

    assert "Accordion" in text
    assert "$" in text


def test_cost_tracker_uses_model_specific_pricing():
    tracker = CostTracker()
    tracker.record(
        TokenUsage(
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            model="grok-4.20",
            call_type="site_page",
        )
    )

    assert tracker.total_grok_cost == 8.0
    assert tracker.summary_dict()["by_model"]["grok-4.20"]["calls"] == 1


def test_save_run_log_preview_suffixes_command(tmp_path):
    """Preview-only runs land in cost_log.jsonl as `<command>_preview` so they're
    visible separately from ingest spend in `distill costs`."""
    tracker = CostTracker()
    tracker.record(
        TokenUsage(
            prompt_tokens=200,
            completion_tokens=80,
            model="grok-4-1-fast-reasoning",
            call_type="discover_plan",
        )
    )

    save_run_log(tmp_path, "discover", tracker, preview=True)

    entry = json.loads((tmp_path / "cost_log.jsonl").read_text(encoding="utf-8").strip())
    assert entry["command"] == "discover_preview"


def test_save_run_log_default_does_not_suffix(tmp_path):
    """Without preview=True, the command name is recorded verbatim — preserves
    backward compatibility for all existing ingest-path call sites."""
    tracker = CostTracker()
    tracker.record(
        TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            model="grok-4-1-fast-reasoning",
            call_type="paper",
        )
    )

    save_run_log(tmp_path, "papers", tracker)

    entry = json.loads((tmp_path / "cost_log.jsonl").read_text(encoding="utf-8").strip())
    assert entry["command"] == "papers"
