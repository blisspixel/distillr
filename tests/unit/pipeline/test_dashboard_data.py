import json
from datetime import datetime, timedelta

from distill.ingestors.sites.scraper import SitePage
from distill.library import Library
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
    entry_source_type,
    estimate_topic_watch_cost,
    estimated_topic_watch_sweep,
    format_run_timestamp,
    load_all_cost_runs,
    load_latest_run_payload,
    load_recent_cost_runs,
    load_topic_change_history,
    parse_run_datetime,
    source_cost_rollups,
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
