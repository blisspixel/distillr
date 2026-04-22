from rich.console import Console

from distill.costs import CostTracker, TokenUsage
from distill.summary import (
    ETATracker,
    RunSummary,
    VideoResult,
    _file_size,
    display_estimate,
    display_summary,
)


def test_run_summary_counts_successful_full_and_shorts(tmp_path):
    summary = RunSummary(command="learn")
    summary.add_result(VideoResult("v1", "Video", True, is_short=False))
    summary.add_result(VideoResult("v2", "Short", True, is_short=True))
    summary.add_result(VideoResult("v3", "Failed", False, error="boom"))

    assert summary.passed == 2
    assert summary.failed == 1
    assert summary.full_count == 1
    assert summary.shorts_count == 1


def test_add_output_only_keeps_existing_paths(tmp_path):
    summary = RunSummary(command="learn")
    existing = tmp_path / "exists.md"
    existing.write_text("x", encoding="utf-8")

    summary.add_output(existing)
    summary.add_output(existing)
    summary.add_output(tmp_path / "missing.md")

    assert summary.output_files == [existing.resolve()]


def test_add_issue_deduplicates_identical_entries():
    summary = RunSummary(command="learn")

    summary.add_issue("topic-synthesis", "failed", context="ai")
    summary.add_issue("topic-synthesis", "failed", context="ai")

    assert summary.issue_count == 1


def test_add_exception_records_traceback_and_type():
    summary = RunSummary(command="learn")

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        summary.add_exception("topic-synthesis", exc, context="ai", details={"topic": "ai"})

    issue = summary.issues[0]
    assert issue.exception_type == "RuntimeError"
    assert "RuntimeError: boom" in issue.traceback_text
    assert issue.details == (("topic", "ai"),)


def test_display_summary_includes_outputs_failures_and_cost(tmp_path, monkeypatch):
    summary = RunSummary(command="learn")
    summary.start_time = 100.0
    summary.add_result(VideoResult("v1", "Video One", True, is_short=False))
    summary.add_result(VideoResult("v2", "Short One", True, is_short=True))
    summary.add_result(VideoResult("v3", "Video Fail", False, error="No transcript"))
    summary.add_issue("topic-synthesis", "No topic synthesis output written", context="ai")
    output_file = tmp_path / "insights.md"
    output_file.write_text("hello", encoding="utf-8")
    summary.add_output(output_file)

    tracker = CostTracker()
    tracker.record(
        TokenUsage(
            prompt_tokens=100,
            completion_tokens=50,
            model="grok-4-1-fast-reasoning",
            call_type="pass1",
        )
    )
    logged = {}
    monkeypatch.setattr("distill.costs.save_run_log", lambda **kwargs: logged.update(kwargs))
    monkeypatch.setattr("distill.summary.time.time", lambda: 112.5)

    console = Console(record=True, width=120)
    display_summary(summary, cost_tracker=tracker, console=console, log_dir=tmp_path)
    rendered = console.export_text()

    assert "1 video" in rendered
    assert "1 Short" in rendered
    assert "1 failed" in rendered
    assert "1 issue" in rendered
    assert "insights.md" in rendered
    assert "Video Fail" in rendered
    assert "topic-synthesis" in rendered
    assert logged["command"] == "learn"


def test_display_summary_writes_run_artifacts(tmp_path, monkeypatch):
    summary = RunSummary(command="learn")
    summary.start_time = 100.0
    summary.add_result(VideoResult("v1", "Video Fail", False, error="No transcript"))
    try:
        raise ValueError("bad report")
    except ValueError as exc:
        summary.add_exception("report", exc, context="ai", details={"scope": "topic"})
    output_file = tmp_path / "report.md"
    output_file.write_text("hello", encoding="utf-8")
    summary.add_output(output_file)

    monkeypatch.setattr("distill.summary.time.time", lambda: 112.5)

    console = Console(record=True, width=120)
    display_summary(summary, console=console, log_dir=tmp_path)

    run_log = tmp_path / "run_log.jsonl"
    latest = tmp_path / "latest_run_errors.md"
    latest_json = tmp_path / "latest_run.json"

    assert run_log.exists()
    assert latest.exists()
    assert latest_json.exists()
    run_log_text = run_log.read_text(encoding="utf-8")
    latest_text = latest.read_text(encoding="utf-8")
    latest_json_text = latest_json.read_text(encoding="utf-8")

    assert '"command": "learn"' in run_log_text
    assert '"exception_type": "ValueError"' in latest_json_text
    assert '"traceback":' in latest_json_text
    assert "Timestamp:" in latest_text
    assert "ValueError" in latest_text
    assert "bad report" in latest_text
    assert "Video Fail" in latest_text


