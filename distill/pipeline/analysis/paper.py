"""Paper analysis and synthesis helpers."""

from __future__ import annotations

import logging

from distill.config import DistillConfig
from distill.ingestors.papers.arxiv import (
    PaperRecord,
    build_paper_document,
    fetch_paper_pdf_text,
)
from distill.library.intent import CorpusIntent
from distill.library.paths import (
    ProvenanceFields,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.chunking import chunk_content, estimate_tokens
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.synthesis import paper_insight_prompt, paper_topic_synthesis_prompt

logger = logging.getLogger(__name__)

__all__ = [
    "analyze_paper",
    "synthesize_papers",
]


def analyze_paper(
    paper: PaperRecord,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
    *,
    intent: CorpusIntent | None = None,
) -> tuple[str, str]:
    """Run per-paper analysis and return (insights_md, paper_document).

    Fetches the arXiv PDF and includes the extracted text in the document passed
    to the LLM. Falls back to abstract-only if PDF fetch/extract fails. The
    returned paper_document is the exact content the LLM saw, suitable for
    writing to the paper artifact so outputs match what was analyzed.

    ``router_config`` lets a caller (e.g. the eval harness) force a specific
    model/provider; defaults to the configured routing. ``intent`` selects the
    analysis lens and goal focus; ``None`` keeps the neutral default.
    """
    rc = router_config or RouterConfig()
    goal = intent.goal if intent else ""
    lens = intent.lens if intent else ""
    pdf_text = fetch_paper_pdf_text(paper.pdf_url)
    document = build_paper_document(paper, pdf_text=pdf_text)
    prompt = paper_insight_prompt(paper.title, paper.paper_id, document, goal=goal, lens=lens)

    # Check if content needs chunking based on context window
    content_tokens = estimate_tokens(document)
    # Default context window for cloud providers; adaptive chunking will be
    # fully wired in Phase 4 with provider metadata resolution.
    context_window = 1_000_000  # Conservative default for cloud
    threshold = int(context_window * 0.80)
    if content_tokens >= threshold:
        chunks = chunk_content(document, context_window)
        logger.debug(
            "Chunking decision: content_tokens=%d, window=%d, threshold=%d, "
            "decision=CHUNK, num_chunks=%d",
            content_tokens,
            context_window,
            threshold,
            len(chunks),
        )
        # For now, process first chunk only (multi-pass assembly comes in Phase 4)
        document = chunks[0].text
        prompt = paper_insight_prompt(paper.title, paper.paper_id, document, goal=goal, lens=lens)
    else:
        logger.debug(
            "Chunking decision: content_tokens=%d, window=%d, threshold=%d, decision=PASSTHROUGH",
            content_tokens,
            context_window,
            threshold,
        )

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
        f"model: {response.model}\n"
        f"model_version: {response.model}\n"
        f"temperature: 0.0\n"
        f'prompt_id: "analysis.paper.v2"\n'
        f"lens: {lens or 'general'}\n"
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

    rc = RouterConfig()
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
            synthesis_scope="corpus-consensus",
            extra={"legacy_filename": "paper_synthesis.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_IDS["synthesis.paper"],
            ),
        ),
    )
    return synthesis
