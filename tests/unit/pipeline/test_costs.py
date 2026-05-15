"""Tests for distill.costs."""

import json

from distill.llm.cost import deep_research_query_cost
from distill.pipeline.costs import (
    ACCORDION_GROK_ESTIMATE,
    CostTracker,
    TokenUsage,
    estimate_run_cost,
    report_deep_research_estimate,
    save_run_log,
)


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

    entry = json.loads(
        (tmp_path / ".distill" / "cost_log.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["command"] == "learn"
    assert entry["by_call_type"]["pass1"]["calls"] == 2


def test_estimate_run_cost_includes_accordion():
    text = estimate_run_cost(2, 1, accordion=True)

    assert "Accordion" in text
    assert f"${report_deep_research_estimate():.2f}" in text
    assert f"Gemini ${deep_research_query_cost():.2f}" in text


def test_report_deep_research_estimate_uses_central_pricing():
    assert report_deep_research_estimate() == (deep_research_query_cost() + ACCORDION_GROK_ESTIMATE)


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

    entry = json.loads(
        (tmp_path / ".distill" / "cost_log.jsonl").read_text(encoding="utf-8").strip()
    )
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

    entry = json.loads(
        (tmp_path / ".distill" / "cost_log.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["command"] == "papers"


# ---------------------------------------------------------------------------
# Task 17.3 — cost delegation and ops_dir tests
# ---------------------------------------------------------------------------


def test_costs_pricing_delegates_to_llm_cost():
    """distill/costs.py pricing lookups match distill/llm/cost.py pricing."""
    from distill.llm.cost import PRICING as LLM_PRICING
    from distill.llm.cost import get_pricing

    # CostTracker.total_grok_cost uses get_pricing() from distill.llm.cost
    tracker = CostTracker()
    tracker.record(
        TokenUsage(
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            model="grok-4.3",
            call_type="analysis",
        )
    )
    rates = get_pricing("grok-4.3")
    expected = 1_000_000 * rates["input"] / 1_000_000 + 1_000_000 * rates["output"] / 1_000_000
    assert tracker.total_grok_cost == expected

    # Verify the pricing dict is the same object
    assert "grok-4.3" in LLM_PRICING
    assert LLM_PRICING["grok-4.3"]["input"] == 1.25
    assert LLM_PRICING["grok-4.3"]["output"] == 2.50


def test_save_run_log_writes_to_ops_dir(tmp_path):
    """save_run_log writes to <log_dir>/.distill/cost_log.jsonl."""
    tracker = CostTracker()
    tracker.record(
        TokenUsage(prompt_tokens=100, completion_tokens=50, model="grok-4.3", call_type="test")
    )

    save_run_log(tmp_path, "test_cmd", tracker)

    ops_log = tmp_path / ".distill" / "cost_log.jsonl"
    assert ops_log.exists()
    entry = json.loads(ops_log.read_text(encoding="utf-8").strip())
    assert entry["command"] == "test_cmd"

    # Old location should NOT have the file
    assert not (tmp_path / "cost_log.jsonl").exists()


def test_save_run_log_migration_helper(tmp_path):
    """Existing root-level cost_log.jsonl is migrated to .distill/ on first run."""
    # Create a legacy cost_log.jsonl at the root
    old_log = tmp_path / "cost_log.jsonl"
    old_log.write_text('{"command": "old_entry"}\n', encoding="utf-8")

    tracker = CostTracker()
    tracker.record(
        TokenUsage(prompt_tokens=50, completion_tokens=25, model="grok-4.3", call_type="test")
    )

    save_run_log(tmp_path, "new_entry", tracker)

    # Old file should be gone
    assert not old_log.exists()

    # New location should have both the migrated content and the new entry
    new_log = tmp_path / ".distill" / "cost_log.jsonl"
    assert new_log.exists()
    lines = new_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["command"] == "old_entry"
    assert json.loads(lines[1])["command"] == "new_entry"


def test_save_run_log_no_migration_when_new_exists(tmp_path):
    """If .distill/cost_log.jsonl already exists, don't migrate the old one."""
    # Create both old and new
    old_log = tmp_path / "cost_log.jsonl"
    old_log.write_text('{"command": "old"}\n', encoding="utf-8")

    ops_dir = tmp_path / ".distill"
    ops_dir.mkdir()
    new_log = ops_dir / "cost_log.jsonl"
    new_log.write_text('{"command": "already_migrated"}\n', encoding="utf-8")

    tracker = CostTracker()
    tracker.record(
        TokenUsage(prompt_tokens=50, completion_tokens=25, model="grok-4.3", call_type="test")
    )

    save_run_log(tmp_path, "append", tracker)

    # Old file should still be there (not migrated since new already exists)
    assert old_log.exists()

    # New log should have the existing entry + the new one
    lines = new_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["command"] == "already_migrated"
    assert json.loads(lines[1])["command"] == "append"