def test_display_summary_noop_when_empty():
    console = Console(record=True, width=120)

    display_summary(RunSummary(command="learn"), console=console)

    assert console.export_text() == ""


def test_file_size_formats_units(tmp_path):
    small = tmp_path / "small.txt"
    small.write_bytes(b"a" * 10)
    medium = tmp_path / "medium.txt"
    medium.write_bytes(b"a" * 2048)

    assert _file_size(small) == "10 B"
    assert _file_size(medium).endswith("KB")


class TestETATracker:
    def test_tick_increments_completed(self, monkeypatch):
        import distill.summary as summary_mod

        call_count = [0]
        base = 1000.0

        def fake_time():
            call_count[0] += 1
            return base + call_count[0] * 5.0

        monkeypatch.setattr(summary_mod.time, "time", fake_time)

        tracker = ETATracker(total=3)
        start = tracker.start()
        tracker.tick(start)
        assert tracker.completed == 1

    def test_eta_str_empty_when_no_times(self):
        tracker = ETATracker(total=5)
        assert tracker.eta_str == ""

    def test_eta_str_empty_when_done(self):
        tracker = ETATracker(total=1, completed=1)
        tracker._times = [5.0]
        assert tracker.eta_str == ""

    def test_eta_str_shows_seconds(self):
        tracker = ETATracker(total=3, completed=1)
        tracker._times = [10.0]
        eta = tracker.eta_str
        assert eta == "~20s left"

    def test_eta_str_shows_minutes(self):
        tracker = ETATracker(total=5, completed=1)
        tracker._times = [30.0]
        eta = tracker.eta_str
        assert eta == "~2m left"

    def test_avg_seconds_empty(self):
        tracker = ETATracker(total=3)
        assert tracker.avg_seconds == 0

    def test_avg_seconds(self):
        tracker = ETATracker(total=3)
        tracker._times = [10.0, 20.0]
        assert tracker.avg_seconds == 15.0

    def test_progress_str_without_eta(self):
        tracker = ETATracker(total=3)
        result = tracker.progress_str()
        assert "1/3" in result

    def test_progress_str_with_eta(self):
        tracker = ETATracker(total=5, completed=2)
        tracker._times = [10.0, 10.0]
        result = tracker.progress_str("analyzing")
        assert "3/5" in result
        assert "left" in result
        assert "analyzing" in result


class TestDisplayEstimate:
    def test_full_videos(self):
        console = Console(record=True, width=120)
        display_estimate(full_videos=3, console=console)
        rendered = console.export_text()
        assert "3 videos" in rendered

    def test_shorts(self):
        console = Console(record=True, width=120)
        display_estimate(shorts=2, console=console)
        rendered = console.export_text()
        assert "2 Shorts" in rendered

    def test_scan_videos(self):
        console = Console(record=True, width=120)
        display_estimate(scan_videos=4, console=console)
        rendered = console.export_text()
        assert "4 videos (scan)" in rendered

    def test_include_report(self):
        console = Console(record=True, width=120)
        display_estimate(full_videos=1, include_report=True, console=console)
        rendered = console.export_text()
        assert "Deep Research" in rendered

    def test_no_videos(self):
        console = Console(record=True, width=120)
        display_estimate(console=console)
        rendered = console.export_text()
        assert "0 videos" in rendered

    def test_synthesis_calls_only(self):
        console = Console(record=True, width=120)
        display_estimate(synthesis_calls=3, console=console)
        rendered = console.export_text()
        assert "synthesis" in rendered.lower()


def test_file_size_megabytes(tmp_path):
    large = tmp_path / "large.txt"
    large.write_bytes(b"a" * (2 * 1024 * 1024))
    assert _file_size(large).endswith("MB")


def test_display_summary_long_elapsed(tmp_path, monkeypatch):
    summary = RunSummary(command="learn")
    summary.start_time = 100.0
    summary.add_result(VideoResult("v1", "Video One", True, is_short=False))
    monkeypatch.setattr("distill.summary.time.time", lambda: 300.0)

    console = Console(record=True, width=120)
    display_summary(summary, console=console)
    rendered = console.export_text()
    assert "3m" in rendered
