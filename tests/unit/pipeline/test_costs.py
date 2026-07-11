"""Tests for distill.costs."""

import json

from distill.llm.cost import deep_research_query_cost
from distill.llm.router import LLM_Response
from distill.pipeline.costs import (
    ACCORDION_GROK_ESTIMATE,
    CostTracker,
    TokenUsage,
    estimate_ask_workflow_cost,
    estimate_paper_workflow_cost,
    estimate_routed_video_workflow_cost,
    estimate_run_cost,
    estimate_site_batch_workflow_cost,
    estimate_stage_cost,
    estimate_synthesis_workflow_cost,
    estimate_video_workflow_cost,
    report_deep_research_estimate,
    save_run_log,
)


def test_scan_run_excluded_from_video_calibration():
    # The per-video calibration rate must come only from pure full-analysis
    # runs. A scan pass is ~8x cheaper and a mixed full+shorts run skews the
    # numerator/denominator, so both must be excluded (returns None).
    from distill.pipeline.costs import _classify_clean_run

    scan = {"actual_cost": 0.01, "full_videos": 5, "by_call_type": {"scan": {"calls": 5}}}
    assert _classify_clean_run(scan) is None

    full = {
        "actual_cost": 0.15,
        "full_videos": 5,
        "by_call_type": {"pass1": {"calls": 5}, "pass2": {"calls": 5}},
    }
    assert _classify_clean_run(full) == ("video", 0.15, 5)

    mixed = {
        "actual_cost": 0.10,
        "full_videos": 2,
        "shorts": 5,
        "by_call_type": {"pass1": {"calls": 2}},
    }
    assert _classify_clean_run(mixed) is None


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


def test_estimate_run_cost_uses_active_local_route_when_provided():
    from distill.llm.router import RouterConfig

    text = estimate_run_cost(
        2,
        1,
        router_config=RouterConfig(provider="ollama", fast_model="qwen2.5:14b"),
    )

    assert text.startswith("Estimated cost: $0.00")


def test_video_workflow_estimate_matches_display_components():
    from distill.pipeline.costs import estimate_stage_cost

    estimate = estimate_video_workflow_cost(
        full_videos=2,
        shorts=1,
        scan_videos=3,
        include_report=True,
        synthesis_calls=2,
    )

    expected = (
        2 * estimate_stage_cost("video_full")
        + estimate_stage_cost("video_short")
        + 3 * estimate_stage_cost("video_scan")
        + 2 * estimate_stage_cost("synthesis")
        + report_deep_research_estimate()
    )
    assert estimate == expected


def test_routed_video_workflow_estimate_is_zero_for_local_stages():
    from distill.llm.router import RouterConfig

    estimate = estimate_routed_video_workflow_cost(
        full_videos=2,
        shorts=1,
        scan_videos=3,
        synthesis_calls=2,
        router_config=RouterConfig(provider="ollama", fast_model="qwen2.5:14b"),
    )

    assert estimate == 0.0


def test_routed_video_workflow_prices_mixed_local_and_cloud_routes():
    from distill.llm.router import RouterConfig

    estimate = estimate_routed_video_workflow_cost(
        full_videos=2,
        synthesis_calls=1,
        router_config=RouterConfig(
            provider="ollama",
            fast_model="qwen2.5:14b",
            synthesis_provider="anthropic",
            synthesis_model="claude-sonnet-4",
        ),
    )

    assert estimate == estimate_stage_cost("synthesis", model="claude-sonnet-4")


def test_routed_claim_extraction_prices_the_concepts_route():
    from distill.llm.router import RouterConfig

    estimate = estimate_routed_video_workflow_cost(
        claim_extraction_calls=2,
        router_config=RouterConfig(
            provider="ollama",
            fast_model="qwen2.5:14b",
            concepts_provider="anthropic",
            concepts_model="claude-sonnet-4",
        ),
    )

    assert estimate == 2 * estimate_stage_cost("claim_extraction", model="claude-sonnet-4")


def test_routed_video_workflow_prices_eligible_metered_fallback():
    from distill.llm.router import RouterConfig

    estimate = estimate_routed_video_workflow_cost(
        full_videos=1,
        router_config=RouterConfig(
            provider="ollama",
            fast_model="qwen2.5:14b",
            fallback_provider="xai",
            fallback_model="grok-4.3",
        ),
    )

    assert estimate == estimate_stage_cost("video_full", model="grok-4.3")


def test_routed_video_workflow_ignores_blocked_metered_fallback():
    from distill.llm.router import RouterConfig

    estimate = estimate_routed_video_workflow_cost(
        synthesis_calls=1,
        router_config=RouterConfig(
            provider="ollama",
            fast_model="qwen2.5:14b",
            cost_mode="no-metered",
            fallback_provider="xai",
            fallback_model="grok-4.3",
        ),
    )

    assert estimate == 0.0


def test_routed_video_workflow_includes_metered_report_generation():
    from distill.llm.router import RouterConfig

    router_config = RouterConfig(provider="xai", fast_model="grok-4.3")

    estimate = estimate_routed_video_workflow_cost(
        full_videos=1,
        include_report=True,
        router_config=router_config,
    )

    expected = (
        estimate_stage_cost("video_full", model="grok-4.3")
        + deep_research_query_cost()
        + max(estimate_stage_cost("synthesis", model="grok-4.3"), ACCORDION_GROK_ESTIMATE)
    )
    assert estimate == expected


