"""Paper analysis and synthesis helpers."""

from __future__ import annotations

from distill.config import DistillConfig
from distill.costs import CostTracker
from distill.paper_ingest import (
    PaperRecord,
    build_paper_document,
    fetch_paper_pdf_text,
)
from distill.prompts import paper_insight_prompt, paper_topic_synthesis_prompt
from distill.site_analysis import _call_grok, _get_client


def analyze_paper(
    paper: PaperRecord,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> tuple[str, str]:
    """Run per-paper analysis and return (insights_md, paper_document).

    Fetches the arXiv PDF and includes the extracted text in the document passed
    to the LLM. Falls back to abstract-only if PDF fetch/extract fails. The
    returned paper_document is the exact content the LLM saw, suitable for
    writing to paper.md so artifacts match what was analyzed.
    """
    client = _get_client(config)
    model = config.xai_model_for("site")
    pdf_text = fetch_paper_pdf_text(paper.pdf_url)
    document = build_paper_document(paper, pdf_text=pdf_text)
    prompt = paper_insight_prompt(paper.title, paper.paper_id, document)
    result = _call_grok(client, prompt, model=model, tracker=tracker, call_type="paper")
    safe_title = paper.title.replace('"', '\\"')
    source_mode = "full_pdf" if pdf_text else "abstract_only"
    insights = (
        f"---\n"
        f'paper_title: "{safe_title}"\n'
        f"paper_id: {paper.paper_id}\n"
        f"source: {paper.source}\n"
        f"url: {paper.abs_url}\n"
        f"analyzed_by: {model}\n"
        f"source_mode: {source_mode}\n"
        "---\n\n"
        f"{result}\n"
    )
    return insights, document


def synthesize_papers(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    papers_dir = config.papers_dir(topic)
    if not papers_dir.exists():
        return ""

    paper_summaries: dict[str, str] = {}
    for paper_dir in sorted(papers_dir.iterdir()):
        if not paper_dir.is_dir():
            continue
        insights_file = paper_dir / "insights.md"
        if insights_file.exists():
            paper_summaries[paper_dir.name] = insights_file.read_text(encoding="utf-8")

    if not paper_summaries:
        return ""

    client = _get_client(config)
    model = config.xai_model_for("site")
    synthesis = _call_grok(
        client,
        paper_topic_synthesis_prompt(topic, paper_summaries),
        model=model,
        tracker=tracker,
        call_type="paper_synthesis",
    )
    output = config.topic_dir(topic) / "paper_synthesis.md"
    output.write_text(synthesis, encoding="utf-8")
    return synthesis
