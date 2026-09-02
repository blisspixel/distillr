# pyright: strict
"""Accordion method -- Deep Research dossier + section-by-section Grok writing."""

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.library.paths import (
    ProvenanceFields,
    artifact_exists,
    artifact_path,
    base_frontmatter,
    tags_for,
    write_markdown_artifact,
)
from distill.llm import call as llm_call
from distill.llm.call import LLMCall
from distill.llm.cost_policy import require_route_allowed
from distill.llm.retry import retry_with_backoff
from distill.llm.router import RouterConfig
from distill.llm.run_context import phase_scope
from distill.pipeline.citation_refs import (
    unresolved_numbered_citation_reason as _unresolved_numbered_citation_reason,
)
from distill.pipeline.costs import BudgetExceededError, CostTracker, TokenUsage
from distill.pipeline.report._interactions import (
    await_interaction,
    file_search_grounding_reason,
    interaction_text,
    preflight_metered_interaction,
    require_cost_tracker,
    submit_metered_interaction,
)
from distill.pipeline.report.accordion_qa import (
    extract_section_feedback as _extract_section_feedback,
)
from distill.pipeline.report.accordion_qa import (
    normalize_qa_title as _normalize_qa_title,
)
from distill.pipeline.report.accordion_qa import (
    parse_qa_failures as _parse_qa_failures,
)
from distill.pipeline.report.assembly import assemble_report as _render_assembled_report
from distill.pipeline.report.assembly import audit_assembled_report
from distill.pipeline.report.deep_research import _get_report_path
from distill.pipeline.report.file_search import create_research_store, delete_store
from distill.pipeline.report.materials import (
    channels_for_scope as _channels_for_scope,
)
from distill.pipeline.report.materials import (
    gather_tagged_materials as _gather_tagged_materials,
)
from distill.pipeline.summary import BatchProgress
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.report import (
    REPORT_SECTIONS,
    ReportSection,
    WrittenSection,
    dossier_prompt,
    fix_prompt,
    get_active_sections,
    qa_prompt,
    section_prompt,
)
from distill.prompts.report_sections import DEFAULT_SECTION_PROFILE

logger = logging.getLogger(__name__)


def __getattr__(name: str) -> object:
    """Lazily expose ``genai`` so importing this module stays cheap.

    The google-genai SDK costs roughly a second of import time, so it is
    imported only when a report actually runs. Tests that patch
    ``distill.pipeline.report.accordion.genai.Client`` keep working: this
    hook resolves ``genai`` to the real module on first attribute access.
    """
    if name == "genai":
        from google import genai

        return genai
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "report_router_config",
    "run_accordion_research",
    "run_sequential_report",
]

# Gemini Deep Research (the April-2026 successor to deep-research-pro-preview-12-2025).
# Standard variant, not the pricier deep-research-max-preview-04-2026.
DEEP_RESEARCH_MODEL = "deep-research-preview-04-2026"


@dataclass(frozen=True)
class SectionWriteResult:
    """Outcome of one section call before orchestration policy is applied."""

    section: WrittenSection | None
    error: str = ""
    refusal: str = ""


def report_router_config(config: DistillConfig) -> RouterConfig:
    """Build one report router so preflight and model calls use the same keys."""

    return RouterConfig(
        xai_api_key=config.xai_api_key.get_secret_value(),
        gemini_api_key=config.gemini_api_key.get_secret_value(),
        anthropic_api_key=config.anthropic_api_key.get_secret_value(),
        openai_api_key=config.openai_api_key.get_secret_value(),
        openrouter_api_key=config.openrouter_api_key.get_secret_value(),
        openrouter_zdr=config.distill_openrouter_zdr,
        cost_mode=config.distill_cost_mode,
        fast_model=config.xai_fast_model,
        premium_model=config.xai_premium_model,
        analysis_model=config.xai_analysis_model,
        rerank_model=config.xai_rerank_model,
        synthesis_model=config.xai_synthesis_model,
        site_model=config.xai_site_model,
        accordion_model=config.accordion_section_model,
    )