def test_routed_video_workflow_builds_default_router(monkeypatch):
    monkeypatch.setenv("DISTILL_PROVIDER", "ollama")
    monkeypatch.setenv("DISTILL_FAST_MODEL", "qwen2.5:14b")
    monkeypatch.delenv("DISTILL_FALLBACK_PROVIDER", raising=False)
    monkeypatch.delenv("DISTILL_FALLBACK_MODEL", raising=False)

    assert estimate_routed_video_workflow_cost(full_videos=1) == 0.0


def test_estimate_run_cost_includes_routed_metered_accordion_generation():
    from distill.llm.router import RouterConfig

    text = estimate_run_cost(
        0,
        0,
        accordion=True,
        router_config=RouterConfig(provider="xai", fast_model="grok-4.3"),
    )

    assert f"generation ${ACCORDION_GROK_ESTIMATE:.2f}" in text


def test_routed_local_accordion_has_only_explicit_deep_research_cost():
    from distill.llm.router import RouterConfig

    router_config = RouterConfig(provider="ollama", fast_model="qwen2.5:14b")

    estimate = estimate_routed_video_workflow_cost(
        include_report=True,
        router_config=router_config,
    )
    text = estimate_run_cost(0, 0, accordion=True, router_config=router_config)

    assert estimate == deep_research_query_cost()
    assert "generation $0.00" in text


def test_synthesis_workflow_estimate_counts_known_calls():
    from distill.pipeline.costs import estimate_stage_cost

    assert estimate_synthesis_workflow_cost(0) == 0.0
    assert estimate_synthesis_workflow_cost(3) == 3 * estimate_stage_cost("synthesis")


def test_routed_synthesis_paper_ask_and_site_estimates_are_zero_locally():
    from distill.llm.router import RouterConfig

    rc = RouterConfig(provider="ollama", fast_model="qwen2.5:14b")

    assert estimate_synthesis_workflow_cost(2, router_config=rc) == 0.0
    assert estimate_paper_workflow_cost(2, synthesis_calls=2, router_config=rc) == 0.0
    assert estimate_ask_workflow_cost(2_000, router_config=rc) == 0.0
    assert estimate_site_batch_workflow_cost(3, synthesis_calls=2, router_config=rc) == 0.0


def test_routed_site_estimate_preserves_explicit_deep_research_cost():
    from distill.llm.router import RouterConfig

    estimate = estimate_site_batch_workflow_cost(
        3,
        synthesis_calls=2,
        include_report=True,
        router_config=RouterConfig(provider="ollama", fast_model="qwen2.5:14b"),
    )

    assert estimate == report_deep_research_estimate()


def test_routed_nonvideo_estimates_keep_metered_workload_overrides():
    from distill.llm.router import RouterConfig

    rc = RouterConfig(
        provider="ollama",
        fast_model="qwen2.5:14b",
        synthesis_provider="anthropic",
        synthesis_model="claude-sonnet-4",
        qa_provider="anthropic",
        qa_model="claude-sonnet-4",
        site_provider="anthropic",
        site_model="claude-sonnet-4",
    )

    assert estimate_synthesis_workflow_cost(router_config=rc) > 0
    assert estimate_ask_workflow_cost(2_000, router_config=rc) > 0
    assert estimate_site_batch_workflow_cost(1, router_config=rc) > 0


def test_paper_estimate_follows_site_route_over_global_provider():
    from distill.llm.router import RouterConfig

    metered_site = RouterConfig(
        provider="ollama",
        fast_model="qwen2.5:14b",
        site_provider="anthropic",
        site_model="claude-sonnet-4",
    )
    local_site = RouterConfig(
        provider="xai",
        fast_model="grok-4.3",
        site_provider="ollama",
        site_model="qwen2.5:14b",
    )

    assert estimate_paper_workflow_cost(1, synthesis_calls=1, router_config=metered_site) > 0
    assert (
        estimate_paper_workflow_cost(
            1,
            synthesis_calls=1,
            router_config=local_site,
            analysis_mode="single",
        )
        == 0.0
    )
    assert (
        estimate_paper_workflow_cost(
            1,
            synthesis_calls=1,
            router_config=local_site,
            analysis_mode="multipass",
        )
        > 0
    )
    assert (
        estimate_paper_workflow_cost(
            1,
            synthesis_calls=1,
            router_config=local_site,
        )
        > 0
    )


def test_site_estimate_routes_page_and_synthesis_work_through_site_override():
    from distill.llm.router import RouterConfig

    local_site = RouterConfig(
        provider="xai",
        fast_model="grok-4.3",
        site_provider="ollama",
        site_model="qwen2.5:14b",
        synthesis_provider="anthropic",
        synthesis_model="claude-sonnet-4",
    )
    metered_site = RouterConfig(
        provider="ollama",
        fast_model="qwen2.5:14b",
        site_provider="anthropic",
        site_model="claude-sonnet-4",
        synthesis_provider="ollama",
        synthesis_model="qwen2.5:14b",
    )

    assert (
        estimate_site_batch_workflow_cost(
            2,
            synthesis_calls=3,
            router_config=local_site,
        )
        == 0.0
    )
    assert (
        estimate_site_batch_workflow_cost(
            2,
            synthesis_calls=3,
            router_config=metered_site,
        )
        > 0
    )


