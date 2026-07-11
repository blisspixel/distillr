import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SitePage
from distill.library import Library
from distill.pipeline import dashboard_data as _dashboard_data
from distill.pipeline.dashboard_data import (
    _load_site_manifest,
    build_site_section_state,
    collect_corpus_health_warnings,
    collect_recent_artifacts,
    collect_stale_topic_watches,
    collect_topic_changes,
    count_paper_corpus,
    count_site_corpus,
    count_topic_outputs,
    dashboard_snapshot,
    duration_str,
    entry_source_type,
    estimate_topic_watch_cost,
    estimated_topic_watch_sweep,
    format_run_timestamp,
    load_all_cost_runs,
    load_latest_run_payload,
    load_recent_cost_runs,
    load_topic_change_history,
    parse_run_datetime,
    read_json_dict,
    source_cost_rollups,
    stale_synthesis_warnings,
    strip_frontmatter,
    sum_recent_cost,
    topic_cost_rollups,
    topic_recent_costs,
    topic_spend_last_days,
    topic_trend_label,
    topic_watch_budget_messages,
)


def test_dashboard_snapshot_uses_shared_rollups_and_health(config):
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestChannel", "TestChannel")
    lib.add_to_topic_watchlist(
        "ai-daily",
        "AI daily",
        topic="ai",
        cadence="daily",
        limit=10,
        report=True,
        max_run_cost=1.0,
        monthly_budget=2.0,
    )

    video_dir = config.video_dir("ai", "TestChannel", "video-1")
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "metadata.json").write_text(
        json.dumps({"title": "Long Video", "duration": 3600, "analysis_mode": "scan"}),
        encoding="utf-8",
    )
    (video_dir / "transcript.txt").write_text("short", encoding="utf-8")
    (video_dir / "insights.md").write_text("brief", encoding="utf-8")

    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Synthesis", encoding="utf-8")
    (topic_dir / "change_history.jsonl").write_text(
        "\n".join(
            [
                '{"generated_at":"2026-04-01T08:00:00","summary":"+3 videos","counts":{"videos":3,"pages":0,"papers":0,"outputs":1}}',
                '{"generated_at":"2026-03-31T08:00:00","summary":"+1 video","counts":{"videos":1,"pages":0,"papers":0,"outputs":0}}',
            ]
        ),
        encoding="utf-8",
    )

    now = datetime.now()
    recent = (now - timedelta(days=2)).replace(microsecond=0).isoformat()
    (config.library_dir / "cost_log.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": recent,
                        "command": "learn",
                        "actual_cost": 0.4,
                        "metadata": {"topic": "ai", "source_type": "youtube"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": now.replace(microsecond=0).isoformat(),
                        "command": "report",
                        "actual_cost": 2.5,
                        "metadata": {"topic": "ai"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    (config.library_dir / "latest_run.json").write_text(
        json.dumps({"results": {"failed": 1}, "issues": [{"stage": "demo", "message": "problem"}]}),
        encoding="utf-8",
    )

    snapshot = dashboard_snapshot(config)

    assert snapshot["total_videos"] == 1
    assert snapshot["scan_videos"] == 1
    assert snapshot["topic_spend_rollups"][0][0] == "ai"
    assert snapshot["source_spend_rollups"][0][0] in {"report", "youtube"}
    assert snapshot["budget_messages"]
    assert snapshot["corpus_health_warnings"]
    assert snapshot["latest_results"]["failed"] == 1
    assert snapshot["topic_trends"]["ai"] == "trend: rising"


def test_dashboard_snapshot_includes_filesystem_only_corpus(config):
    topic = "direct-topic"
    channel = "Direct Channel"
    video_dir = config.video_dir(topic, channel, "video-1")
    video_dir.mkdir(parents=True)
    (video_dir / "metadata.json").write_text(
        json.dumps({"title": "Direct Video", "analysis_mode": "full"}),
        encoding="utf-8",
    )
    (video_dir / "insights.md").write_text("# Insights", encoding="utf-8")

    paper_dir = config.paper_dir(topic, "Direct Paper", "2401.00001")
    paper_dir.mkdir(parents=True)
    (paper_dir / "paper.md").write_text("# Paper", encoding="utf-8")

    page_dir = config.site_page_dir(topic, "example.com", "Direct Page", "page-1")
    page_dir.mkdir(parents=True)
    (page_dir / "content.md").write_text("# Page", encoding="utf-8")

    lib = Library(config)
    assert lib.get_topics() == []

    snapshot = dashboard_snapshot(config)

    assert snapshot["topics"] == [topic]
    assert snapshot["total_channels"] == 1
    assert snapshot["total_videos"] == 1
    assert snapshot["full_videos"] == 1
    assert snapshot["paper_count"] == 1
    assert snapshot["site_count"] == 1
    assert snapshot["page_count"] == 1
    assert lib.get_topics() == []


def test_dashboard_snapshot_uses_configured_cost_warning_policy(tmp_path):
    config = DistillConfig(
        distill_output_dir=tmp_path / "library",
        distill_cost_warning_daily_usd=1.0,
        distill_cost_workflow_budgets="report=1.50",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    (config.library_dir / "cost_log.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-06-03T12:00:00",
                "command": "report",
                "actual_cost": 2.5,
                "metadata": {"topic": "ai"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    snapshot = dashboard_snapshot(config)
    kinds = {warning["kind"] for warning in snapshot["cost_warnings"]}
    messages = [warning["message"] for warning in snapshot["cost_warnings"]]

    assert {"daily-threshold", "workflow-budget"} <= kinds
    assert any("above workflow budget $1.50" in message for message in messages)


def test_dashboard_helper_rollups_and_parsing():
    now = datetime.now().replace(microsecond=0)
    recent = (now - timedelta(days=1)).isoformat()
    stale = (now - timedelta(days=60)).isoformat()
    entries = [
        {"timestamp": recent, "actual_cost": 0.4, "command": "learn", "metadata": {"topic": "ai"}},
        {
            "timestamp": recent,
            "actual_cost": 2.5,
            "command": "report",
            "metadata": {"topic": "ai", "source_type": "report"},
        },
        {
            "timestamp": recent,
            "actual_cost": 0.7,
            "command": "site-batch",
            "metadata": {"topic": "vendor-site", "source_type": "website"},
        },
        {"timestamp": stale, "actual_cost": 99, "command": "learn", "metadata": {"topic": "old"}},
    ]

    assert parse_run_datetime(recent) is not None
    assert parse_run_datetime("not-a-date") is None
    assert format_run_timestamp(recent) != "unknown"
    assert format_run_timestamp("") == "unknown"
    assert topic_spend_last_days(entries, "ai", days=30) == 2.9
    assert topic_recent_costs(entries, "ai", limit=2) == [0.4, 2.5] or topic_recent_costs(
        entries, "ai", limit=2
    ) == [2.5, 0.4]
    assert topic_cost_rollups(entries, days=30, limit=2)[0][0] == "ai"
    assert {source for source, _, _ in source_cost_rollups(entries, days=30)} == {
        "youtube",
        "report",
        "website",
    }
    assert entry_source_type({"command": "site-batch", "metadata": {}}) == "website"
    assert entry_source_type({"command": "report", "metadata": {}}) == "report"


def test_dashboard_data_parser_helpers_handle_structural_fallbacks(tmp_path):
    assert duration_str(None) == "?"
    assert duration_str(42) == "42s"
    assert duration_str(125) == "2m05s"
    assert duration_str(3661) == "1h01m"
    assert strip_frontmatter("---\ntitle: One\n---\nBody\n") == "Body"
    assert strip_frontmatter("---\nunterminated") == "---\nunterminated"

    malformed = tmp_path / "bad.json"
    malformed.write_text("{bad json", encoding="utf-8")
    assert read_json_dict(malformed) == {}
    assert read_json_dict(tmp_path / "missing.json") == {}

    log_file = tmp_path / "cost_log.jsonl"
    log_file.write_text('{"actual_cost": 1}\n', encoding="utf-8")
    log_file.chmod(0)
    try:
        # On Unix this reaches the OSError branch. On Windows the owner can
        # still read the file, so the assertion accepts the parsed fallback too.
        assert load_recent_cost_runs(log_file) in ([], [{"actual_cost": 1}])
    finally:
        log_file.chmod(0o600)

    bad_time = {"timestamp": "not-a-date", "actual_cost": 3, "metadata": {"topic": "ai"}}
    stale_time = {
        "timestamp": (datetime.now() - timedelta(days=60)).isoformat(),
        "actual_cost": 5,
        "metadata": {"topic": "ai"},
    }
    bad_cost = {
        "timestamp": datetime.now().isoformat(),
        "actual_cost": "not-money",
        "metadata": {"topic": "ai"},
        "command": "learn",
    }
    no_topic = {
        "timestamp": datetime.now().isoformat(),
        "actual_cost": 2,
        "metadata": {},
        "command": "learn",
    }
    assert format_run_timestamp("not-a-date") == "not-a-date"
    assert parse_run_datetime("2026-06-01T00:00:00+00:00").tzinfo is None
    assert topic_spend_last_days([bad_time, stale_time], "ai") == 0.0
    assert topic_recent_costs([bad_time], "ai") == []
    assert topic_cost_rollups([bad_time, bad_cost, no_topic], days=30) == []
    assert source_cost_rollups([bad_time, bad_cost], days=30) == []


def test_dashboard_data_private_numeric_helpers_and_cost_log_read_errors(tmp_path, monkeypatch):
    assert _dashboard_data._float_value(object(), default=2.5) == 2.5
    assert _dashboard_data._int_value(object(), default=7) == 7

    log_file = tmp_path / "cost_log.jsonl"
    log_file.write_text('{"actual_cost": 1}\n', encoding="utf-8")
    original_read_text = Path.read_text

    def read_text(path: Path, *args, **kwargs):
        if path == log_file:
            raise OSError("locked")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    assert load_recent_cost_runs(log_file) == []


def test_topic_watch_budget_messages_and_stale_detection(config):
    lib = Library(config)
    lib.add_to_topic_watchlist(
        "ai-daily",
        "AI daily",
        topic="ai",
        cadence="daily",
        limit=10,
        report=True,
        max_run_cost=1.0,
        monthly_budget=2.0,
    )
    entry = lib.get_topic_watch_entry("ai-daily")
    assert entry is not None
    assert collect_stale_topic_watches([entry]) == ["ai-daily has never run"]

    now = datetime.now().replace(microsecond=0)
    entries = [
        {
            "timestamp": now.isoformat(),
            "actual_cost": 3.0,
            "metadata": {"topic": "ai"},
            "command": "learn",
        },
        {
            "timestamp": (now - timedelta(days=1)).isoformat(),
            "actual_cost": 0.5,
            "metadata": {"topic": "ai"},
            "command": "learn",
        },
        {
            "timestamp": (now - timedelta(days=2)).isoformat(),
            "actual_cost": 0.4,
            "metadata": {"topic": "ai"},
            "command": "learn",
        },
    ]

    messages = topic_watch_budget_messages(entry, entries)
    assert any("max-run budget" in message for message in messages)
    assert any("monthly spend" in message for message in messages)
    assert any("spend spike" in message for message in messages)

    safe_entry = SimpleNamespace(
        name="safe",
        topic="ai",
        limit=1,
        report=False,
        max_run_cost=None,
        monthly_budget=100.0,
    )
    assert topic_watch_budget_messages(safe_entry, []) == []


def test_stale_topic_watch_states_cover_invalid_stale_and_fresh_entries():
    stale_weekly = (datetime.now() - timedelta(days=9)).replace(microsecond=0).isoformat()
    fresh_daily = (datetime.now() - timedelta(hours=12)).replace(microsecond=0).isoformat()
    entries = [
        SimpleNamespace(name="invalid", cadence="daily", last_run_at="not-a-date"),
        SimpleNamespace(name="weekly", cadence="weekly", last_run_at=stale_weekly),
        SimpleNamespace(name="fresh", cadence="daily", last_run_at=fresh_daily),
    ]

    stale = collect_stale_topic_watches(entries)

    assert "invalid has invalid last-run state" in stale
    assert "weekly is stale for its weekly cadence" in stale
    assert not any("fresh" in item for item in stale)


def test_load_latest_payload_and_site_section_state(config):
    latest_run = config.library_dir / "latest_run.json"
    latest_run.parent.mkdir(parents=True, exist_ok=True)
    latest_run.write_text('{"results":{"ok":1}}', encoding="utf-8")
    assert load_latest_run_payload(config.library_dir) == {"results": {"ok": 1}}

    pages = [
        SitePage(
            url="https://example.com/topic/ai/one",
            final_url="https://example.com/topic/ai/one",
            title="One",
            site_name="example.com",
            page_type="topic",
            text="Body",
        ),
        SitePage(
            url="https://example.com/topic/ai/two",
            final_url="https://example.com/topic/ai/two",
            title="Two",
            site_name="example.com",
            page_type="research",
            text="Body",
        ),
    ]

    state = build_site_section_state(pages)
    assert state == [
        {
            "section": "topic/ai",
            "page_count": 2,
            "urls": [
                "https://example.com/topic/ai/one",
                "https://example.com/topic/ai/two",
            ],
            "page_types": ["research", "topic"],
        }
    ]


def test_site_manifest_parser_preserves_section_change_fields(tmp_path):
    manifest_path = tmp_path / "site.json"
    manifest_path.write_text(
        json.dumps(
            {
                "sections": [
                    {
                        "section": "topic/ai",
                        "page_count": 2,
                        "urls": ["https://example.com/a", "https://example.com/b"],
                        "page_types": ["docs", "research"],
                        "last_crawled_at": "2026-06-28T12:00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert _load_site_manifest(manifest_path) == {
        "sections": [
            {
                "section": "topic/ai",
                "page_count": 2,
                "urls": ["https://example.com/a", "https://example.com/b"],
                "page_types": ["docs", "research"],
                "last_crawled_at": "2026-06-28T12:00:00",
            }
        ]
    }


def test_cost_helpers_handle_missing_and_invalid_data(tmp_path):
    log_file = tmp_path / "cost_log.jsonl"
    # Mix in valid-JSON-but-non-object lines ([], a scalar): these must be
    # skipped, not kept, or sum_recent_cost's entry.get(...) crashes the dashboard.
    log_file.write_text(
        '\n{"actual_cost": 1.25}\nnot-json\n[]\n42\n{"actual_cost": "bad"}\n',
        encoding="utf-8",
    )

    recent = load_recent_cost_runs(log_file, limit=5)
    assert len(recent) == 2
    assert all(isinstance(r, dict) for r in recent)
    assert load_all_cost_runs(tmp_path / "missing.jsonl") == []
    assert sum_recent_cost(recent) == 1.25


def test_topic_watch_estimation_helpers(config):
    lib = Library(config)
    lib.add_to_topic_watchlist(
        "ai-daily",
        "AI daily",
        topic="ai",
        cadence="daily",
        limit=10,
        report=True,
        max_run_cost=1.0,
        monthly_budget=2.0,
    )
    lib.add_to_topic_watchlist(
        "ai-lite",
        "AI lite",
        topic="ai",
        cadence="weekly",
        limit=5,
        report=False,
    )
    watches = lib.get_topic_watchlist()

    from distill.pipeline.costs import estimate_stage_cost, report_deep_research_estimate

    video = estimate_stage_cost("video_full")
    report = report_deep_research_estimate()
    # watches[0]: limit 10 + report; watches[1]: limit 5, no report.
    assert round(estimate_topic_watch_cost(watches[0]), 4) == round(10 * video + report, 4)
    assert round(estimated_topic_watch_sweep(watches), 4) == round(
        10 * video + report + 5 * video, 4
    )

    from distill.llm.router import RouterConfig

    local = RouterConfig(provider="ollama", fast_model="qwen2.5:14b")
    assert estimate_topic_watch_cost(watches[0], router_config=local) == report
    assert estimated_topic_watch_sweep(watches, router_config=local) == report


def test_corpus_counting_and_recent_artifacts(config):
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "report.md").write_text("# Report", encoding="utf-8")
    (topic_dir / "brief.md").write_text("# Brief", encoding="utf-8")
    (topic_dir / "topic_synthesis.md").write_text("# Synth", encoding="utf-8")
    site_dir = config.site_dir("ai", "example.com")
    page_dir = config.site_page_dir("ai", "example.com", "Page One")
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "content.md").write_text("content", encoding="utf-8")
    (site_dir / "synthesis.md").write_text("# Site synth", encoding="utf-8")
    paper_dir = config.paper_dir("ai", "Memory Systems", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "paper.md").write_text("# Paper", encoding="utf-8")

    assert count_site_corpus(config, ["ai"]) == (1, 1)
    assert count_paper_corpus(config, ["ai"]) == 1
    assert count_topic_outputs(config, ["ai"]) == (1, 1, 1)

    artifacts = collect_recent_artifacts(config, ["ai"], limit=10)
    assert any(kind == "site synthesis" for _, kind, _ in artifacts)
    assert any(kind == "report" for _, kind, _ in artifacts)


def test_collect_recent_artifacts_skips_unreadable_stat(config, monkeypatch):
    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    artifact = topic_dir / "ai_Topic_Synthesis.md"
    artifact.write_text("# synth", encoding="utf-8")
    original_exists = Path.exists
    original_stat = Path.stat

    def exists(path: Path, *args, **kwargs):
        if path == artifact:
            return True
        return original_exists(path, *args, **kwargs)

    def stat(path: Path, *args, **kwargs):
        if path == artifact:
            raise OSError("locked")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(Path, "stat", stat)

    assert collect_recent_artifacts(config, ["ai"]) == []


def test_corpus_counting_skips_missing_files_and_empty_directories(config):
    sites_root = config.sites_dir("ai")
    sites_root.mkdir(parents=True, exist_ok=True)
    (sites_root / "not-a-site.txt").write_text("skip", encoding="utf-8")
    (sites_root / "empty-site").mkdir()

    papers_root = config.papers_dir("ai")
    papers_root.mkdir(parents=True, exist_ok=True)
    (papers_root / "not-a-paper.txt").write_text("skip", encoding="utf-8")
    (papers_root / "empty-paper").mkdir()

    assert count_site_corpus(config, ["missing", "ai"]) == (1, 0)
    assert count_paper_corpus(config, ["missing", "ai"]) == 0
    assert count_topic_outputs(config, ["missing"]) == (0, 0, 0)


def test_topic_change_history_and_labels(config):
    history_path = config.topic_dir("ai") / "change_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(
            [
                '{"generated_at":"2026-04-10T08:00:00","summary":"fresh","counts":{"videos":2,"pages":1,"papers":0,"outputs":1}}',
                '{"generated_at":"2026-04-09T08:00:00","summary":"older","counts":{"videos":1,"pages":1,"papers":0,"outputs":0}}',
                "bad-json",
            ]
        ),
        encoding="utf-8",
    )

    history = load_topic_change_history(config, "ai")
    assert history[0]["summary"] == "fresh"
    assert topic_trend_label(config, "ai") == "trend: rising"


def test_topic_change_history_handles_missing_cooling_and_steady_labels(config):
    assert load_topic_change_history(config, "missing") == []
    assert topic_trend_label(config, "missing") is None

    history_path = config.topic_dir("cooling") / "change_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(
            [
                '{"generated_at":"2026-04-10T08:00:00","summary":"fresh","counts":{"videos":1,"pages":0,"papers":0,"outputs":0}}',
                '{"generated_at":"2026-04-09T08:00:00","summary":"older","counts":{"videos":2,"pages":1,"papers":0,"outputs":0}}',
            ]
        ),
        encoding="utf-8",
    )
    assert topic_trend_label(config, "cooling") == "trend: cooling"

    history_path = config.topic_dir("steady") / "change_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(
            [
                '{"generated_at":"2026-04-10T08:00:00","summary":"fresh","counts":{"videos":1,"pages":1,"papers":0,"outputs":0}}',
                '{"generated_at":"2026-04-09T08:00:00","summary":"older","counts":{"videos":2,"pages":0,"papers":0,"outputs":0}}',
                '{"generated_at":"2026-04-08T08:00:00","summary":"bad","counts":{"videos":"bad","pages":0,"papers":0,"outputs":0}}',
            ]
        ),
        encoding="utf-8",
    )
    assert topic_trend_label(config, "steady") == "trend: steady"


def test_topic_change_history_returns_empty_on_read_error(config, monkeypatch):
    history_path = config.topic_dir("ai") / "change_history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text('{"generated_at":"2026-04-10T08:00:00"}', encoding="utf-8")
    original_read_text = Path.read_text

    def read_text(path: Path, *args, **kwargs):
        if path == history_path:
            raise OSError("locked")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    assert load_topic_change_history(config, "ai") == []


def test_collect_topic_changes_reports_quiet_watched_topics(config):
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@Empty", "Empty")
    lib.add_to_topic_watchlist("ai-daily", "AI daily", topic="ai", cadence="daily")
    baseline = (datetime.now() - timedelta(days=2)).replace(microsecond=0).isoformat()
    lib.mark_topic_watch_run("ai-daily", baseline)
    videos_dir = config.videos_dir("ai", "Empty")
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "not-a-video.txt").write_text("skip", encoding="utf-8")
    sites_root = config.sites_dir("ai")
    sites_root.mkdir(parents=True, exist_ok=True)
    (sites_root / "not-a-site.txt").write_text("skip", encoding="utf-8")
    pages_dir = config.site_dir("ai", "empty-site") / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "not-a-page.txt").write_text("skip", encoding="utf-8")

    changes = collect_topic_changes(config, lib, ["ai"], lib.get_topic_watchlist(), limit=5)

    assert changes[0][0] == "ai"
    assert changes[0][1].startswith("quiet since")


