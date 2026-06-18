"""Local-file ingest orchestration.

The local-file counterpart to ``ingest_tweet``: extract text from an on-disk
document, write a raw artifact plus an ``_Insights.md`` under
``library/topics/<topic>/local/<slug>/``, and route through the same analysis
pipeline the network sources use. PDFs get the paper-analysis prompt; Markdown /
text / HTML get the page-analysis prompt. Closes the gap where the playbook
layer only updated from network ingestion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.local import extract_local_document
from distill.library.paths import (
    ProvenanceFields,
    artifact_path,
    base_frontmatter,
    slugify_title,
    tags_for,
    write_markdown_artifact,
    write_text_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.synthesis import paper_insight_prompt, site_page_insight_prompt

logger = logging.getLogger(__name__)

__all__ = ["LocalIngestResult", "ingest_local_file"]


@dataclass(slots=True)
class LocalIngestResult:
    """Paths and metadata from a local-file ingest."""

    document_path: Path
    insights_path: Path | None
    kind: str
    title: str
    slug: str


def ingest_local_file(
    path: Path,
    *,
    topic: str,
    config: DistillConfig,
    analyze: bool = True,
    tracker: CostTracker | None = None,
) -> LocalIngestResult:
    """Ingest a local document into ``topic``.

    Extracts the text, writes the raw document artifact, and (unless
    ``analyze`` is False) runs analysis and writes ``_Insights.md`` with full
    provenance. Cost is recorded to ``tracker`` when provided.
    """
    doc = extract_local_document(path)
    slug = slugify_title(doc.title, source_id=path.name)
    local_dir = config.topic_dir(topic) / "local" / slug

    document_path = write_text_artifact(local_dir, "content", doc.text, identity=slug)

    insights_path: Path | None = None
    if analyze:
        rc = RouterConfig()
        if doc.kind == "pdf":
            prompt = paper_insight_prompt(doc.title, path.name, doc.text)
        else:
            prompt = site_page_insight_prompt(doc.title, str(path), "local", doc.kind, doc.text)

        response = llm_call(rc, workload_tag="site", prompt=prompt, call_type="local")
        if tracker is not None:
            tracker.record(TokenUsage.from_response(response, call_type="local"))
        # Write-time verify hook: ground numeric claims against the extracted
        # document text *before* committing; strict mode refuses the write.
        from distill.pipeline.verify import resolve_verify_mode, run_verify_hook

        outcome = run_verify_hook(
            local_dir,
            response.text,
            doc.text,
            mode=resolve_verify_mode(config.distill_verify),
            identity=slug,
            insight_name=artifact_path(local_dir, "insights", identity=slug).name,
            source_name=document_path.name,
        )
        if outcome is not None and not outcome.report.ok:
            style = "red" if outcome.refused else "yellow"
            console.print(f"  [{style}]{outcome.summary_line}[/{style}]")
        if outcome is None or not outcome.refused:
            insights_path = write_markdown_artifact(
                local_dir,
                "insights",
                response.text,
                identity=slug,
                frontmatter=base_frontmatter(
                    artifact_type="insights",
                    title=doc.title,
                    topic=topic,
                    source="local",
                    source_id=path.name,
                    tags=tags_for(topic, "local"),
                    provenance=ProvenanceFields(
                        model=response.model,
                        model_version=response.model,
                        temperature=0.0,
                        prompt_id=PROMPT_IDS["analysis.local"],
                    ),
                ),
            )

    return LocalIngestResult(
        document_path=document_path,
        insights_path=insights_path,
        kind=doc.kind,
        title=doc.title,
        slug=slug,
    )