def run_accordion_research(
    topic: str,
    config: DistillConfig,
    scope: str = "topic",
    channel_name: str | None = None,
    focus: str | None = None,
    test: bool = False,
    dossier_only: bool = False,
    sections: list[str] | None = None,
    tracker: CostTracker | None = None,
    skip_qa: bool = False,
) -> str | None:
    """Run the full accordion pipeline: research -> sections -> assembly -> QA."""
    router_config = report_router_config(config)
    router_config.validate_config("accordion")
    require_route_allowed(
        cost_mode=config.distill_cost_mode,
        provider="gemini",
        workload="report",
    )
    tracker = require_cost_tracker(tracker)
    phase_total = 1 if dossier_only else 3 if skip_qa else 4
    phase_progress = BatchProgress("report", phase_total, tracker)

    # ── Phase 1: Research ──
    console.print("\n[bold cyan]Phase 1: Research (Gemini Deep Research)[/bold cyan]")

    phase_start = phase_progress.start_item()
    console.print(phase_progress.item_line("research", "Gemini Deep Research"))
    with phase_scope("report.research", wait_class="provider"):
        dossier = _run_dossier_phase(topic, config, scope, channel_name, focus, test, tracker)
    if not dossier:
        phase_progress.finish_item(phase_start, success=False)
        console.print(phase_progress.status_line("failed"))
        return None
    phase_progress.finish_item(phase_start, success=True)
    console.print(phase_progress.status_line("done"))

    dossier_words = len(dossier.split())
    console.print(f"[green]Research complete: {dossier_words:,} words of validated facts[/green]")

    # Save research as standalone artifact
    research_path = _get_research_path(topic, config, scope, channel_name)
    research_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown_artifact(
        research_path.parent,
        "research",
        dossier,
        identity=research_path.stem.removesuffix("_Research"),
        frontmatter=base_frontmatter(
            artifact_type="research",
            title=f"Research dossier: {_scope_label(scope, topic, channel_name)}",
            topic=topic if scope != "all" else "",
            source="distill",
            tags=tags_for(topic, "research") if scope != "all" else tags_for("", "research"),
            synthesis_scope="interpretation",
            extra={"legacy_filename": "research.md"},
            provenance=ProvenanceFields(
                model=DEEP_RESEARCH_MODEL,
                model_version=DEEP_RESEARCH_MODEL,
                temperature=0.0,
                prompt_id=PROMPT_IDS["report.dossier"],
            ),
        ),
    )
    console.print(f"[dim]Research saved: {research_path}[/dim]")

    if dossier_only:
        console.print("[cyan]Research-only mode -- skipping section writing[/cyan]")
        return dossier

    return run_sequential_report(
        topic=topic,
        config=config,
        dossier=dossier,
        scope=scope,
        channel_name=channel_name,
        sections=sections,
        tracker=tracker,
        skip_qa=skip_qa,
        phase_progress=phase_progress,
        section_profile=DEFAULT_SECTION_PROFILE,
        research_label="Deep Research dossier",
        method_label="Accordion method | Deep Research dossier plus sequential section writing",
        prompt_family="report.accordion",
        router_config=router_config,
    )


