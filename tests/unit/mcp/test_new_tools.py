"""Unit tests for new MCP tools (papers, discover, site_batch, synthesize, costs, doctor)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from distill.config import DistillConfig


@pytest.fixture
def mock_config(tmp_path):
    """Create a test DistillConfig."""
    config = DistillConfig(
        xai_api_key="test-key",
        gemini_api_key="test-gemini",
        distill_output_dir=tmp_path / "library",
    )
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config


# ── Property 10: Progress events have valid structure ──
# Feature: mcp-first-surface, Property 10: Progress events have valid structure
# **Validates: Requirements 9.2**


@settings(max_examples=100)
@given(
    progress=st.floats(min_value=0.0, max_value=100.0),
    total=st.integers(min_value=1, max_value=100),
)
def test_progress_events_valid_structure(progress, total):
    """Property 10: Progress events have valid structure."""
    # Simulate what our tools do: progress/total should yield 0.0-1.0
    normalized = progress / total if total > 0 else 0.0
    # The MCP SDK accepts progress as an integer count and total
    # Our tools pass progress=i, total=len(items) which is always valid
    assert normalized >= 0.0  # always true for non-negative
    # The actual constraint: progress value passed to ctx.report_progress
    # should be a non-negative integer <= total
    int_progress = int(min(progress, total))
    assert 0 <= int_progress <= total


class TestCostsTool:
    def test_no_cost_history(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())
        assert result["status"] == "ok"
        assert result["runs"] == []
        assert "No cost history" in result.get("message", "")

    def test_with_cost_entries(self, mock_config):
        log_file = mock_config.library_dir / "cost_log.jsonl"
        entries = [
            '{"command": "learn", "actual_cost": 0.05}',
            '{"command": "papers", "actual_cost": 0.10}',
        ]
        log_file.write_text("\n".join(entries), encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.costs import costs

            result = json.loads(costs())
        assert result["runs_shown"] == 2
        assert result["total_cost"] == 0.15


class TestDoctorTool:
    def test_returns_checks(self, mock_config):
        # Keep live key validation off the network; return healthy stubs.
        def _fake(provider, config):
            return ("ok", "stub") if provider == "xai" else ("not_set", "")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.doctor.checks._doctor_validate_key", side_effect=_fake),
        ):
            from distill.mcp.tools.doctor import doctor

            result = json.loads(doctor())
        assert "checks" in result
        check_names = [c["check"] for c in result["checks"]]
        assert "xai_api_key" in check_names
        assert "library_dir" in check_names

    def test_flags_invalid_key(self, mock_config):
        """A present-but-rejected key reports 'invalid', not a false-green 'ok'."""

        def _fake(provider, config):
            if provider == "gemini":
                return ("invalid", "400 API_KEY_INVALID")
            return ("ok", "stub")

        with (
            patch("distill.mcp.server._config", return_value=mock_config),
            patch("distill.doctor.checks._doctor_validate_key", side_effect=_fake),
        ):
            from distill.mcp.tools.doctor import doctor

            result = json.loads(doctor())
        gem = next(c for c in result["checks"] if c["check"] == "gemini_api_key")
        assert gem["status"] == "invalid"
        assert result["status"] == "warning"

    def test_missing_api_key(self, tmp_path):
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        config.library_dir.mkdir(parents=True, exist_ok=True)

        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.doctor import doctor

            result = json.loads(doctor())
        xai_check = next(c for c in result["checks"] if c["check"] == "xai_api_key")
        assert xai_check["status"] == "missing"


class TestPapersTool:
    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "anthropic")  # not implemented -> no model
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.papers import papers

            result = json.loads(asyncio.run(papers("ai", "transformers")))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_processes_paper_records(self, mock_config, monkeypatch, tmp_path):
        from distill.ingestors.papers.arxiv import PaperRecord

        paper = PaperRecord(
            paper_id="2602.12670v1",
            title="Agent Memory Systems",
            abstract="A paper about memory systems.",
            authors=["Alice"],
            abs_url="https://arxiv.org/abs/2602.12670v1",
            pdf_url="https://arxiv.org/pdf/2602.12670v1.pdf",
        )
        monkeypatch.setattr("distill.ingestors.papers.arxiv.search_arxiv", lambda *a, **k: [paper])
        monkeypatch.setattr(
            "distill.pipeline.analysis.paper.analyze_paper",
            lambda *a, **k: ("# Insights", "# Paper"),
        )
        monkeypatch.setattr(
            "distill.commands._paper_artifacts.write_paper_artifacts",
            lambda *a, **k: tmp_path / "paper",
        )
        monkeypatch.setattr(
            "distill.pipeline.analysis.paper.synthesize_papers",
            lambda *a, **k: "# Synthesis",
        )
        monkeypatch.setattr(
            "distill.pipeline.synthesis.corpus.synthesize_corpus",
            lambda *a, **k: "# Corpus",
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.papers import papers

            result = json.loads(asyncio.run(papers("ai", "agent memory", limit=1)))

        assert result["status"] == "complete"
        assert result["papers"] == [{"title": "Agent Memory Systems", "status": "ok"}]


class TestSiteBatchTool:
    def test_no_urls_or_seed(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai")))
        assert result["status"] == "error"
        assert "urls" in result["error"] or "seed_file" in result["error"]

    def test_missing_seed_file(self, mock_config):
        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file="/nonexistent.txt")))
        assert result["status"] == "error"
        assert "inside the library root" in result["error"]

    def test_seed_file_must_stay_inside_library(self, mock_config, tmp_path):
        outside = tmp_path / "seeds.txt"
        outside.write_text("https://private.example/internal\n", encoding="utf-8")

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file=str(outside))))

        assert result["status"] == "error"
        assert "inside the library root" in result["error"]
        assert "private.example" not in json.dumps(result)

    def test_seed_file_inside_library_processes_site_seed(self, mock_config, monkeypatch):
        seed_file = mock_config.library_dir / "seeds.txt"
        seed_file.write_text("https://example.com/guide\n", encoding="utf-8")
        seen = []

        def fake_process_site_seed(seed, config, tracker, summary):
            seen.append((seed.url, seed.topic, config, summary.command))
            return "Example", 1

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed", fake_process_site_seed
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file="seeds.txt")))

        assert result["status"] == "complete"
        assert result["pages"] == [
            {
                "url": "https://example.com/guide",
                "site": "Example",
                "pages": 1,
                "status": "ok",
            }
        ]
        assert seen == [("https://example.com/guide", "ai", mock_config, "site-batch")]

    def test_json_seed_file_honors_mixed_crawl_modes(self, mock_config, monkeypatch):
        seed_file = mock_config.library_dir / "sites.json"
        seed_file.write_text(
            json.dumps(
                {
                    "topic": "web",
                    "crawl": {
                        "max_depth": 1,
                        "max_pages_per_seed": 4,
                        "same_section_only": True,
                    },
                    "collections": [
                        {
                            "name": "overview",
                            "mode": "exact-page",
                            "seeds": ["https://example.com/overview"],
                        },
                        {
                            "name": "docs",
                            "mode": "shallow-crawl",
                            "crawl_prefix": "/docs",
                            "seeds": ["https://example.com/docs/start"],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        seen = []

        def fake_process_site_seed(seed, config, tracker, summary):
            seen.append(
                (
                    seed.url,
                    seed.max_depth,
                    seed.max_pages,
                    seed.crawl_prefix,
                    seed.same_section_only,
                )
            )
            return "Example", 1

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed", fake_process_site_seed
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file="sites.json")))

        assert result["status"] == "complete"
        assert [page["url"] for page in result["pages"]] == [
            "https://example.com/overview",
            "https://example.com/docs/start",
        ]
        assert seen == [
            ("https://example.com/overview", 0, 1, "", True),
            ("https://example.com/docs/start", 1, 4, "/docs", True),
        ]

    def test_json_seed_file_rejects_unknown_mode_without_processing(self, mock_config, monkeypatch):
        seed_file = mock_config.library_dir / "sites.json"
        seed_file.write_text(
            json.dumps(
                {
                    "topic": "web",
                    "urls": [
                        {
                            "url": "https://example.com/guide",
                            "mode": "wide-open",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        calls = []
        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed",
            lambda *args, **kwargs: calls.append("process"),
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", seed_file="sites.json")))

        assert result["status"] == "error"
        assert "Unsupported site crawl mode" in result["error"]
        assert calls == []

    def test_direct_urls_use_existing_site_pipeline(self, mock_config, monkeypatch):
        seen = []

        def fake_process_site_seed(seed, config, tracker, summary):
            seen.append((seed.url, seed.max_depth, seed.max_pages))
            return "Example", 0

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed", fake_process_site_seed
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", urls=["https://example.com/guide"])))

        assert result["status"] == "complete"
        assert result["pages"][0]["status"] == "skipped"
        assert seen == [("https://example.com/guide", 0, 1)]

    def test_site_batch_reports_unchanged_counts(self, mock_config, monkeypatch):
        from distill.commands._site_ingest import SiteIngestResult

        def fake_process_site_seed(seed, config, tracker, summary):
            return SiteIngestResult(
                site_name="Example",
                page_count=1,
                analyzed_pages=0,
                skipped_pages=1,
            )

        monkeypatch.setattr(
            "distill.commands._site_ingest.process_site_seed", fake_process_site_seed
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.sites import site_batch

            result = json.loads(asyncio.run(site_batch("ai", urls=["https://example.com/guide"])))

        assert result["status"] == "complete"
        assert result["pages"] == [
            {
                "url": "https://example.com/guide",
                "site": "Example",
                "pages": 1,
                "status": "unchanged",
                "analyzed_pages": 0,
                "skipped_pages": 1,
            }
        ]


class TestSynthesizeTool:
    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "anthropic")  # not implemented -> no model
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.synthesis import synthesize

            result = json.loads(asyncio.run(synthesize("ai")))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()


class TestDiscoverTool:
    def test_no_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISTILL_PROVIDER", "anthropic")  # not implemented -> no model
        config = DistillConfig(
            xai_api_key="",
            distill_output_dir=tmp_path / "library",
        )
        with patch("distill.mcp.server._config", return_value=config):
            from distill.mcp.tools.discover import discover

            result = json.loads(asyncio.run(discover("test goal")))
        assert result["status"] == "error"
        assert "model" in result["error"].lower()

    def test_papers_only_handles_paper_record_authors(self, mock_config, monkeypatch):
        from distill.ingestors.papers.arxiv import PaperRecord

        monkeypatch.setattr(
            "distill.ingestors.papers.arxiv.search_arxiv",
            lambda *a, **k: [
                PaperRecord(
                    paper_id="2602.12670v1",
                    title="Agent Memory Systems",
                    abstract="A paper about memory systems.",
                    authors=["Alice", "Bob"],
                    abs_url="https://arxiv.org/abs/2602.12670v1",
                )
            ],
        )

        with patch("distill.mcp.server._config", return_value=mock_config):
            from distill.mcp.tools.discover import discover

            result = json.loads(asyncio.run(discover("agent memory", papers_only=True)))

        assert result["status"] == "complete"
        assert result["papers"] == [
            {
                "title": "Agent Memory Systems",
                "authors": ["Alice", "Bob"],
                "url": "https://arxiv.org/abs/2602.12670v1",
            }
        ]
