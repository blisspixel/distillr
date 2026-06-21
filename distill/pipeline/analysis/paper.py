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
from distill.llm.metadata import ProviderMetadata, resolve_metadata_for_router
from distill.llm.router import RouterConfig
from distill.pipeline.analysis.chunking import chunk_content, estimate_tokens
from distill.pipeline.analysis.multipass import (
    PAPER_ANALYSIS_PASSES,
    merge_paper_pass_results,
    multi_pass_analysis,
)
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.synthesis import paper_insight_prompt, paper_topic_synthesis_prompt

logger = logging.getLogger(__name__)

__all__ = [
    "analyze_paper",
    "synthesize_papers",
]

_CHUNK_RESERVED_RATIO = 0.20
_PASSTHROUGH_THRESHOLD_RATIO = 0.80


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
    returned paper_document is always the full captured source (the receipt), even
    when analysis runs over chunked multipass passes.

    ``router_config`` lets a caller (e.g. the eval harness) force a specific
    model/provider; defaults to the configured routing. ``intent`` selects the
    analysis lens and goal focus; ``None`` keeps the neutral default.
    """
    rc = router_config or RouterConfig()
    goal = intent.goal if intent else ""
    lens = intent.lens if intent else ""
    pdf_text = fetch_paper_pdf_text(paper.pdf_url)
    document = build_paper_document(paper, pdf_text=pdf_text)
    source_mode = "full_pdf" if pdf_text else "abstract_only"

    metadata = resolve_metadata_for_router(rc, "analysis")
    provider_name = metadata.provider_name
    content_tokens = estimate_tokens(document)
    threshold = int(metadata.context_window * _PASSTHROUGH_THRESHOLD_RATIO)

    if content_tokens < threshold:
        logger.debug(
            "Paper analysis passthrough: tokens=%d window=%d provider=%s",
            content_tokens,
            metadata.context_window,
            provider_name,
        )
        body, model = _single_pass_analysis(
            paper,
            document,
            rc,
            goal=goal,
            lens=lens,
            tracker=tracker,
        )
        selection_modes = ""
    else:
        logger.debug(
            "Paper analysis multipass: tokens=%d window=%d chunks pending provider=%s",
            content_tokens,
            metadata.context_window,
            provider_name,
        )
        body, model, selection_modes = _multipass_analysis(
            paper,
            document,
            rc,
            metadata,
            goal=goal,
            lens=lens,
            tracker=tracker,
        )
        source_mode = "chunked_multipass"

    insights = _build_paper_insights(
        paper,
        body,
        model=model,
        source_mode=source_mode,
        lens=lens,
        chunk_selection_modes=selection_modes,
    )
    return insights, document


def _single_pass_analysis(
    paper: PaperRecord,
    document: str,
    rc: RouterConfig,
    *,
    goal: str,
    lens: str,
    tracker: CostTracker | None,
) -> tuple[str, str]:
    prompt = paper_insight_prompt(paper.title, paper.paper_id, document, goal=goal, lens=lens)
    response = llm_call(rc, workload_tag="site", prompt=prompt, call_type="paper")
    if tracker is not None:
        tracker.record(TokenUsage.from_response(response, call_type="paper"))
    return response.text.strip() + "\n", response.model


def _multipass_analysis(
    paper: PaperRecord,
    document: str,
    rc: RouterConfig,
    metadata: ProviderMetadata,
    *,
    goal: str,
    lens: str,
    tracker: CostTracker | None,
) -> tuple[str, str, str]:
    chunks = chunk_content(
        document,
        metadata.context_window,
        reserved_ratio=_CHUNK_RESERVED_RATIO,
    )
    multipass = multi_pass_analysis(
        chunks,
        rc,
        metadata,
        passes=PAPER_ANALYSIS_PASSES,
        tracker=tracker,
        goal=goal,
        lens=lens,
    )
    results = multipass.passes
    if not results:
        logger.warning(
            "Multipass produced no sections for %s; falling back to single pass on lead chunk",
            paper.paper_id,
        )
        lead = chunks[0].text if chunks else document
        body, model = _single_pass_analysis(
            paper,
            lead,
            rc,
            goal=goal,
            lens=lens,
            tracker=tracker,
        )
        return body, model, multipass.selection_modes

    model = _multipass_model_from_tracker(tracker) or rc.resolve("analysis")[1]
    body = merge_paper_pass_results(results, body="")
    return body, model, multipass.selection_modes


def _multipass_model_from_tracker(tracker: CostTracker | None) -> str:
    if tracker is None or not tracker.entries:
        return ""
    for entry in reversed(tracker.entries):
        if entry.call_type == "paper" and entry.model:
            return entry.model
    return tracker.entries[-1].model


def _build_paper_insights(
    paper: PaperRecord,
    body: str,
    *,
    model: str,
    source_mode: str,
    lens: str,
    chunk_selection_modes: str = "",
) -> str:
    safe_title = paper.title.replace('"', '\\"')
    prompt_id = PROMPT_IDS.get("analysis.paper", "analysis.paper.v2")
    selection_line = (
        f"chunk_selection_modes: {chunk_selection_modes}\n" if chunk_selection_modes else ""
    )
    return (
        f"---\n"
        f'paper_title: "{safe_title}"\n'
        f"paper_id: {paper.paper_id}\n"
        f"source: {paper.source}\n"
        f"url: {paper.abs_url}\n"
        f"analyzed_by: {model}\n"
        f"source_mode: {source_mode}\n"
        f"{selection_line}"
        f"model: {model}\n"
        f"model_version: {model}\n"
        f"temperature: 0.0\n"
        f'prompt_id: "{prompt_id}"\n'
        f"lens: {lens or 'general'}\n"
        "---\n\n"
        f"{body.rstrip()}\n"
    )


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
        tracker.record(TokenUsage.from_response(response, call_type="paper_synthesis"))

    from distill.pipeline.verify import run_synthesis_verify

    if run_synthesis_verify(
        config.topic_dir(topic),
        synthesis,
        "\n\n".join(paper_summaries.values()),
        verify_mode=config.distill_verify,
        identity=f"{topic}-paper-synthesis",
        insight_name=f"{topic} paper synthesis",
        source_name="per-paper insights",
        notify=logger.warning,
    ):
        logger.warning("paper synthesis for %s not written (verify strict)", topic)
        return ""
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

    try:
        from distill.library import claude_md

        claude_md.refresh_for_topic(config.library_dir, config.topic_dir(topic), topic)
    except Exception as exc:
        logger.debug("CLAUDE.md refresh skipped for %s: %s", topic, exc)

    return synthesis
