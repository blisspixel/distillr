"""Tests for per-item failure isolation in long ingest loops (0.12.10).

One crashed source must not kill a long mixed-source run: the failure is
recorded as a run issue, the loop continues, synthesis covers what landed,
and the summary prints the convergent-re-run resume hint. The spend cap
(BudgetExceededError) stays a hard stop -- swallowing it per-item would
defeat the MCP per-call budget.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rich.console import Console

from distill.commands import _discover_flow
from distill.commands._site_ingest import SiteIngestResult
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.ingestors.sites.scraper import SiteSeed
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.summary import RunSummary, display_summary


def _ranked_paper(paper_id: str, title: str):
    return SimpleNamespace(
        paper=PaperRecord(
            paper_id=paper_id,
            title=title,
            abstract="abstract",
            authors=["A"],
            abs_url=f"https://arxiv.org/abs/{paper_id}",
        )
    )


class TestPaperLoopIsolation:
    def _run(self, tmp_path, analyze_side_effect):
        config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "lib")
        summary = RunSummary(command="discover")
        ranked = [
            _ranked_paper("2601.00001v1", "good one"),
            _ranked_paper("2601.00002v1", "bad"),
            _ranked_paper("2601.00003v1", "good two"),
        ]
        with (
            patch.object(_discover_flow, "analyze_paper", side_effect=analyze_side_effect),
            patch.object(_discover_flow, "synthesize_papers", return_value="synth") as synth,
        ):
            _discover_flow._discover_ingest_papers("t", config, CostTracker(), summary, ranked)
        return summary, synth

    def test_one_failed_paper_does_not_kill_the_run(self, tmp_path):
        def analyze(paper, config, tracker=None, intent=None):
            if "bad" in paper.title:
                raise RuntimeError("PDF extraction exploded")
            return ("---\n---\ninsights", "document")

        summary, synth = self._run(tmp_path, analyze)

        issues = [i for i in summary.issues if i.stage == "paper-analysis"]
        assert len(issues) == 1
        assert "bad" in issues[0].context
        # The two good papers landed (paper + insights each).
        assert len(summary.output_files) >= 4
        # Synthesis still ran over what landed.
        synth.assert_called_once()

    def test_paper_progress_includes_failures_and_spend(self, tmp_path, capsys):
        def analyze(paper, config, tracker=None, intent=None):
            if "bad" in paper.title:
                raise RuntimeError("PDF extraction exploded")
            return ("---\n---\ninsights", "document")

        self._run(tmp_path, analyze)

        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert "paper 1/3" in out
        assert "paper 2/3" in out
        assert "paper 3/3" in out
        assert "completed 2/3" in out
        assert "failed 1" in out
        assert "spent $0.0000" in out

    def test_budget_exceeded_is_a_hard_stop(self, tmp_path):
        def analyze(paper, config, tracker=None, intent=None):
            raise BudgetExceededError(0.6, 0.5)

        with pytest.raises(BudgetExceededError):
            self._run(tmp_path, analyze)


class TestSiteLoopIsolation:
    def test_site_progress_continues_after_seed_failure(self, tmp_path, capsys):
        config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "lib")
        summary = RunSummary(command="discover")
        ranked = [
            SimpleNamespace(
                site_seed=SiteSeed(
                    url="https://bad.example.com/a",
                    topic="old",
                    discover_crawl=True,
                    max_depth=1,
                    max_pages=3,
                ),
                title="bad site",
            ),
            SimpleNamespace(
                site_seed=SiteSeed(url="https://good.example.com/b", topic="old"),
                title="good site",
            ),
        ]
        calls: list[SiteSeed] = []

        def process(seed, config, tracker, summary, scrape_only=False, ingest_attachments=False):
            calls.append(seed)
            if "bad" in seed.url:
                raise RuntimeError("crawl exploded")
            return SiteIngestResult(
                site_name="good.example.com",
                page_count=1,
                skipped_pages=1,
            )

        with (
            patch.object(_discover_flow, "_process_site_seed", side_effect=process),
            patch.object(_discover_flow, "synthesize_site_topic", return_value=None),
        ):
            _discover_flow._discover_ingest_sites(
                "web",
                config,
                CostTracker(),
                summary,
                ranked,
                ingest_attachments=False,
                has_videos=False,
            )

        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert [seed.topic for seed in calls] == ["web", "web"]
        assert calls[0].max_depth == 1
        assert calls[0].max_pages == 3
        assert calls[1].max_depth == 0
        assert calls[1].max_pages == 1
        assert "site 1/2" in out
        assert "site 2/2" in out
        assert "completed 1/2" in out
        assert "failed 1" in out
        assert "spent $0.0000" in out
        assert "phase skipped (1 unchanged)" in out
        issues = [i for i in summary.issues if i.stage == "site-ingest"]
        assert len(issues) == 1
        assert issues[0].context == "https://bad.example.com/a"


class TestVideoLoopIsolation:
    def test_one_crashed_video_does_not_kill_the_channel_sweep(self, tmp_path):
        from types import SimpleNamespace

        from distill.commands import _learning_flow

        config = DistillConfig(xai_api_key="t", distill_output_dir=tmp_path / "lib")

        def video(vid, title):
            return SimpleNamespace(
                video=SimpleNamespace(
                    video_id=vid,
                    title=title,
                    channel_name="chan",
                    channel_url="https://youtube.com/@chan",
                    duration=600,
                    upload_date="20260601",
                    url=f"https://youtube.com/watch?v={vid}",
                )
            )

        processed = []

        def fake_process_video(topic, channel, vid, config, tracker, summary, **kwargs):
            if vid.video_id == "v2":
                raise RuntimeError("yt-dlp exploded")
            processed.append(vid.video_id)
            return True

        captured: dict = {}

        def summary_factory(command):
            captured["summary"] = RunSummary(command=command)
            return captured["summary"]

        class FakeLib:
            def __init__(self, config):
                pass

            def add_channel(self, *a, **k):
                return True

        _learning_flow.process_learning_selection(
            "t",
            config,
            CostTracker(),
            [video("v1", "first"), video("v2", "crasher"), video("v3", "third")],
            save=False,
            report=False,
            test=False,
            generate_brief=False,
            library_factory=FakeLib,
            run_summary_factory=summary_factory,
            output_path=lambda *a, **k: tmp_path / "out",
            ensure_channel_context=lambda *a, **k: None,
            process_video=fake_process_video,
            synthesize_channel=lambda *a, **k: None,
            synthesize_topic=lambda *a, **k: None,
            synthesize_corpus=lambda *a, **k: None,
            run_scope_report=lambda *a, **k: None,
            generate_and_export_topic_brief=lambda *a, **k: None,
        )

        assert processed == ["v1", "v3"]
        issues = [i for i in captured["summary"].issues if i.stage == "video-analysis"]
        assert len(issues) == 1
        assert "crasher" in issues[0].context


class TestResumeHint:
    def _render(self, summary: RunSummary) -> str:
        console = Console(record=True, width=100)
        display_summary(summary, console=console)
        return console.export_text()

    @staticmethod
    def _normalize_console_text(text: str) -> str:
        # Rich may soft-wrap long hint lines at narrow console widths.
        return " ".join(text.split())

    def test_hint_printed_for_retryable_ingest_failures(self):
        summary = RunSummary(command="discover")
        summary.add_exception("paper-analysis", RuntimeError("x"), context="p")
        out = self._normalize_console_text(self._render(summary))
        assert "Re-run the same command" in out
        assert "already-ingested sources are skipped" in out

    def test_no_hint_for_unrelated_issues(self):
        summary = RunSummary(command="discover")
        summary.add_exception("corpus-synthesis", RuntimeError("x"), context="t")
        out = self._normalize_console_text(self._render(summary))
        assert "Re-run the same command" not in out