def test_paper_workflow_estimate_counts_papers_and_synthesis():
    from distill.pipeline.costs import estimate_stage_cost

    estimate = estimate_paper_workflow_cost(3, synthesis_calls=2)

    expected = 3 * estimate_stage_cost("paper") + 2 * estimate_stage_cost("synthesis")
    assert estimate == expected
    assert estimate_paper_workflow_cost(-1) == 0.0


def test_ask_workflow_estimate_uses_retrieved_source_size():
    empty = estimate_ask_workflow_cost(0, question_chars=100)
    short = estimate_ask_workflow_cost(1_000, question_chars=100)
    long = estimate_ask_workflow_cost(8_000, question_chars=100)

    assert empty == 0.0
    assert 0 < short < long


def test_site_batch_workflow_estimate_counts_pages_synthesis_and_report():
    estimate = estimate_site_batch_workflow_cost(
        3,
        synthesis_calls=2,
        include_report=True,
    )

    expected = (
        3 * estimate_stage_cost("site_page")
        + 2 * estimate_stage_cost("synthesis")
        + report_deep_research_estimate()
    )
    assert estimate == expected
    assert estimate_site_batch_workflow_cost(0) == 0.0


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


def test_anthropic_sonnet5_uses_current_intro_pricing():
    from distill.llm.cost import compute_cost

    assert compute_cost("claude-sonnet-5", 1_000_000, 1_000_000) == 12.0


def test_cost_tracker_treats_no_metered_provider_responses_as_zero():
    tracker = CostTracker()
    response = LLM_Response(
        text="ok",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        model="qwen2.5:14b",
        provider_name="ollama",
        provider_type="local",
    )

    tracker.record(TokenUsage.from_response(response, call_type="analysis"))
    tracker.record(
        TokenUsage(
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            model="agent",
            provider_name="agent",
            call_type="analysis",
        )
    )

    assert tracker.total_cost == 0.0
    assert tracker.format_cost() == "$0.0000"
    assert tracker.summary_dict()["no_metered_calls"] == 2


def test_budget_exceeded_error_formats_small_and_large_budgets():
    from distill.pipeline.costs import BudgetExceededError, ProjectedBudgetExceededError

    err_small = BudgetExceededError(0.00123, 0.0005)
    assert "$0.0005" in str(err_small)

    err_large = BudgetExceededError(1.2345, 1.0)
    assert "$1.00" in str(err_large)

    projected = ProjectedBudgetExceededError(0.12, 0.05)
    assert isinstance(projected, BudgetExceededError)
    assert projected.spent == 0.12
    assert projected.projected == 0.12
    assert "projected spend" in str(projected)
    assert "before the run starts" in str(projected)


def test_cost_tracker_budget_exceeded_raises_on_record():
    from distill.pipeline.costs import BudgetExceededError, CostTracker, TokenUsage

    tracker = CostTracker(budget=0.001)
    tracker.record(TokenUsage(prompt_tokens=1, completion_tokens=1, model="grok-4.3"))

    try:
        tracker.record(TokenUsage(prompt_tokens=100000, completion_tokens=100000, model="grok-4.3"))
    except BudgetExceededError:
        pass
    else:
        raise AssertionError("expected BudgetExceededError")


def test_route_class_covers_included_plan_and_no_metered():
    from distill.pipeline.costs import TokenUsage, _route_class

    local = TokenUsage(provider_type="local")
    assert _route_class(local) == "local"

    included = TokenUsage(provider_type="included-plan")
    assert _route_class(included) == "included-plan"

    class Fake:
        provider_type = "x"
        provider_name = ""
        no_metered_cost = True

    assert _route_class(Fake()) == "no-metered"  # type: ignore[arg-type]


def test_report_deep_research_estimate_without_section_writing():
    from distill.pipeline.costs import deep_research_query_cost, report_deep_research_estimate

    val = report_deep_research_estimate(include_section_writing=False)
    assert val == deep_research_query_cost()


def test_load_cost_calibration_handles_missing_and_bad_json(tmp_path):
    from distill.pipeline.costs import load_cost_calibration

    # missing file -> default calibration
    cal = load_cost_calibration(tmp_path)
    assert cal.per_paper > 0  # default

    # bad file content
    log = tmp_path / ".distill" / "cost_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("not json\n\n{}\n", encoding="utf-8")
    cal2 = load_cost_calibration(tmp_path)
    assert cal2.per_paper > 0  # still defaults on bad data (blank line continue hit)