def run_sequential_report(
    *,
    topic: str,
    config: DistillConfig,
    dossier: str,
    scope: str = "topic",
    channel_name: str | None = None,
    sections: list[str] | None = None,
    tracker: CostTracker,
    skip_qa: bool = False,
    phase_progress: BatchProgress | None = None,
    section_profile: str = DEFAULT_SECTION_PROFILE,
    research_label: str = "Deep Research dossier",
    method_label: str = "Accordion method | Deep Research dossier plus sequential section writing",
    prompt_family: str = "report.accordion",
    router_config: RouterConfig | None = None,
    report_title: str = "Strategic Intelligence Report",
    writer_role: str = (
        "a senior pre-sales architect who advises enterprise customers on AI strategy "
        "across Microsoft, Google, AWS, and NVIDIA"
    ),
    show_video_coverage: bool = True,
) -> str | None:
    """Write, review, assemble, audit, and save an ordered report."""

    if not dossier.strip():
        return None
    progress = phase_progress or BatchProgress("report", 2 if skip_qa else 3, tracker)
    router = router_config or report_router_config(config)
    router.validate_config("accordion")

    # Determine active sections based on scope
    _, channel_count = _count_sources(topic, config, scope, channel_name)
    active_sections = get_active_sections(scope, channel_count, profile=section_profile)

    # ── Phase 2: Section Writing ──
    _, section_model = router.resolve("accordion")
    console.print(
        f"\n[bold cyan]Phase 2: Section Writing ({section_model} x {len(active_sections)} sections)[/bold cyan]"
    )

    phase_start = progress.start_item()
    console.print(progress.item_line("sections", "Section writing"))
    with phase_scope("report.sections", wait_class="provider"):
        tagged_materials = _gather_tagged_materials(topic, config, scope, channel_name)

        written_sections = _write_sections(
            topic=topic,
            config=config,
            dossier=dossier,
            scope=scope,
            channel_name=channel_name,
            tagged_materials=tagged_materials,
            filter_sections=sections,
            tracker=tracker,
            active_sections=active_sections,
            research_label=research_label,
            router_config=router,
            report_title=report_title,
            writer_role=writer_role,
        )

    if not written_sections:
        progress.finish_item(phase_start, success=False)
        console.print(progress.status_line("failed"))
        console.print("[red]No sections were written successfully[/red]")
        return None
    progress.finish_item(phase_start, success=True)
    console.print(progress.status_line("done"))

    # ── Phase 3: Assembly ──
    console.print("\n[bold cyan]Phase 3: Assembly[/bold cyan]")

    phase_start = progress.start_item()
    console.print(progress.item_line("assembly", "Report assembly"))
    with phase_scope("report.assembly", wait_class="deterministic_cpu"):
        report = _assemble_report(
            topic=topic,
            config=config,
            scope=scope,
            channel_name=channel_name,
            sections=written_sections,
            method_label=method_label,
            report_title=report_title,
            show_video_coverage=show_video_coverage,
        )
    progress.finish_item(phase_start, success=True)
    console.print(progress.status_line("done"))

    # ── Phase 4: QA ──
    if not skip_qa:
        console.print("\n[bold cyan]Phase 4: QA Review[/bold cyan]")

        phase_start = progress.start_item()
        console.print(progress.item_line("qa", "QA review"))
        with phase_scope("report.qa", wait_class="provider"):
            written_sections, rewrote = _run_qa_phase(
                topic=topic,
                config=config,
                dossier=dossier,
                report=report,
                written_sections=written_sections,
                tracker=tracker,
                active_sections=active_sections,
                research_label=research_label,
                router_config=router,
                report_title=report_title,
                writer_role=writer_role,
            )
        progress.finish_item(phase_start, success=True)
        console.print(progress.status_line("done"))

        # Re-assemble if any sections were rewritten
        if rewrote:
            console.print(
                f"\n[bold cyan]Re-assembling report ({rewrote} section(s) rewritten)[/bold cyan]"
            )
            report = _assemble_report(
                topic=topic,
                config=config,
                scope=scope,
                channel_name=channel_name,
                sections=written_sections,
                method_label=method_label,
                report_title=report_title,
                show_video_coverage=show_video_coverage,
            )

    audit_assembled_report(report, written_sections)

    # Save
    output_path = _get_report_path(topic, config, scope, channel_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _, section_model = router.resolve("accordion")
    write_markdown_artifact(
        output_path.parent,
        "report",
        report,
        identity=output_path.stem.removesuffix("_Report"),
        frontmatter=base_frontmatter(
            artifact_type="report",
            title=f"Report: {_scope_label(scope, topic, channel_name)}",
            topic=topic if scope != "all" else "",
            source="distill",
            tags=tags_for(topic, "report") if scope != "all" else tags_for("", "report"),
            synthesis_scope="interpretation",
            extra={
                "legacy_filename": "report.md",
                "report_profile": section_profile,
                "research_source": research_label,
            },
            provenance=ProvenanceFields(
                model=section_model,
                model_version=section_model,
                temperature=0.5,
                prompt_id=PROMPT_IDS[prompt_family],
            ),
        ),
    )

    total_words = len(report.split())
    console.print(
        f"[bold green]Report complete: {total_words:,} words ({len(written_sections)} sections)[/bold green]"
    )
    console.print(f"[dim]Saved: {output_path}[/dim]")

    return report


# ─── Phase 1: Dossier ────────────────────────────────────────────────


def _run_dossier_phase(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
    focus: str | None,
    test: bool,
    tracker: CostTracker | None = None,
) -> str | None:
    """Run Gemini Deep Research with File Search grounding to produce a structured fact dossier."""
    require_route_allowed(
        cost_mode=config.distill_cost_mode,
        provider="gemini",
        workload="report",
    )
    tracker = require_cost_tracker(tracker)
    preflight_metered_interaction(tracker=tracker, model=DEEP_RESEARCH_MODEL)
    from google import genai

    client = genai.Client(api_key=config.gemini_api_key.get_secret_value())

    console.print("[cyan]Preparing research corpus...[/cyan]")
    store_name, file_count = create_research_store(client, topic, config, scope, channel_name)

    if file_count == 0:
        console.print("[red]No content found for research scope[/red]")
        delete_store(client, store_name)
        return None

    prompt = dossier_prompt(topic, corpus="", focus=focus)

    console.print("[cyan]Submitting to Gemini Deep Research...[/cyan]")
    console.print(
        f"[dim]Grounded on {file_count} documents via File Search. This typically takes 5-15 minutes.[/dim]"
    )

    try:
        interaction = submit_metered_interaction(
            lambda: client.interactions.create(
                input=prompt,
                agent=DEEP_RESEARCH_MODEL,
                background=True,
                tools=[
                    {
                        "type": "file_search",
                        "file_search_store_names": [store_name],
                    }
                ],
            ),
            tracker=tracker,
            model=DEEP_RESEARCH_MODEL,
        )

        interaction_id = interaction.id
        console.print(f"[dim]Job ID: {interaction_id}[/dim]")

        completed = await_interaction(client, interaction_id, console, label="Deep Research")
        if completed is None:
            return None

        grounding_refusal = file_search_grounding_reason(completed)
        if grounding_refusal:
            console.print(f"[red]Deep Research refused:[/red] {grounding_refusal}")
            return None
        result_text = interaction_text(completed)
        if not result_text:
            console.print("[red]Research completed but no output received[/red]")
            return None

        return result_text

    except BudgetExceededError:
        raise
    except Exception as e:
        console.print(f"[red]Deep Research error: {e}[/red]")
        return None

    finally:
        delete_store(client, store_name)


# ─── Phase 2: Section Writing ────────────────────────────────────────


def _write_sections(
    topic: str,
    config: DistillConfig,
    dossier: str,
    scope: str,
    channel_name: str | None,
    tagged_materials: dict[str, str],
    filter_sections: list[str] | None = None,
    tracker: CostTracker | None = None,
    active_sections: list[ReportSection] | None = None,
    research_label: str = "Deep Research dossier",
    router_config: RouterConfig | None = None,
    report_title: str = "Strategic Intelligence Report",
    writer_role: str = (
        "a senior pre-sales architect who advises enterprise customers on AI strategy "
        "across Microsoft, Google, AWS, and NVIDIA"
    ),
) -> list[WrittenSection]:
    """Write each report section sequentially with context continuity."""
    rc = router_config or report_router_config(config)
    written: list[WrittenSection] = []
    section_list = REPORT_SECTIONS if active_sections is None else active_sections
    total = len(section_list)
    selected_sections = [
        (i, section_def)
        for i, section_def in enumerate(section_list)
        if not filter_sections or section_def["id"] in filter_sections
    ]
    progress = BatchProgress("section", len(selected_sections), tracker)
    consecutive_failures = 0

    for progress_index, (i, section_def) in enumerate(selected_sections):
        section_id = section_def["id"]
        section_title = section_def["title"]

        item_start = progress.start_item()
        console.print(progress.item_line("write", section_title))

        result = write_one_section(
            topic=topic,
            config=config,
            dossier=dossier,
            section_def=section_def,
            previous_sections=written,
            section_index=i,
            total_sections=total,
            tagged_material=tagged_materials.get(section_id),
            tracker=tracker,
            router_config=rc,
            research_label=research_label,
            report_title=report_title,
            writer_role=writer_role,
        )
        if result.section is None:
            if result.error:
                console.print(f"  [red]Failed after retries: {result.error}[/red]")
            message = (
                f"  [red]Refused {section_title}: {result.refusal}[/red]"
                if result.refusal
                else f"  [red]Failed to write {section_title}[/red]"
            )
            console.print(message)
            progress.finish_item(item_start, success=False)
            console.print(progress.status_line("failed"))
            consecutive_failures += 1
            if consecutive_failures >= 3:
                console.print("[red]3 consecutive failures -- stopping section writing[/red]")
                break
            continue

        consecutive_failures = 0
        written.append(result.section)
        console.print(f"  [green]{result.section['word_count']:,} words[/green]")
        progress.finish_item(item_start, success=True)
        console.print(progress.status_line("done"))

        if progress_index < len(selected_sections) - 1:
            time.sleep(3)

    return written


def write_one_section(
    *,
    topic: str,
    config: DistillConfig,
    dossier: str,
    section_def: ReportSection,
    previous_sections: list[WrittenSection],
    section_index: int,
    total_sections: int,
    tagged_material: str | None,
    tracker: CostTracker | None,
    router_config: RouterConfig,
    research_label: str = "Deep Research dossier",
    report_title: str = "Strategic Intelligence Report",
    writer_role: str = (
        "a senior pre-sales architect who advises enterprise customers on AI strategy "
        "across Microsoft, Google, AWS, and NVIDIA"
    ),
) -> SectionWriteResult:
    """Write one section with retries, receipts, and citation refusal."""

    section_title = section_def["title"]
    prompt = section_prompt(
        section=section_def,
        topic=topic,
        research_dossier=dossier,
        previous_sections=previous_sections,
        section_index=section_index,
        total_sections=total_sections,
        tagged_material=tagged_material,
        research_label=research_label,
        report_title=report_title,
        writer_role=writer_role,
    )
    voice = section_def.get("voice", "analytical")
    temperature = 0.3 if voice == "reference" else 0.5 if voice == "analytical" else 0.6
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    _, model_name = router_config.resolve("accordion")
    start_time = time.monotonic()
    attempt_count = 1

    def make_call() -> str:
        response = llm_call(
            router_config,
            workload_tag="accordion",
            prompt=prompt,
            max_tokens=16384,
            temperature=temperature,
            call_type=f"section:{section_title[:30]}",
            usage_tracker=tracker,
        )
        if tracker:
            tracker.record(
                TokenUsage.from_response(response, call_type=f"section:{section_title[:30]}")
            )
        return response.text

    def on_retry(attempt: int, delay: float, error: Exception) -> None:
        nonlocal attempt_count
        attempt_count = attempt + 2
        failed_call = LLMCall(
            model=model_name,
            prompt_hash=prompt_hash,
            prompt_text=prompt[:4096] if len(prompt) <= 4096 else "",
            temperature=temperature,
            max_tokens=16384,
            latency_ms=int((time.monotonic() - start_time) * 1000),
            error_message=str(error),
            attempt=attempt + 1,
        )
        logger.warning(
            "LLM call failed for section %r (attempt %d), retrying in %.1fs: %s",
            section_title,
            attempt + 1,
            delay,
            error,
            extra={"llm_call": failed_call.to_dict()},
        )

    try:
        content = retry_with_backoff(
            make_call,
            max_retries=3,
            base_delay=2.0,
            jitter_fraction=0.5,
            is_permanent=lambda exc: isinstance(exc, BudgetExceededError),
            on_retry=on_retry,
        )
    except BudgetExceededError:
        raise
    except Exception as exc:
        final_call = LLMCall(
            model=model_name,
            prompt_hash=prompt_hash,
            prompt_text=prompt[:4096] if len(prompt) <= 4096 else "",
            temperature=temperature,
            max_tokens=16384,
            latency_ms=int((time.monotonic() - start_time) * 1000),
            error_message=str(exc),
            attempt=attempt_count,
        )
        logger.error(
            "LLM call exhausted retries for section %r: %s",
            section_title,
            exc,
            extra={"llm_call": final_call.to_dict()},
        )
        return SectionWriteResult(section=None, error=str(exc))

    if attempt_count > 1:
        success_call = LLMCall(
            model=model_name,
            prompt_hash=prompt_hash,
            prompt_text=prompt[:4096] if len(prompt) <= 4096 else "",
            temperature=temperature,
            max_tokens=16384,
            response_text=content[:2048] if content else "",
            latency_ms=int((time.monotonic() - start_time) * 1000),
            attempt=attempt_count,
        )
        logger.info(
            "LLM call succeeded for section %r after %d attempts",
            section_title,
            attempt_count,
            extra={"llm_call": success_call.to_dict()},
        )

    refusal = _unresolved_numbered_citation_reason(content)
    if not content or refusal:
        return SectionWriteResult(section=None, refusal=refusal or "")
    cleaned = _clean_section_output(content)
    return SectionWriteResult(
        section={
            "id": section_def["id"],
            "title": section_title,
            "content": cleaned,
            "word_count": len(cleaned.split()),
        }
    )


# ─── Phase 3: Assembly ───────────────────────────────────────────────


# ─── Phase 4: QA ────────────────────────────────────────────────────


def _run_qa_phase(
    topic: str,
    config: DistillConfig,
    dossier: str,
    report: str,
    written_sections: list[WrittenSection],
    tracker: CostTracker | None = None,
    active_sections: list[ReportSection] | None = None,
    research_label: str = "Deep Research dossier",
    router_config: RouterConfig | None = None,
    report_title: str = "Strategic Intelligence Report",
    writer_role: str = "a senior pre-sales architect",
) -> tuple[list[WrittenSection], int]:
    """Run QA review and fix failed sections. Returns (sections, rewrite_count)."""
    rc = router_config or report_router_config(config)
    qa_result = review_assembled_report(
        topic=topic,
        dossier=dossier,
        report=report,
        tracker=tracker,
        router_config=rc,
        research_label=research_label,
        report_title=report_title,
    )

    if not qa_result:
        console.print("  [yellow]QA review failed -- skipping[/yellow]")
        return written_sections, 0

    failed_sections = _parse_qa_failures(qa_result)

    pass_count = len(written_sections) - len(failed_sections)
    console.print(f"  [green]{pass_count} PASS[/green]  [red]{len(failed_sections)} FAIL[/red]")

    if not failed_sections:
        console.print("  [green]All sections passed QA[/green]")
        return written_sections, 0

    for title in failed_sections:
        console.print(f"  [red]FAIL: {title}[/red]")

    qa_by_section = _extract_section_feedback(qa_result)

    # Match on normalized titles so cosmetic drift in the QA output (list
    # numbering, '&' vs 'and', case, trailing verdict) does not cause a failed
    # section to be silently skipped instead of rewritten.
    failed_norm = {_normalize_qa_title(t) for t in failed_sections}
    feedback_norm = {_normalize_qa_title(k): v for k, v in qa_by_section.items()}

    rewrite_targets = _qa_rewrite_targets(written_sections, active_sections, failed_norm)

    rewrote = 0
    progress = BatchProgress("qa-fix", len(rewrite_targets), tracker)
    for i, section, section_def in rewrite_targets:
        title = section["title"]
        feedback = feedback_norm.get(
            _normalize_qa_title(title),
            "Section failed QA review. Improve specificity, add confidence labels, and ground all claims in the research.",
        )

        item_start = progress.start_item()
        console.print(progress.item_line("rewrite", title))

        rewrite = rewrite_one_section(
            topic=topic,
            dossier=dossier,
            report=report,
            section=section,
            section_def=section_def,
            feedback=feedback,
            tracker=tracker,
            router_config=rc,
            report_title=report_title,
            writer_role=writer_role,
        )

        if rewrite:
            refusal = _unresolved_numbered_citation_reason(rewrite)
            if refusal:
                console.print(f"  [yellow]Rewrite refused for {title}: {refusal}[/yellow]")
                progress.finish_item(item_start, success=False)
                console.print(progress.status_line("failed"))
                continue

            rewrite = _clean_section_output(rewrite)
            new_words = len(rewrite.split())
            old_words = section["word_count"]
            written_sections[i] = {
                **section,
                "content": rewrite,
                "word_count": new_words,
            }
            console.print(f"  [green]Rewritten: {old_words} -> {new_words} words[/green]")
            rewrote += 1
            progress.finish_item(item_start, success=True)
            console.print(progress.status_line("done"))
        else:
            console.print(f"  [yellow]Rewrite failed for {title} -- keeping original[/yellow]")
            progress.finish_item(item_start, success=False)
            console.print(progress.status_line("failed"))

    return written_sections, rewrote


def review_assembled_report(
    *,
    topic: str,
    dossier: str,
    report: str,
    tracker: CostTracker | None,
    router_config: RouterConfig,
    research_label: str,
    report_title: str = "Strategic Intelligence Report",
) -> str:
    """Review the complete report once so cross-section issues stay visible."""

    try:
        response = llm_call(
            router_config,
            workload_tag="accordion",
            prompt=qa_prompt(
                topic,
                dossier,
                report,
                research_label=research_label,
                report_title=report_title,
            ),
            max_tokens=16384,
            retries=1,
            call_type="qa_review",
            usage_tracker=tracker,
        )
        if tracker:
            tracker.record(TokenUsage.from_response(response, call_type="qa_review"))
        return response.text
    except BudgetExceededError:
        raise
    except Exception:
        return ""


def _qa_rewrite_targets(
    written_sections: list[WrittenSection],
    active_sections: list[ReportSection] | None,
    failed_normalized_titles: set[str],
) -> list[tuple[int, WrittenSection, ReportSection]]:
    section_lookup = {section["id"]: section for section in (active_sections or REPORT_SECTIONS)}
    for section in get_active_sections():
        section_lookup[section["id"]] = section
    targets: list[tuple[int, WrittenSection, ReportSection]] = []
    for index, written in enumerate(written_sections):
        if _normalize_qa_title(written["title"]) not in failed_normalized_titles:
            continue
        definition = section_lookup.get(written.get("id", ""))
        if definition:
            targets.append((index, written, definition))
    return targets


def rewrite_one_section(
    *,
    topic: str,
    dossier: str,
    report: str,
    section: WrittenSection,
    section_def: ReportSection,
    feedback: str,
    tracker: CostTracker | None,
    router_config: RouterConfig,
    report_title: str = "Strategic Intelligence Report",
    writer_role: str = "a senior pre-sales architect",
) -> str:
    """Rewrite one QA failure with the full document as ordered context."""

    title = section["title"]
    try:
        response = llm_call(
            router_config,
            workload_tag="accordion",
            prompt=fix_prompt(
                section=section_def,
                topic=topic,
                research=dossier,
                qa_feedback=feedback,
                original_content=section["content"],
                report_context=report,
                report_title=report_title,
                writer_role=writer_role,
            ),
            max_tokens=16384,
            call_type=f"fix:{title[:25]}",
            usage_tracker=tracker,
        )
        if tracker:
            tracker.record(TokenUsage.from_response(response, call_type=f"fix:{title[:25]}"))
        return response.text
    except BudgetExceededError:
        raise
    except Exception:
        return ""


def _assemble_report(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
    sections: list[WrittenSection],
    method_label: str = "Accordion method | Deep Research dossier plus section-by-section Grok writing",
    report_title: str = "Strategic Intelligence Report",
    show_video_coverage: bool = True,
) -> str:
    """Assemble written sections into the final report."""
    video_count, channel_count = _count_sources(topic, config, scope, channel_name)
    return _render_assembled_report(
        topic=topic,
        scope_label=_scope_label(scope, topic, channel_name),
        sections=sections,
        video_count=video_count,
        channel_count=channel_count,
        method_label=method_label,
        report_title=report_title,
        show_video_coverage=show_video_coverage,
    )


# ─── Helpers ─────────────────────────────────────────────────────────


def _clean_section_output(content: str) -> str:
    """Strip trailing word counts and meta-commentary from LLM output."""
    # Only strip a self-annotation the model appends at the very end. The
    # earlier unanchored variants also deleted legitimate inline parentheticals
    # like "short (200 words) and dense" from report prose, so they are gone,
    # an end-anchored strip is enough for the model's trailing count.
    content = re.sub(r"\n*\(Word count:?\s*[\d,]+\)\s*$", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\n*\([\d,]+\s*words?\)\s*$", "", content, flags=re.IGNORECASE)
    return content.strip()


def _get_research_path(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> Path:
    """Path for the Phase 1 research notes."""
    if scope == "channel" and channel_name:
        return artifact_path(
            config.channel_dir(topic, channel_name),
            "research",
            identity=f"{topic}_{channel_name}",
        )
    elif scope == "topic":
        return artifact_path(config.topic_dir(topic), "research", identity=topic)
    else:
        return artifact_path(config.library_dir, "research", identity="library")


def _scope_label(scope: str, topic: str, channel_name: str | None) -> str:
    if scope == "channel" and channel_name:
        return f"Channel: {channel_name} ({topic})"
    elif scope == "topic":
        return f"Topic: {topic}"
    else:
        return "Full Library"


def _count_sources(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> tuple[int, int]:
    """Count videos and channels in scope."""
    channels = _channels_for_scope(topic, config, scope, channel_name)

    video_count = 0
    for t, ch in channels:
        vdir = config.videos_dir(t, ch)
        if vdir.exists():
            video_count += sum(
                1 for d in vdir.iterdir() if d.is_dir() and artifact_exists(d, "insights")
            )

    return video_count, len(channels)
