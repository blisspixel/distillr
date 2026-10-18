# pyright: strict
"""Local-file capture, exact reuse, history, and verified publication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.local import LocalDocument, extract_local_document
from distill.library.insights import insight_content_sha256, insight_has_body
from distill.library.local_receipts import (
    archive_local_artifacts,
    local_artifact_transaction,
    local_verification_scope,
    reusable_local_insight,
)
from distill.library.paths import (
    ProvenanceFields,
    artifact_path,
    base_frontmatter,
    slugify_title,
    tags_for,
    write_text_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.pipeline.verify import resolve_verify_mode, write_verified_synthesis
from distill.pipeline.verify_entailment import (
    HHEMChecker,
    entailment_available,
    resolve_entailment_threshold,
)
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.synthesis import paper_insight_prompt, site_page_insight_prompt

__all__ = ["LocalIngestResult", "ingest_local_file"]


@dataclass(slots=True)
class LocalIngestResult:
    document_path: Path
    insights_path: Path | None
    kind: str
    title: str
    slug: str
    refusal_reason: str = ""
    no_op: bool = False
    verification_scope: str = "off"


def ingest_local_file(
    path: Path,
    *,
    topic: str,
    config: DistillConfig,
    analyze: bool = True,
    tracker: CostTracker | None = None,
    force: bool = False,
) -> LocalIngestResult:
    doc = extract_local_document(path)
    slug = slugify_title(doc.title, source_id=path.name)
    directory = config.topic_dir(topic) / "local" / slug
    with local_artifact_transaction(directory, config.library_dir):
        return _ingest_document(
            doc, path, directory, slug, topic, config, analyze=analyze, tracker=tracker, force=force
        )


def _ingest_document(
    doc: LocalDocument,
    path: Path,
    directory: Path,
    slug: str,
    topic: str,
    config: DistillConfig,
    *,
    analyze: bool,
    tracker: CostTracker | None,
    force: bool,
) -> LocalIngestResult:
    document_path = artifact_path(directory, "content", identity=slug)
    if not analyze:
        archive_local_artifacts(directory, slug)
        document_path = write_text_artifact(directory, "content", doc.text, identity=slug)
        return LocalIngestResult(document_path, None, doc.kind, doc.title, slug)
    mode = resolve_verify_mode(config.distill_verify)
    rc = RouterConfig()
    provider, model = rc.resolve("site")
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "provider": provider,
                "model": model,
                "prompt": PROMPT_IDS["analysis.local"],
                "kind": doc.kind,
                "verify": mode,
                "prose_available": entailment_available(),
                "prose_model_revision": HHEMChecker.model_revision,
                "prose_threshold": resolve_entailment_threshold(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if not force:
        reused = reusable_local_insight(directory, slug, doc.text, fingerprint, verify_mode=mode)
        if reused is not None:
            console.print(
                f"no-op: unchanged input, route, prompt, and verification settings; {reused.coverage}"
            )
            return LocalIngestResult(
                document_path,
                reused.path,
                doc.kind,
                doc.title,
                slug,
                no_op=True,
                verification_scope=reused.coverage,
            )
    archive_local_artifacts(directory, slug)
    document_path = write_text_artifact(directory, "content", doc.text, identity=slug)
    prompt = (
        paper_insight_prompt(doc.title, path.name, doc.text)
        if doc.kind == "pdf"
        else site_page_insight_prompt(doc.title, str(path), "local", doc.kind, doc.text)
    )
    response = llm_call(
        rc, workload_tag="site", prompt=prompt, call_type="local", usage_tracker=tracker
    )
    if tracker is not None:
        tracker.record(TokenUsage.from_response(response, call_type="local"))
    if not insight_has_body(response.text):
        console.print("Analysis produced no usable insight.")
        return LocalIngestResult(
            document_path,
            None,
            doc.kind,
            doc.title,
            slug,
            refusal_reason="Analysis produced no usable insight",
        )
    messages: list[str] = []

    def notify(message: str) -> None:
        messages.append(message)
        console.print(message, markup=False, soft_wrap=True)

    frontmatter = base_frontmatter(
        artifact_type="insights",
        title=doc.title,
        topic=topic,
        source="local",
        source_id=path.name,
        tags=tags_for(topic, "local"),
        extra={
            "source_receipt": document_path.name,
            "source_receipt_sha256": insight_content_sha256(doc.text),
            "analysis_fingerprint": fingerprint,
            "verification_required": mode != "off",
        },
        provenance=ProvenanceFields(
            model=response.model,
            model_version=response.model,
            temperature=0.0,
            prompt_id=PROMPT_IDS["analysis.local"],
        ),
    )
    output = write_verified_synthesis(
        directory,
        "insights",
        response.text,
        doc.text,
        verify_mode=mode,
        artifact_identity=slug,
        verify_identity=slug,
        source_name=document_path.name,
        notify=notify,
        frontmatter=frontmatter,
    )
    reason = (
        (messages[-1] if messages else "Verification refused publication") if output is None else ""
    )
    scope = local_verification_scope(directory, slug, mode=mode)
    return LocalIngestResult(
        document_path,
        output,
        doc.kind,
        doc.title,
        slug,
        refusal_reason=reason,
        verification_scope=scope,
    )