def test_save_run_log_records_route_usage_for_zero_dollar_calls(tmp_path):
    tracker = CostTracker()
    tracker.record(
        TokenUsage(
            prompt_tokens=120,
            completion_tokens=40,
            model="qwen3:latest",
            call_type="analysis",
            provider_name="ollama",
            provider_type="local",
        )
    )
    tracker.record_transcription("local", 90.0)

    save_run_log(tmp_path, "local-analysis", tracker)

    entry = json.loads(
        (tmp_path / ".distill" / "cost_log.jsonl").read_text(encoding="utf-8").strip()
    )
    assert entry["actual_cost"] == 0.0
    assert entry["usage_ledger"]["no_metered_llm_calls"] == 1
    assert entry["usage_ledger"]["metered_llm_calls"] == 0
    assert entry["usage_ledger"]["no_metered_transcription_calls"] == 1
    assert entry["by_provider"]["ollama"]["no_metered_cost"] is True
    assert entry["by_route_class"]["local"]["calls"] == 1


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


def test_projected_next_run_cost():
    """projected_next_run_cost averages recent non-preview actuals."""
    from distill.pipeline.costs import projected_next_run_cost

    entries = [
        {"command": "learn", "actual_cost": 0.1},
        {"command": "learn_preview", "actual_cost": 0.01},  # ignored
        {"command": "papers", "actual_cost": 0.2},
        {"command": "discover", "actual_cost": 0.3},
    ]
    proj = projected_next_run_cost(entries)
    # last 3 non-preview: 0.1,0.2,0.3 avg 0.2
    assert abs(proj - 0.2) < 0.001

    assert projected_next_run_cost([]) == 0.0
    assert projected_next_run_cost([{"command": "x_preview", "actual_cost": 1}]) == 0.0

    # zero cost and non-numeric skipped; caps at last 5 qualifying
    entries6 = [
        {"command": "a", "actual_cost": 0.01},
        {"command": "b", "actual_cost": 0.02},
        {"command": "c", "actual_cost": 0.03},
        {"command": "d", "actual_cost": 0.04},
        {"command": "e", "actual_cost": 0.05},
        {"command": "f", "actual_cost": 0.06},
        {"command": "g", "actual_cost": 0},  # skipped
        {"command": "h", "actual_cost": "nan"},  # skipped non num
    ]
    proj6 = projected_next_run_cost(entries6)
    # last 5 non-zero: 0.02..0.06 avg 0.04
    assert abs(proj6 - 0.04) < 0.0001

    # only zero-cost entries -> 0
    assert projected_next_run_cost([{"command": "z", "actual_cost": 0.0}]) == 0.0


def test_cost_anomaly_warnings_flag_media_daily_and_run_spikes():
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        {
            "timestamp": "2026-06-01T12:00:00",
            "command": "report",
            "actual_cost": 1.0,
            "metadata": {"topic": "ai"},
        },
        {
            "timestamp": "2026-06-02T12:00:00",
            "command": "report",
            "actual_cost": 1.2,
            "metadata": {"topic": "ai"},
        },
        {
            "timestamp": "2026-06-03T12:00:00",
            "command": "discover_preview",
            "actual_cost": 99.0,
            "metadata": {"topic": "ai"},
        },
        {
            "timestamp": "2026-06-03T12:00:00",
            "command": "report",
            "actual_cost": 12.0,
            "metadata": {"topic": "ai"},
            "by_model": {"grok-imagine-image": {"calls": 24}},
        },
    ]

    warnings = cost_anomaly_warnings(entries, daily_threshold_usd=10.0, limit=5)
    kinds = [warning["kind"] for warning in warnings]

    assert "xai-media-model" in kinds
    assert "daily-threshold" in kinds
    assert "daily-spike" in kinds
    assert "run-spike" in kinds
    assert all("preview" not in warning["message"] for warning in warnings)


def test_cost_anomaly_warnings_apply_custom_thresholds_and_workflow_budgets():
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        {
            "timestamp": "2026-06-01T12:00:00",
            "command": "report",
            "actual_cost": 0.8,
            "metadata": {"topic": "ai"},
        },
        {
            "timestamp": "2026-06-02T12:00:00",
            "command": "report",
            "actual_cost": 0.9,
            "metadata": {"topic": "ai"},
        },
        {
            "timestamp": "2026-06-03T12:00:00",
            "command": "report",
            "actual_cost": 3.0,
            "metadata": {"topic": "ai"},
        },
    ]

    warnings = cost_anomaly_warnings(
        entries,
        daily_threshold_usd=2.0,
        run_spike_min_usd=0.5,
        workflow_budgets_usd={"report": 1.25},
        limit=5,
    )
    messages = [warning["message"] for warning in warnings]
    kinds = [warning["kind"] for warning in warnings]

    assert "workflow-budget" in kinds
    assert "daily-threshold" in kinds
    assert "daily-spike" in kinds
    assert "run-spike" in kinds
    assert any("above workflow budget $1.25" in message for message in messages)


def test_cost_anomaly_warnings_ignore_bad_rows_and_zero_costs():
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        {"timestamp": "bad", "command": "learn", "actual_cost": "nan"},
        {"timestamp": "bad", "command": "learn", "actual_cost": True},
        {"timestamp": "2026-06-01T12:00:00", "command": "learn", "actual_cost": 0},
    ]

    assert cost_anomaly_warnings(entries) == []


def _anomaly_row(
    command: str,
    cost: object,
    *,
    timestamp: str | None = "2026-06-01T12:00:00",
    topic: str | None = "ai",
    **extra: object,
) -> dict[str, object]:
    """Build one cost-ledger row for cost_anomaly_warnings tests."""
    row: dict[str, object] = {"command": command, "actual_cost": cost, "timestamp": timestamp}
    if topic is not None:
        row["metadata"] = {"topic": topic}
    row.update(extra)
    return row


