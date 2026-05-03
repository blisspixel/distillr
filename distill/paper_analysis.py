"""Paper analysis and synthesis helpers."""

from __future__ import annotations

from distill.artifacts import base_frontmatter, find_artifact, tags_for, write_markdown_artifact
from distill.config import DistillConfig, router_config_from_distill
from distill.costs import CostTracker, TokenUsage
from distill.llm import call as llm_call
from distill.paper_ingest import (
    PaperRecord,
    build_paper_document,
    fetch_paper_pdf_text,
)
from distill.prompts import paper_insight_prompt, paper_topic_synthesis_prompt


def analyze_paper(
    paper: PaperRecord,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> tuple[str, str]:
    """Run per-paper analysis and return (insights_md, paper_document).

    Fetches the arXiv PDF and includes the extracted text in the document passed
    to the LLM. Falls back to abstract-only if PDF fetch/extract fails. The
    returned paper_document is the exact content the LLM saw, suitable for
    writing to the paper artifact so outputs match what was analyzed.
    """
    rc = router_config_from_distill(config)
    pdf_text = fetch_paper_pdf_text(paper.pdf_url)
    document = build_paper_document(paper, pdf_text=pdf_text)
    prompt = paper_insight_prompt(paper.title, paper.paper_id, document)
    response = llm_call(rc, workload_tag="site", prompt=prompt, call_type="paper")
    result = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="paper",
            )
        )
    safe_title = paper.title.replace('"', '\\"')
    source_mode = "full_pdf" if pdf_text else "abstract_only"
    insights = (
        f"---\n"
        f'paper_title: "{safe_title}"\n'
        f"paper_id: {paper.paper_id}\n"
        f"source: {paper.source}\n"
        f"url: {paper.abs_url}\n"
        f"analyzed_by: {response.model}\n"
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
        insights_file = find_artifact(paper_dir, "insights")
        if insights_file.exists():
            paper_summaries[paper_dir.name] = insights_file.read_text(encoding="utf-8")

    if not paper_summaries:
        return ""

    rc = router_config_from_distill(config)
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=paper_topic_synthesis_prompt(topic, paper_summaries),
        call_type="paper_synthesis",
    )
    synthesis = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="paper_synthesis",
            )
        )
    write_markdown_artifact(
        config.topic_dir(topic),
        "paper_synthesis",
        synthesis,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="paper-synthesis",
            title=f"Paper synthesis: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "paper"),
            confidence="corpus-consensus",
            extra={"legacy_filename": "paper_synthesis.md"},
        ),
    )
    return synthesis
