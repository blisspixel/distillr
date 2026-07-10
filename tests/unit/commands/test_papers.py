"""Hermetic boundary tests for the ``paper`` and ``papers`` commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from distill import cli
from distill.commands import papers as papers_cmd
from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import PaperRecord
from distill.pipeline.costs import BudgetExceededError
from distill.pipeline.ranking import RankedPaper

runner = CliRunner()


def _paper(
    paper_id: str = "2607.00001v1",
    *,
    title: str = "Verified Research Systems",
    authors: list[str] | None = None,
) -> PaperRecord:
    return PaperRecord(
        paper_id=paper_id,
        title=title,
        abstract="A substantive paper about verifiable research systems.",
        authors=["Ada Researcher"] if authors is None else authors,
        categories=["cs.AI"],
        published_at="2026-07-01T00:00:00Z",
        abs_url=f"https://arxiv.org/abs/{paper_id}",
    )


def _ranked(record: PaperRecord) -> RankedPaper:
    return RankedPaper(
        paper=record,
        final_score=0.9,
        relevance_score=0.9,
        depth_score=0.8,
        novelty_score=0.7,
        credibility_score=0.9,
        rationale="Directly relevant",
    )


@pytest.fixture
def paper_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DistillConfig:
    """Isolate all default external seams before invoking either command."""
    config = DistillConfig(
        xai_api_key=SecretStr("test-key"),
        distill_output_dir=tmp_path / "library",
    )
    expected_config = config

    def allow_budget(received_config, command, projected):
        assert received_config is config
        assert command in {"paper", "papers"}
        assert projected >= 0

    def apply_verify(mode):
        assert mode == ""

    def expand_query(query, *, config: DistillConfig, tracker, expand):
        assert config is expected_config
        return [query]

    monkeypatch.setattr(papers_cmd, "get_config", lambda: config)
    monkeypatch.setattr(papers_cmd, "_require_model", lambda: None)
    monkeypatch.setattr(papers_cmd, "_apply_verify_override", apply_verify)
    monkeypatch.setattr(
        papers_cmd,
        "enforce_projected_workflow_budget",
        allow_budget,
    )
    monkeypatch.setattr(
        papers_cmd,
        "_expand_paper_queries",
        expand_query,
    )
    monkeypatch.setattr(papers_cmd, "model_available", lambda workload: True)
    monkeypatch.setattr(
        papers_cmd,
        "synthesize_papers",
        lambda topic, config, tracker=None: "",
    )
    monkeypatch.setattr(
        papers_cmd,
        "synthesize_corpus",
        lambda topic, config, tracker=None: "",
    )
    monkeypatch.setattr(
        papers_cmd,
        "_run_concepts_after_ingest",
        lambda topic, tracker=None: None,
    )
    return config


def _invoke_papers(*extra: str):
    return runner.invoke(
        cli.app,
        [
            "papers",
            "verified research",
            "--topic",
            "research",
            "--limit",
            "2",
            "--no-expand",
            *extra,
        ],
    )


def test_paper_fetch_failure_refuses_before_analysis(paper_config, monkeypatch):
    analysis_calls: list[PaperRecord] = []
    monkeypatch.setattr(papers_cmd, "fetch_arxiv_paper", lambda target: None)
    monkeypatch.setattr(
        papers_cmd,
        "analyze_paper",
        lambda record, config, *, tracker, intent: analysis_calls.append(record),
    )

    result = runner.invoke(cli.app, ["paper", "missing", "--topic", "research"])

    assert result.exit_code == 1
    assert analysis_calls == []
    assert "Could not fetch paper metadata" in result.output


def test_paper_without_authors_or_optional_syntheses_completes(paper_config, monkeypatch, tmp_path):
    record = _paper(authors=[])
    paper_dir = tmp_path / "paper-artifacts"
    paper_dir.mkdir()
    artifacts: list[tuple[str, str | None]] = []
    monkeypatch.setattr(papers_cmd, "fetch_arxiv_paper", lambda target: record)
    monkeypatch.setattr(
        papers_cmd,
        "analyze_paper",
        lambda received, config, *, tracker, intent: ("# Insights", "# Paper"),
    )
    monkeypatch.setattr(
        papers_cmd,
        "_write_paper_artifacts",
        lambda topic, received, config, insights, document: paper_dir,
    )

    def find(path, kind, *, identity=None):
        artifacts.append((kind, identity))
        return path / f"{kind}.md"

    monkeypatch.setattr(papers_cmd, "find_artifact", find)

    result = runner.invoke(cli.app, ["paper", record.paper_id, "--topic", "research"])

    assert result.exit_code == 0, result.output
    assert record.title in result.output
    assert "Ada Researcher" not in result.output
    assert artifacts == [("paper", None), ("insights", None)]


@pytest.mark.parametrize(
    ("paper_synthesis", "corpus_synthesis", "expected_optional"),
    [
        ("", "", []),
        ("paper synthesis", "", [("paper_synthesis", "research")]),
        ("", "corpus synthesis", [("corpus_synthesis", "research")]),
        (
            "paper synthesis",
            "corpus synthesis",
            [
                ("paper_synthesis", "research"),
                ("corpus_synthesis", "research"),
            ],
        ),
    ],
)
def test_paper_records_optional_synthesis_outputs(
    paper_config,
    monkeypatch,
    tmp_path,
    paper_synthesis,
    corpus_synthesis,
    expected_optional,
):
    record = _paper()
    paper_dir = tmp_path / "paper-artifacts"
    paper_dir.mkdir()
    artifacts: list[tuple[str, str | None]] = []
    monkeypatch.setattr(papers_cmd, "fetch_arxiv_paper", lambda target: record)
    monkeypatch.setattr(
        papers_cmd,
        "analyze_paper",
        lambda received, config, *, tracker, intent: ("# Insights", "# Paper"),
    )
    monkeypatch.setattr(
        papers_cmd,
        "_write_paper_artifacts",
        lambda topic, received, config, insights, document: paper_dir,
    )
    monkeypatch.setattr(
        papers_cmd,
        "synthesize_papers",
        lambda topic, config, tracker=None: paper_synthesis,
    )
    monkeypatch.setattr(
        papers_cmd,
        "synthesize_corpus",
        lambda topic, config, tracker=None: corpus_synthesis,
    )

    def find(path, kind, *, identity=None):
        artifacts.append((kind, identity))
        return path / f"{kind}.md"

    monkeypatch.setattr(papers_cmd, "find_artifact", find)

    result = runner.invoke(cli.app, ["paper", record.paper_id, "--topic", "research"])

    assert result.exit_code == 0, result.output
    assert artifacts == [("paper", None), ("insights", None), *expected_optional]


def test_papers_rejects_invalid_sort_before_configuration(monkeypatch):
    config_calls: list[str] = []
    monkeypatch.setattr(papers_cmd, "get_config", lambda: config_calls.append("config"))

    result = runner.invoke(cli.app, ["papers", "query", "--sort", "oldest"])

    assert result.exit_code == 1
    assert config_calls == []
    assert "--sort must be 'relevance' or 'date'" in result.output


def test_papers_rejects_invalid_rigor_before_configuration(monkeypatch):
    config_calls: list[str] = []
    monkeypatch.setattr(papers_cmd, "get_config", lambda: config_calls.append("config"))

    result = runner.invoke(cli.app, ["papers", "query", "--rigor", "absolute"])

    assert result.exit_code == 1
    assert config_calls == []
    assert "Unknown --rigor 'absolute'" in result.output


def test_papers_query_fallback_persists_lens_and_warns_on_model_fallback(paper_config, monkeypatch):
    record = _paper()
    observed: dict[str, object] = {}

    def expand_query(query, *, config, tracker, expand):
        observed["expand"] = expand
        return []

    monkeypatch.setattr(papers_cmd, "_expand_paper_queries", expand_query)

    def search(query, *, limit, sort):
        observed.update(search_query=query, search_limit=limit, search_sort=sort)
        return [record]

    def persist(config, topic, query, lens):
        observed.update(topic=topic, lens=lens)

    def rerank(query, candidates, config, *, tracker, top_n, use_llm):
        observed.update(top_n=top_n, use_llm=use_llm)
        return [_ranked(record)]

    monkeypatch.setattr(papers_cmd, "search_arxiv_papers", search)
    monkeypatch.setattr(papers_cmd, "_persist_lens", persist)
    monkeypatch.setattr(papers_cmd, "rerank_papers", rerank)
    monkeypatch.setattr(papers_cmd, "model_available", lambda workload: False)
    monkeypatch.setattr(papers_cmd, "_display_ranked_papers", lambda ranked, *, title: None)

    result = _invoke_papers("--preview", "--lens", "research")

    assert result.exit_code == 0, result.output
    assert observed == {
        "topic": "research",
        "lens": "research",
        "search_query": "verified research",
        "search_limit": 10,
        "search_sort": "relevance",
        "expand": False,
        "top_n": 2,
        "use_llm": True,
    }
    assert "deterministic ranking fallback" in result.output


def test_papers_multi_query_uses_bounded_multi_search(paper_config, monkeypatch):
    record = _paper()
    observed: dict[str, object] = {}

    def expand_query(query, *, config, tracker, expand):
        observed["expand"] = expand
        return ["query one", "query two"]

    monkeypatch.setattr(papers_cmd, "_expand_paper_queries", expand_query)

    def search(queries, *, limit_per_query, sort):
        observed.update(
            queries=queries,
            limit_per_query=limit_per_query,
            sort=sort,
        )
        return [record]

    def rerank(query, candidates, config, *, tracker, top_n, use_llm):
        observed.update(top_n=top_n, use_llm=use_llm)
        return [_ranked(record)]

    monkeypatch.setattr(papers_cmd, "search_arxiv_multi", search)
    monkeypatch.setattr(papers_cmd, "rerank_papers", rerank)
    monkeypatch.setattr(papers_cmd, "_display_ranked_papers", lambda ranked, *, title: None)

    result = runner.invoke(
        cli.app,
        [
            "papers",
            "verified research",
            "--topic",
            "research",
            "--limit",
            "2",
            "--preview",
            "--no-rerank",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed == {
        "queries": ["query one", "query two"],
        "expand": True,
        "limit_per_query": 10,
        "sort": "relevance",
        "top_n": 2,
        "use_llm": False,
    }


def test_papers_search_exception_reports_issue(paper_config, monkeypatch):
    def fail_search(query, *, limit, sort):
        raise RuntimeError("arXiv unavailable")

    monkeypatch.setattr(papers_cmd, "search_arxiv_papers", fail_search)

    result = _invoke_papers("--no-rerank")

    assert result.exit_code == 1
    assert "arXiv search failed: arXiv unavailable" in result.output
    assert "paper-search" in result.output


def test_papers_empty_search_refuses(paper_config, monkeypatch):
    monkeypatch.setattr(
        papers_cmd,
        "search_arxiv_papers",
        lambda query, *, limit, sort: [],
    )

    result = _invoke_papers("--no-rerank")

    assert result.exit_code == 1
    assert "No papers found for query" in result.output


def test_papers_converged_corpus_is_a_clean_no_op(paper_config, monkeypatch):
    from distill.library import ingested as ingested_module
    from distill.pipeline import discovery as discovery_module

    record = _paper()
    rerank_calls: list[str] = []
    monkeypatch.setattr(
        papers_cmd,
        "search_arxiv_papers",
        lambda query, *, limit, sort: [record],
    )
    monkeypatch.setattr(
        ingested_module,
        "ingested_source_ids",
        lambda topic_dir: {record.paper_id},
    )
    monkeypatch.setattr(
        discovery_module,
        "filter_ingested_candidates",
        lambda papers, videos, *, ingested: ([], [], 1),
    )

    def unexpected_rerank(query, candidates, config, *, tracker, top_n, use_llm):
        rerank_calls.append(query)
        return []

    monkeypatch.setattr(
        papers_cmd,
        "rerank_papers",
        unexpected_rerank,
    )

    result = _invoke_papers("--preview", "--no-rerank")

    assert result.exit_code == 0, result.output
    assert rerank_calls == []
    assert "Excluded 1 paper(s) already in 'research'" in result.output
    assert "Corpus is current" in result.output


def test_papers_isolates_item_failure_and_runs_requested_concepts(
    paper_config, monkeypatch, tmp_path
):
    failed = _paper("2607.00001v1", title="Broken Analysis")
    succeeded = _paper("2607.00002v1", title="Successful Analysis")
    analyzed: list[str] = []
    issues: list[dict[str, object]] = []
    concepts: list[str] = []
    artifacts: list[tuple[str, str | None]] = []
    paper_dir = tmp_path / "paper-output"
    paper_dir.mkdir()

    monkeypatch.setattr(
        papers_cmd,
        "search_arxiv_papers",
        lambda query, *, limit, sort: [failed, succeeded],
    )
    monkeypatch.setattr(
        papers_cmd,
        "rerank_papers",
        lambda query, candidates, config, *, tracker, top_n, use_llm: [
            _ranked(failed),
            _ranked(succeeded),
        ],
    )
    monkeypatch.setattr(papers_cmd, "_display_ranked_papers", lambda ranked, *, title: None)

    def analyze(record, config, *, tracker, intent):
        analyzed.append(record.paper_id)
        if record is failed:
            raise RuntimeError("analysis failed")
        return "# Insights", "# Paper"

    def record_issue(summary, *, stage, exc, context, details):
        issues.append(
            {
                "stage": stage,
                "error": str(exc),
                "context": context,
                "details": details,
            }
        )

    monkeypatch.setattr(papers_cmd, "analyze_paper", analyze)
    monkeypatch.setattr(
        papers_cmd,
        "_write_paper_artifacts",
        lambda topic, record, config, insights, document: paper_dir,
    )

    def find(path, kind, *, identity=None):
        artifacts.append((kind, identity))
        return path / f"{kind}.md"

    monkeypatch.setattr(papers_cmd, "find_artifact", find)
    monkeypatch.setattr(papers_cmd.cli_shared, "record_exception_issue", record_issue)
    monkeypatch.setattr(
        papers_cmd,
        "_run_concepts_after_ingest",
        lambda topic, *, tracker: concepts.append(topic),
    )

    result = _invoke_papers("--no-rerank", "--concepts")

    assert result.exit_code == 0, result.output
    assert analyzed == [failed.paper_id, succeeded.paper_id]
    assert issues == [
        {
            "stage": "paper-analysis",
            "error": "analysis failed",
            "context": failed.title,
            "details": {"topic": "research", "paper_id": failed.paper_id},
        }
    ]
    assert concepts == ["research"]
    assert artifacts == [("paper", None), ("insights", None)]
    assert "failed 1" in result.output
    assert "completed 1/2" in result.output


@pytest.mark.parametrize(
    ("paper_synthesis", "corpus_synthesis", "expected_optional"),
    [
        ("", "", []),
        ("paper synthesis", "", [("paper_synthesis", "research")]),
        ("", "corpus synthesis", [("corpus_synthesis", "research")]),
        (
            "paper synthesis",
            "corpus synthesis",
            [
                ("paper_synthesis", "research"),
                ("corpus_synthesis", "research"),
            ],
        ),
    ],
)
def test_papers_records_optional_syntheses_without_running_concepts(
    paper_config,
    monkeypatch,
    tmp_path,
    paper_synthesis,
    corpus_synthesis,
    expected_optional,
):
    record = _paper()
    paper_dir = tmp_path / "paper-output"
    paper_dir.mkdir()
    artifacts: list[tuple[str, str | None]] = []
    concepts: list[str] = []
    monkeypatch.setattr(
        papers_cmd,
        "search_arxiv_papers",
        lambda query, *, limit, sort: [record],
    )
    monkeypatch.setattr(
        papers_cmd,
        "rerank_papers",
        lambda query, candidates, config, *, tracker, top_n, use_llm: [_ranked(record)],
    )
    monkeypatch.setattr(papers_cmd, "_display_ranked_papers", lambda ranked, *, title: None)
    monkeypatch.setattr(
        papers_cmd,
        "analyze_paper",
        lambda received, config, *, tracker, intent: ("# Insights", "# Paper"),
    )
    monkeypatch.setattr(
        papers_cmd,
        "_write_paper_artifacts",
        lambda topic, received, config, insights, document: paper_dir,
    )
    monkeypatch.setattr(
        papers_cmd,
        "synthesize_papers",
        lambda topic, config, tracker=None: paper_synthesis,
    )
    monkeypatch.setattr(
        papers_cmd,
        "synthesize_corpus",
        lambda topic, config, tracker=None: corpus_synthesis,
    )
    monkeypatch.setattr(
        papers_cmd,
        "_run_concepts_after_ingest",
        lambda topic, *, tracker: concepts.append(topic),
    )

    def find(path, kind, *, identity=None):
        artifacts.append((kind, identity))
        return path / f"{kind}.md"

    monkeypatch.setattr(papers_cmd, "find_artifact", find)

    result = _invoke_papers("--no-rerank")

    assert result.exit_code == 0, result.output
    assert artifacts == [("paper", None), ("insights", None), *expected_optional]
    assert concepts == []


def test_papers_budget_crossing_is_a_hard_stop(paper_config, monkeypatch):
    first = _paper("2607.00001v1", title="Budget Crossing")
    second = _paper("2607.00002v1", title="Must Not Run")
    issue_calls: list[str] = []
    analyzed: list[str] = []
    writes: list[str] = []
    syntheses: list[str] = []
    concepts: list[str] = []
    paper_dir = paper_config.library_dir / "budget-output"
    paper_dir.mkdir(parents=True)
    monkeypatch.setattr(
        papers_cmd,
        "search_arxiv_papers",
        lambda query, *, limit, sort: [first, second],
    )
    monkeypatch.setattr(
        papers_cmd,
        "rerank_papers",
        lambda query, candidates, config, *, tracker, top_n, use_llm: [
            _ranked(first),
            _ranked(second),
        ],
    )
    monkeypatch.setattr(papers_cmd, "_display_ranked_papers", lambda ranked, *, title: None)

    def exceed_budget(record, config, *, tracker, intent):
        analyzed.append(record.paper_id)
        if record is first:
            raise BudgetExceededError(spent=1.01, budget=1.0)
        return "# Insights", "# Paper"

    monkeypatch.setattr(papers_cmd, "analyze_paper", exceed_budget)

    def write_artifacts(topic, record, config, insights, document):
        writes.append(record.paper_id)
        return paper_dir

    monkeypatch.setattr(
        papers_cmd,
        "_write_paper_artifacts",
        write_artifacts,
    )
    monkeypatch.setattr(
        papers_cmd,
        "synthesize_papers",
        lambda topic, config, tracker=None: syntheses.append("paper"),
    )
    monkeypatch.setattr(
        papers_cmd,
        "synthesize_corpus",
        lambda topic, config, tracker=None: syntheses.append("corpus"),
    )
    monkeypatch.setattr(
        papers_cmd,
        "_run_concepts_after_ingest",
        lambda topic, *, tracker: concepts.append(topic),
    )

    def record_issue(summary, *, stage, exc, context, details):
        issue_calls.append(stage)

    monkeypatch.setattr(papers_cmd.cli_shared, "record_exception_issue", record_issue)

    result = _invoke_papers("--no-rerank", "--concepts")

    assert isinstance(result.exception, BudgetExceededError)
    assert analyzed == [first.paper_id]
    assert writes == []
    assert syntheses == []
    assert concepts == []
    assert issue_calls == []