def test_cost_anomaly_warnings_media_dedup_and_non_media_skip():
    """Media warnings dedupe per model+date, read a top-level model, and skip non-media models."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row(
            "video",
            1.0,
            timestamp="2026-06-01T00:00:00",
            by_model={"grok-imagine-image": {"calls": 1}},
        ),
        _anomaly_row("video", 1.0, timestamp="2026-06-01T09:00:00", model="grok-imagine-image"),
        _anomaly_row(
            "report", 2.0, timestamp="2026-06-02T00:00:00", by_model={"grok-4.3": {"calls": 1}}
        ),
        _anomaly_row(
            "video",
            1.0,
            timestamp="2026-06-02T09:00:00",
            by_model={"grok-imagine-image": {"calls": 1}},
        ),
    ]

    media = [w for w in cost_anomaly_warnings(entries, limit=5) if w["kind"] == "xai-media-model"]
    joined = " ".join(str(w["message"]) for w in media)
    assert len(media) == 2  # one per date; the same-date duplicate is deduped
    assert "grok-imagine-image" in joined
    assert "grok-4.3" not in joined  # non-media model never warned


def test_cost_anomaly_warnings_respect_limit_after_media():
    """The total limit caps output and short-circuits after the media pass."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row(
            "video",
            1.0,
            timestamp="2026-06-01T00:00:00",
            by_model={"grok-imagine-image": {"calls": 1}},
        ),
        _anomaly_row(
            "video",
            1.0,
            timestamp="2026-06-02T00:00:00",
            by_model={"grok-imagine-image": {"calls": 1}},
        ),
    ]

    warnings = cost_anomaly_warnings(entries, limit=1)
    assert len(warnings) == 1
    assert warnings[0]["kind"] == "xai-media-model"


def test_cost_anomaly_warnings_skip_non_overrun_workflow_budgets():
    """Invalid budgets, unbudgeted commands, and under-budget runs never warn."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row("learn", 5.0),  # not budgeted
        _anomaly_row("report", 0.5),  # budgeted but under budget
    ]

    warnings = cost_anomaly_warnings(
        entries,
        workflow_budgets_usd={"report": 1.25, "bad": 0.0, "  ": 2.0},  # last two are invalid
        limit=5,
    )
    assert all(w["kind"] != "workflow-budget" for w in warnings)


def test_cost_anomaly_warnings_skip_non_spike_runs():
    """A gentle rise below the multiplier, and a latest run below the floor, are not spikes."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row("report", 1.0, timestamp="2026-06-01T00:00:00"),
        _anomaly_row("report", 1.1, timestamp="2026-06-01T01:00:00"),
        _anomaly_row("report", 1.2, timestamp="2026-06-01T02:00:00"),  # below multiplier
        _anomaly_row("channel", 1.0, topic="ml", timestamp="2026-06-01T00:00:00"),
        _anomaly_row("channel", 1.1, topic="ml", timestamp="2026-06-01T01:00:00"),
        _anomaly_row("channel", 0.6, topic="ml", timestamp="2026-06-01T02:00:00"),  # below floor
    ]

    warnings = cost_anomaly_warnings(entries, run_spike_min_usd=1.0, limit=5)
    assert all(w["kind"] != "run-spike" for w in warnings)


def test_cost_anomaly_warnings_skip_non_spike_daily_totals():
    """Four modest days (odd-length baseline) below the spike bar produce no daily warning."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row("report", 1.0, topic=None, timestamp="2026-06-01T00:00:00"),
        _anomaly_row("report", 1.1, topic=None, timestamp="2026-06-02T00:00:00"),
        _anomaly_row("report", 1.2, topic=None, timestamp="2026-06-03T00:00:00"),
        _anomaly_row("report", 1.15, topic=None, timestamp="2026-06-04T00:00:00"),
    ]

    assert cost_anomaly_warnings(entries, daily_threshold_usd=10.0, limit=5) == []


def test_cost_anomaly_warnings_parse_malformed_rows_without_crashing():
    """Non-numeric costs, missing timestamps, and unparseable dates degrade to no warning."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row("a", None),  # non-numeric cost -> dropped
        _anomaly_row("a", "not-a-number"),  # unparseable cost string -> dropped
        _anomaly_row("a", 1.0, timestamp=None),  # missing timestamp -> no date
        _anomaly_row("a", 1.0, timestamp="9999-99-99T00:00"),  # unparseable, >=10 chars
    ]

    assert cost_anomaly_warnings(entries) == []


