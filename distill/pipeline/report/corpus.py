# pyright: strict
"""Corpus-first research material for sequential reports."""

from __future__ import annotations

from distill._console import console
from distill.config import DistillConfig
from distill.llm.cost_policy import (
    LOCAL_PROVIDER_NAMES,
    local_provider_endpoint,
    require_route_allowed,
)
from distill.pipeline.costs import CostTracker
from distill.pipeline.report._interactions import require_cost_tracker
from distill.pipeline.report.accordion import report_router_config
from distill.pipeline.report.file_search import gather_corpus_documents
from distill.pipeline.summary import BatchProgress
from distill.prompts.report_sections import CORPUS_SECTION_PROFILE

__all__ = [
    "MAX_CORPUS_REPORT_CHARS",
    "build_corpus_dossier",
    "gather_corpus_dossier",
    "run_corpus_report",
]

MAX_CORPUS_REPORT_CHARS = 160_000
_TRUNCATION_NOTE = "\n\n[Corpus material omitted at the configured report context boundary.]"


def _document_priority(label: str) -> tuple[int, str]:
    normalized = label.casefold()
    if "corpus-synthesis" in normalized:
        return 0, normalized
    if "topic-synthesis" in normalized or "paper-synthesis" in normalized:
        return 1, normalized
    if "site-synthesis" in normalized or "channel-meta" in normalized:
        return 2, normalized
    return 3, normalized


def build_corpus_dossier(
    topic: str,
    documents: list[tuple[str, str]],
    *,
    focus: str | None = None,
    max_chars: int = MAX_CORPUS_REPORT_CHARS,
) -> str:
    """Build a synthesis-first, bounded evidence dossier from local artifacts."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    header_lines = [
        f"# Corpus evidence dossier: {topic}",
        "",
        "This material comes from Distill corpus artifacts. Treat artifact labels, URLs, and receipt paths as provenance. Support not found is uncertainty, not proof that a claim is false.",
    ]
    if focus:
        header_lines.extend(["", f"Research focus: {focus.strip()}"])
    dossier = "\n".join(header_lines).strip()
    if not documents:
        return ""

    included = 0
    for label, content in sorted(documents, key=lambda item: _document_priority(item[0])):
        normalized_label = label.strip()
        normalized_content = content.strip()
        if not normalized_label or not normalized_content:
            continue
        block = f"\n\n## Corpus artifact: {normalized_label}\n\n{normalized_content}"
        remaining = max_chars - len(dossier)
        if remaining <= len(_TRUNCATION_NOTE):
            break
        if len(block) <= remaining:
            dossier += block
            included += 1
            continue
        if included == 0:
            usable = remaining - len(_TRUNCATION_NOTE)
            dossier += block[:usable].rstrip() + _TRUNCATION_NOTE
            included = 1
        else:
            dossier += _TRUNCATION_NOTE
        break
    return dossier if included else ""


def gather_corpus_dossier(
    topic: str,
    config: DistillConfig,
    scope: str = "topic",
    channel_name: str | None = None,
    focus: str | None = None,
) -> str:
    """Gather local artifacts and compose the report evidence dossier."""

    documents = gather_corpus_documents(topic, config, scope, channel_name)
    return build_corpus_dossier(topic, documents, focus=focus)


def run_corpus_report(
    topic: str,
    config: DistillConfig,
    scope: str = "topic",
    channel_name: str | None = None,
    focus: str | None = None,
    sections: list[str] | None = None,
    tracker: CostTracker | None = None,
    skip_qa: bool = False,
) -> str | None:
    """Write a sequential report directly from the durable local corpus."""

    router = report_router_config(config)
    router.validate_config("accordion")
    provider, model = router.resolve("accordion")
    endpoint = local_provider_endpoint(provider) if provider in LOCAL_PROVIDER_NAMES else None
    require_route_allowed(
        cost_mode=config.distill_cost_mode,
        provider=provider,
        workload="report",
        endpoint=endpoint,
    )
    tracker = require_cost_tracker(tracker)
    console.print("\n[bold cyan]Research material: Distill corpus[/bold cyan]")
    dossier = gather_corpus_dossier(topic, config, scope, channel_name, focus)
    if not dossier:
        console.print("[red]No corpus artifacts found for the report scope[/red]")
        return None
    console.print(f"[green]Corpus material ready: {len(dossier):,} characters for {model}[/green]")

    from distill.pipeline.report.accordion import run_sequential_report

    return run_sequential_report(
        topic=topic,
        config=config,
        dossier=dossier,
        scope=scope,
        channel_name=channel_name,
        sections=sections,
        tracker=tracker,
        skip_qa=skip_qa,
        phase_progress=BatchProgress("report", 2 if skip_qa else 3, tracker),
        section_profile=CORPUS_SECTION_PROFILE,
        research_label="Distill corpus artifacts with receipt paths",
        method_label="Corpus report | Local corpus evidence plus sequential section writing",
        prompt_family="report.corpus",
        router_config=router,
        report_title="Research Report",
        writer_role=(
            "a senior research analyst who traces claims to evidence, separates fact from "
            "inference, and explains uncertainty without imposing a domain-specific agenda"
        ),
        show_video_coverage=False,
    )