def test_collect_topic_changes_skips_unreadable_change_stats(config, monkeypatch):
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestChannel", "TestChannel")
    baseline = datetime.now() - timedelta(days=1)

    video_insights = config.video_dir("ai", "TestChannel", "vid001") / "insights.md"
    video_insights.parent.mkdir(parents=True, exist_ok=True)
    video_insights.write_text("insight", encoding="utf-8")
    page_content = config.site_page_dir("ai", "example.com", "Page") / "content.md"
    page_content.parent.mkdir(parents=True, exist_ok=True)
    page_content.write_text("content", encoding="utf-8")
    site_synthesis = config.site_dir("ai", "example.com") / "ai_example.com_Site_Synthesis.md"
    site_synthesis.write_text("synthesis", encoding="utf-8")
    topic_report = config.topic_dir("ai") / "ai_Report.md"
    topic_report.write_text("report", encoding="utf-8")

    unreadable = {video_insights, page_content, site_synthesis, topic_report}
    original_exists = Path.exists
    original_stat = Path.stat

    def exists(path: Path, *args, **kwargs):
        if path in unreadable:
            return True
        return original_exists(path, *args, **kwargs)

    def stat(path: Path, *args, **kwargs):
        if path in unreadable:
            raise OSError("locked")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setattr(Path, "stat", stat)

    assert collect_topic_changes(config, lib, ["ai"], [], limit=5) == []

    lib.add_to_topic_watchlist("ai-daily", "AI daily", topic="ai", cadence="daily")
    lib.mark_topic_watch_run("ai-daily", baseline.replace(microsecond=0).isoformat())

    changes = collect_topic_changes(config, lib, ["ai"], lib.get_topic_watchlist(), limit=5)
    assert changes[0][1].startswith("quiet since")