def test_cost_anomaly_warnings_cap_workflow_warnings_at_limit():
    """More budget overruns than the limit are capped, short-circuiting later passes."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row("report", 5.0),
        _anomaly_row("discover", 5.0),
        _anomaly_row("papers", 5.0),
    ]

    warnings = cost_anomaly_warnings(
        entries,
        workflow_budgets_usd={"report": 1.0, "discover": 1.0, "papers": 1.0},
        limit=2,
    )
    assert len(warnings) == 2
    assert all(w["kind"] == "workflow-budget" for w in warnings)


def test_cost_anomaly_warnings_cap_daily_warnings_at_limit():
    """More over-threshold days than the limit are capped, short-circuiting later passes."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row("report", 15.0, topic=None, timestamp="2026-06-01T00:00:00"),
        _anomaly_row("report", 16.0, topic=None, timestamp="2026-06-02T00:00:00"),
        _anomaly_row("report", 17.0, topic=None, timestamp="2026-06-03T00:00:00"),
    ]

    warnings = cost_anomaly_warnings(entries, daily_threshold_usd=10.0, limit=2)
    assert len(warnings) == 2
    assert all(w["kind"] == "daily-threshold" for w in warnings)


def test_cost_anomaly_warnings_cap_run_spikes_at_limit():
    """More run spikes than the limit are capped and stop the scan."""
    from distill.pipeline.costs import cost_anomaly_warnings

    entries = [
        _anomaly_row("report", 1.0, timestamp="2026-06-01T00:00:00"),
        _anomaly_row("report", 1.0, timestamp="2026-06-02T00:00:00"),
        _anomaly_row("report", 5.0, timestamp="2026-06-03T00:00:00"),
        _anomaly_row("channel", 1.0, topic="ml", timestamp="2026-06-01T00:00:00"),
        _anomaly_row("channel", 1.0, topic="ml", timestamp="2026-06-02T00:00:00"),
        _anomaly_row("channel", 5.0, topic="ml", timestamp="2026-06-03T00:00:00"),
    ]

    # A high daily threshold isolates the run-spike pass from daily warnings.
    warnings = cost_anomaly_warnings(entries, daily_threshold_usd=100.0, limit=1)
    assert len(warnings) == 1
    assert warnings[0]["kind"] == "run-spike"


def test_cost_anomaly_warnings_match_budget_despite_command_whitespace():
    """A ledger command with surrounding whitespace still matches its stripped budget key.

    Budget keys are normalized with strip().lower(); the ledger command must be
    normalized the same way, or an over-budget run silently escapes its warning.
    """
    from distill.pipeline.costs import cost_anomaly_warnings

    warnings = cost_anomaly_warnings(
        [_anomaly_row(" discover ", 5.0)],
        workflow_budgets_usd={"discover": 1.0},
        limit=5,
    )
    assert any(w["kind"] == "workflow-budget" for w in warnings)


def test_estimate_run_cost_zero_items_no_accordion():
    # Covers the false branches for if full_videos, if shorts, if accordion.
    text = estimate_run_cost(0, 0, accordion=False)
    assert text.startswith("Estimated cost: $0.00")
    assert "()" in text or "0.00 ( )" in text or text.endswith("()")


def test_classify_clean_run_site_zero_calls_is_none():
    from distill.pipeline.costs import _classify_clean_run

    site_zero = {
        "actual_cost": 0.05,
        "by_call_type": {"site_page": {"calls": 0}},
    }
    assert _classify_clean_run(site_zero) is None  # n==0 branch


def test_load_cost_calibration_oserror_on_read_returns_default(tmp_path):
    from unittest.mock import patch

    from distill.pipeline.costs import load_cost_calibration

    log = tmp_path / ".distill" / "cost_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        '{"actual_cost": 0.1, "by_call_type": {"paper": {"calls": 1}}}\n', encoding="utf-8"
    )

    with patch.object(type(log), "read_text", side_effect=OSError("simulated read fail")):
        cal = load_cost_calibration(tmp_path)
    # hits the except OSError path -> default
    assert cal.per_paper > 0


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


# ---- model-aware Gemini Deep Research cost ---------------------------------


def test_gemini_cost_is_model_aware():
    tracker = CostTracker()
    tracker.record_gemini_query("deep-research-preview-04-2026")  # standard ~2.50
    tracker.record_gemini_query("deep-research-max-preview-04-2026")  # max ~5.00
    assert tracker.gemini_queries == 2
    assert tracker.total_gemini_cost == 7.50


def test_gemini_cost_count_only_fallback():
    # A tracker that carries only a count (e.g. a sub-range report copy) still
    # prices at the standard per-query estimate.
    tracker = CostTracker(gemini_queries=2)
    assert tracker.total_gemini_cost == 2 * deep_research_query_cost()


# ---- transcription cost tracking -------------------------------------------


def test_record_transcription_cloud_and_local():
    tracker = CostTracker()
    tracker.record_transcription("xai-grok-stt", 3600.0, model="grok-stt")  # 1h @ $0.10
    tracker.record_transcription("whisper-1", 1800.0)  # 0.5h @ $0.36 = 0.18
    tracker.record_transcription("local", 7200.0)  # free
    assert len(tracker.transcriptions) == 3
    assert round(tracker.total_transcription_cost, 4) == round(0.10 + 0.18, 4)


def test_total_cost_includes_transcription():
    tracker = CostTracker()
    tracker.record(TokenUsage(prompt_tokens=1_000_000, completion_tokens=0, model="grok-4.3"))
    tracker.record_transcription("xai-grok-stt", 3600.0)
    # grok input 1M @ $1.25 + transcription 1h @ $0.10
    assert round(tracker.total_cost, 4) == round(1.25 + 0.10, 4)


def test_summary_dict_includes_transcription_when_present():
    tracker = CostTracker()
    assert "transcription_calls" not in tracker.summary_dict()
    tracker.record_transcription("whisper-1", 3600.0)
    summary = tracker.summary_dict()
    assert summary["transcription_calls"] == 1
    assert summary["estimated_transcription_cost"] == "$0.3600"


def test_estimate_discover_cost():
    from distill.pipeline.costs import (
        _DISCOVER_PAPER_COST,
        _DISCOVER_SITE_COST,
        _DISCOVER_VIDEO_COST,
        estimate_discover_cost,
    )

    assert estimate_discover_cost() == 0.0
    # Rates are derived from the default model's pricing, so compute the
    # expectation from the constants rather than pinning a dollar figure.
    expected = 5 * _DISCOVER_PAPER_COST + 10 * _DISCOVER_VIDEO_COST + 3 * _DISCOVER_SITE_COST
    assert round(estimate_discover_cost(papers=5, videos=10, sites=3), 6) == round(expected, 6)
    assert estimate_discover_cost(papers=-1) == 0.0  # clamps negatives


def test_discover_estimates_zero_active_local_routes_even_with_cloud_history():
    from distill.llm.router import RouterConfig
    from distill.pipeline.costs import CostCalibration, estimate_discover_items

    calibration = CostCalibration(
        per_paper=0.2,
        per_video=0.3,
        per_site=0.4,
        samples={"paper": 5, "video": 5, "site": 5},
    )
    rc = RouterConfig(provider="ollama", fast_model="qwen2.5:14b")

    estimate = estimate_discover_items(
        papers=2,
        video_durations=[900],
        sites=1,
        calibration=calibration,
        router_config=rc,
    )

    assert estimate.expected == 0.0
    assert estimate.low == 0.0
    assert estimate.high == 0.0
    assert not estimate.calibrated


def test_discover_cost_keeps_historical_rates_for_metered_routes():
    from distill.llm.router import RouterConfig
    from distill.pipeline.costs import CostCalibration, estimate_discover_cost

    calibration = CostCalibration(
        per_paper=0.2,
        per_video=0.3,
        per_site=0.4,
        samples={"paper": 4, "video": 5, "site": 6},
    )

    estimate = estimate_discover_cost(
        papers=1,
        videos=2,
        sites=3,
        calibration=calibration,
        router_config=RouterConfig(provider="xai", fast_model="grok-4.3"),
    )

    assert estimate == 0.2 + 2 * 0.3 + 3 * 0.4


def test_discover_estimate_prices_only_metered_source_override():
    from distill.llm.router import RouterConfig
    from distill.pipeline.costs import estimate_discover_items

    rc = RouterConfig(
        provider="ollama",
        fast_model="qwen2.5:14b",
        site_provider="anthropic",
        site_model="claude-sonnet-4",
    )

    estimate = estimate_discover_items(
        papers=1,
        video_durations=[900],
        sites=1,
        router_config=rc,
    )

    assert estimate.expected == (
        estimate_stage_cost("paper", model="claude-sonnet-4")
        + estimate_stage_cost("site_page", model="claude-sonnet-4")
    )


def test_stage_cost_tracks_default_model_pricing():
    from distill.llm.cost import DEFAULT_MODEL, compute_cost
    from distill.pipeline.costs import _STAGE_TOKENS, estimate_stage_cost

    # estimate_stage_cost must equal compute_cost over the stage's token volumes
    # at the default model — i.e. it tracks the model, never a hard-coded rate.
    tin, tout = _STAGE_TOKENS["video_full"]
    assert estimate_stage_cost("video_full") == compute_cost(DEFAULT_MODEL, tin, tout)
    # grok-4.3 default ($1.25 / $2.50): 13k in + 6k out = $0.03125.
    assert round(estimate_stage_cost("video_full"), 5) == 0.03125


# ---- metadata-aware, self-calibrating discover estimate (0.9.1) ------------