def test_corpus_health_warning_limits_and_directory_skips(config):
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@Empty", "Empty")
    lib.add_channel("ai", "https://www.youtube.com/@Thin", "Thin")

    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    stale_synthesis = topic_dir / "ai_Topic_Synthesis.md"
    stale_synthesis.write_text("# stale", encoding="utf-8")
    old = (datetime.now() - timedelta(days=120)).timestamp()
    os.utime(stale_synthesis, (old, old))
    assert collect_corpus_health_warnings(config, lib, ["ai"], limit=1) == [
        "ai topic synthesis is stale (120d old)"
    ]

    stale_synthesis.unlink()
    video_dir = config.video_dir("ai", "Thin", "vid001")
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir.parent / "not-a-video.txt").write_text("skip", encoding="utf-8")
    (video_dir / "metadata.json").write_text(json.dumps({"title": "Thin Video"}), encoding="utf-8")
    (video_dir / "insights.md").write_text("brief", encoding="utf-8")
    video_warnings = collect_corpus_health_warnings(
        config, lib, ["ai"], limit=1, include_thin_transcripts=False
    )
    assert video_warnings == ["ai / Thin: Thin Video insights look thin (5 chars)"]


def test_site_and_paper_health_warning_limits(config):
    lib = Library(config)

    sites_root = config.sites_dir("ai")
    sites_root.mkdir(parents=True, exist_ok=True)
    (sites_root / "not-a-site.txt").write_text("skip", encoding="utf-8")
    site_dir = config.site_dir("ai", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "site.json").write_text(
        json.dumps(
            {
                "sections": [
                    {
                        "section": "docs",
                        "last_crawled_at": (datetime.now() - timedelta(days=45))
                        .replace(microsecond=0)
                        .isoformat(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert collect_corpus_health_warnings(config, lib, ["ai"], limit=1) == [
        "ai / example.com: section docs is stale (45d old)"
    ]

    (site_dir / "site.json").unlink()
    pages_dir = site_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "not-a-page.txt").write_text("skip", encoding="utf-8")
    page_dir = config.site_page_dir("ai", "example.com", "Thin Page")
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "metadata.json").write_text(json.dumps({"title": "Thin Page"}), encoding="utf-8")
    (page_dir / "insights.md").write_text("tiny", encoding="utf-8")
    assert collect_corpus_health_warnings(config, lib, ["ai"], limit=1) == [
        "ai / example.com: Thin Page page insights look thin (4 chars)"
    ]

    (page_dir / "insights.md").unlink()
    papers_dir = config.papers_dir("ai")
    papers_dir.mkdir(parents=True, exist_ok=True)
    (papers_dir / "not-a-paper.txt").write_text("skip", encoding="utf-8")
    paper_dir = config.paper_dir("ai", "Thin Paper", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text(json.dumps({"title": "Thin Paper"}), encoding="utf-8")
    (paper_dir / "insights.md").write_text("tiny", encoding="utf-8")
    assert collect_corpus_health_warnings(config, lib, ["ai"], limit=1) == [
        "ai: Thin Paper paper insights look thin (4 chars)"
    ]


def test_corpus_health_warnings_tolerate_unreadable_insights(config, monkeypatch):
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@Video", "Video")

    video_insights = config.video_dir("ai", "Video", "vid001") / "insights.md"
    video_insights.parent.mkdir(parents=True, exist_ok=True)
    video_insights.write_text("brief", encoding="utf-8")
    page_insights = config.site_page_dir("ai", "example.com", "Page") / "insights.md"
    page_insights.parent.mkdir(parents=True, exist_ok=True)
    page_insights.write_text("tiny", encoding="utf-8")
    paper_insights = config.paper_dir("ai", "Paper", "2602.12670") / "insights.md"
    paper_insights.parent.mkdir(parents=True, exist_ok=True)
    paper_insights.write_text("tiny", encoding="utf-8")

    unreadable = {video_insights, page_insights, paper_insights}
    original_read_text = Path.read_text

    def read_text(path: Path, *args, **kwargs):
        if path in unreadable:
            raise OSError("locked")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    assert (
        collect_corpus_health_warnings(
            config,
            lib,
            ["ai"],
            include_thin_transcripts=False,
        )
        == []
    )


def test_stale_synthesis_warning_uses_source_relative_freshness(config):
    topic_dir = config.topic_dir("ai")
    insight_path = topic_dir / "papers" / "p1" / "p1_Insights.md"
    insight_path.parent.mkdir(parents=True, exist_ok=True)
    insight_path.write_text(
        '---\ngenerated_at: "2026-06-10T12:00:00"\n---\n\nInsight',
        encoding="utf-8",
    )
    synthesis_path = topic_dir / "ai_Corpus_Synthesis.md"
    synthesis_path.write_text(
        '---\ngenerated_at: "2026-04-01T12:00:00"\n---\n\nSynthesis',
        encoding="utf-8",
    )

    warnings = stale_synthesis_warnings(config, ["ai"])

    assert len(warnings) == 1
    assert "ai ai_Corpus_Synthesis.md predates 1 newer source(s)" in warnings[0]
    assert "distill corpus ai" in warnings[0]


def test_stale_synthesis_warning_respects_limit(config):
    for topic in ("ai", "ml"):
        topic_dir = config.topic_dir(topic)
        insight_path = topic_dir / "papers" / "p1" / "p1_Insights.md"
        insight_path.parent.mkdir(parents=True, exist_ok=True)
        insight_path.write_text(
            '---\ngenerated_at: "2026-06-10T12:00:00"\n---\n\nInsight',
            encoding="utf-8",
        )
        synthesis_path = topic_dir / f"{topic}_Corpus_Synthesis.md"
        synthesis_path.write_text(
            '---\ngenerated_at: "2026-04-01T12:00:00"\n---\n\nSynthesis',
            encoding="utf-8",
        )

    warnings = stale_synthesis_warnings(config, ["ai", "ml"], limit=1)

    assert len(warnings) == 1


def test_collect_topic_changes_and_corpus_warnings(config):
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestChannel", "TestChannel")
    lib.add_to_topic_watchlist(
        "ai-daily",
        "AI daily",
        topic="ai",
        cadence="daily",
        limit=5,
        report=False,
    )
    lib.mark_topic_watch_run(
        "ai-daily",
        (datetime.now() - timedelta(days=10)).replace(microsecond=0).isoformat(),
    )

    video_dir = config.video_dir("ai", "TestChannel", "vid001")
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "metadata.json").write_text(
        json.dumps({"title": "Long Video", "duration": 3600}), encoding="utf-8"
    )
    (video_dir / "transcript.txt").write_text("short", encoding="utf-8")
    (video_dir / "insights.md").write_text("brief", encoding="utf-8")

    site_dir = config.site_dir("ai", "example.com")
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "site.json").write_text(
        json.dumps(
            {
                "sections": [
                    {
                        "section": "topic/ai",
                        "last_crawled_at": (datetime.now() - timedelta(days=45))
                        .replace(microsecond=0)
                        .isoformat(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    page_dir = config.site_page_dir("ai", "example.com", "Thin Page")
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "content.md").write_text("content", encoding="utf-8")
    (page_dir / "metadata.json").write_text(json.dumps({"title": "Thin Page"}), encoding="utf-8")
    (page_dir / "insights.md").write_text("tiny", encoding="utf-8")
    (site_dir / "synthesis.md").write_text("# Fresh site synth", encoding="utf-8")

    paper_dir = config.paper_dir("ai", "Thin Paper", "2602.12670")
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "metadata.json").write_text(json.dumps({"title": "Thin Paper"}), encoding="utf-8")
    (paper_dir / "insights.md").write_text("tiny", encoding="utf-8")

    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Synth", encoding="utf-8")

    changes = collect_topic_changes(config, lib, ["ai"], lib.get_topic_watchlist(), limit=5)
    warnings = collect_corpus_health_warnings(config, lib, ["ai"], limit=10)

    assert changes[0][0] == "ai"
    assert "+1 video" in changes[0][1]
    assert "site synthesis" in changes[0][1]
    assert "synthesis refreshed" in changes[0][1]
    assert any("transcript looks thin" in warning for warning in warnings)
    assert any("page insights look thin" in warning for warning in warnings)
    assert any("paper insights look thin" in warning for warning in warnings)
    assert any("section topic/ai is stale" in warning for warning in warnings)