def _write_cost_rows(tmp_path, rows: list[dict]) -> None:
    """Write run-log rows to <tmp_path>/.distill/cost_log.jsonl for calibration."""
    ops = tmp_path / ".distill"
    ops.mkdir(parents=True, exist_ok=True)
    with (ops / "cost_log.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _paper_row(cost: float, papers: int) -> dict:
    return {
        "command": "papers",
        "actual_cost": cost,
        "full_videos": 0,
        "by_call_type": {"paper": {"calls": papers}, "paper_synthesis": {"calls": 1}},
    }


def _video_row(cost: float, videos: int) -> dict:
    return {
        "command": "latest",
        "actual_cost": cost,
        "full_videos": videos,
        "by_call_type": {"pass1": {"calls": videos}, "pass2": {"calls": videos}},
    }


def test_load_cost_calibration_no_log_uses_defaults(tmp_path):
    from distill.pipeline.costs import (
        _DISCOVER_PAPER_COST,
        _DISCOVER_VIDEO_COST,
        load_cost_calibration,
    )

    cal = load_cost_calibration(tmp_path)
    assert cal.per_paper == _DISCOVER_PAPER_COST
    assert cal.per_video == _DISCOVER_VIDEO_COST
    assert cal.any_calibrated is False
    assert cal.samples == {"paper": 0, "video": 0, "site": 0}


def test_load_cost_calibration_derives_per_paper_rate(tmp_path):
    from distill.pipeline.costs import load_cost_calibration

    # Three clean paper runs: total $0.30 over 10 papers -> $0.03/paper.
    _write_cost_rows(
        tmp_path,
        [_paper_row(0.10, 4), _paper_row(0.10, 4), _paper_row(0.10, 2)],
    )
    cal = load_cost_calibration(tmp_path)
    assert round(cal.per_paper, 4) == 0.03
    assert cal.samples["paper"] == 10
    assert cal.any_calibrated is True
    # No video/site history -> those stay on defaults.
    assert cal.samples["video"] == 0


def test_load_cost_calibration_skips_malformed_rows(tmp_path):
    # A JSON-valid but schema-invalid row (string actual_cost, non-dict
    # by_call_type, list/scalar line) or a syntactically-invalid line must not
    # crash calibration: the bad rows are skipped and the clean rows still price.
    from distill.pipeline.costs import load_cost_calibration

    ops = tmp_path / ".distill"
    ops.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"command": "papers", "actual_cost": "nan", "by_call_type": {"paper": {}}}),
        json.dumps({"command": "papers", "actual_cost": 0.10, "by_call_type": "paper"}),
        json.dumps(["unexpected", "list", "row"]),
        json.dumps(42),
        "{not valid json",
        json.dumps(_paper_row(0.10, 4)),
        json.dumps(_paper_row(0.10, 6)),
    ]
    (ops / "cost_log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cal = load_cost_calibration(tmp_path)
    assert round(cal.per_paper, 4) == 0.02  # $0.20 over 10 clean papers
    assert cal.samples["paper"] == 10
    assert cal.any_calibrated is True


def test_load_cost_calibration_derives_per_video_from_full_videos(tmp_path):
    from distill.pipeline.costs import load_cost_calibration

    # Clean video runs: $0.12 over 12 videos -> $0.01/video (counted via full_videos).
    _write_cost_rows(tmp_path, [_video_row(0.06, 6), _video_row(0.06, 6)])
    cal = load_cost_calibration(tmp_path)
    assert round(cal.per_video, 4) == 0.01
    assert cal.samples["video"] == 12
    assert cal.samples["paper"] == 0


def test_load_cost_calibration_thin_history_falls_back(tmp_path):
    from distill.pipeline.costs import _DISCOVER_PAPER_COST, load_cost_calibration

    # Only 2 papers seen (< default min_samples of 3) -> keep the constant.
    _write_cost_rows(tmp_path, [_paper_row(0.50, 2)])
    cal = load_cost_calibration(tmp_path)
    assert cal.per_paper == _DISCOVER_PAPER_COST
    assert cal.samples["paper"] == 0


def test_load_cost_calibration_ignores_preview_and_mixed_runs(tmp_path):
    from distill.pipeline.costs import _DISCOVER_PAPER_COST, load_cost_calibration

    mixed = {
        "command": "discover",
        "actual_cost": 5.0,
        "full_videos": 3,
        "by_call_type": {"paper": {"calls": 3}, "pass1": {"calls": 3}, "site_page": {"calls": 2}},
    }
    preview = dict(_paper_row(9.9, 9), command="papers_preview")
    _write_cost_rows(tmp_path, [mixed, preview])
    cal = load_cost_calibration(tmp_path)
    # Mixed run is not "clean" and preview is skipped -> no paper calibration.
    assert cal.per_paper == _DISCOVER_PAPER_COST
    assert cal.any_calibrated is False


def test_estimate_discover_items_scales_with_video_duration():
    from distill.pipeline.costs import CostCalibration, estimate_discover_items

    cal = CostCalibration(per_video=0.01, samples={"paper": 0, "video": 5, "site": 0})
    # Nominal-length video (900s) costs the base rate; a 4x-long one is capped at 4x.
    nominal = estimate_discover_items(video_durations=[900.0], calibration=cal)
    longer = estimate_discover_items(video_durations=[3600.0], calibration=cal)
    assert round(nominal.expected, 4) == 0.01
    assert round(longer.expected, 4) == 0.04
    # Unknown duration assumes nominal rather than zero.
    unknown = estimate_discover_items(video_durations=[None], calibration=cal)
    assert round(unknown.expected, 4) == 0.01


def test_estimate_discover_items_range_widens_without_calibration():
    from distill.pipeline.costs import CostCalibration, estimate_discover_items

    calibrated = CostCalibration(per_paper=0.02, samples={"paper": 5, "video": 0, "site": 0})
    cal_est = estimate_discover_items(papers=10, calibration=calibrated)
    assert cal_est.calibrated is True
    assert round(cal_est.expected, 4) == 0.20
    assert round(cal_est.low, 4) == 0.14  # 0.7x
    assert round(cal_est.high, 4) == 0.30  # 1.5x

    # No calibration -> wider 0.5x..2.0x band on the default rate.
    default_est = estimate_discover_items(papers=10)
    assert default_est.calibrated is False
    assert round(default_est.low, 4) == round(default_est.expected * 0.5, 4)
    assert round(default_est.high, 4) == round(default_est.expected * 2.0, 4)
    assert default_est.format().startswith("~$")
