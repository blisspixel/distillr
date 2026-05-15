"""Accordion method -- Deep Research dossier + section-by-section Grok writing."""

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from google import genai
from rich.console import Console

from distill.config import DistillConfig
from distill.library.paths import (
    ProvenanceFields,
    artifact_exists,
    artifact_path,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.library.wikilinks import emit_wiki_link
from distill.llm import call as llm_call
from distill.llm.call import LLMCall
from distill.llm.retry import retry_with_backoff
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.pipeline.report.deep_research import _get_report_path
from distill.pipeline.report.file_search import create_research_store, delete_store
from distill.prompts.report import (
    REPORT_SECTIONS,
    dossier_prompt,
    fix_prompt,
    get_active_sections,
    qa_prompt,
    section_prompt,
)

logger = logging.getLogger(__name__)

__all__ = [
    "run_accordion_research",
]

console = Console()

DEEP_RESEARCH_MODEL = "deep-research-pro-preview-12-2025"
MAX_CORPUS_CHARS = 350_000


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

    # ── Phase 1: Research ──
    console.print("\n[bold cyan]Phase 1: Research (Gemini Deep Research)[/bold cyan]")

    dossier = _run_dossier_phase(topic, config, scope, channel_name, focus, test, tracker)
    if not dossier:
        return None

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
            confidence="interpretation",
            extra={"legacy_filename": "research.md"},
            provenance=ProvenanceFields(
                model=DEEP_RESEARCH_MODEL,
                model_version=DEEP_RESEARCH_MODEL,
                temperature=0.0,
                prompt_id="report.dossier.v1",
            ),
        ),
    )
    console.print(f"[dim]Research saved: {research_path}[/dim]")

    if dossier_only:
        console.print("[cyan]Research-only mode -- skipping section writing[/cyan]")
        return dossier

    # Determine active sections based on scope
    _, channel_count = _count_sources(topic, config, scope, channel_name)
    active_sections = get_active_sections(scope, channel_count)

    # ── Phase 2: Section Writing ──
    section_model = config.xai_model_for("accordion")
    console.print(
        f"\n[bold cyan]Phase 2: Section Writing ({section_model} x {len(active_sections)} sections)[/bold cyan]"
    )

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
    )

    if not written_sections:
        console.print("[red]No sections were written successfully[/red]")
        return None

    # ── Phase 3: Assembly ──
    console.print("\n[bold cyan]Phase 3: Assembly[/bold cyan]")

    report = _assemble_report(
        topic=topic,
        config=config,
        scope=scope,
        channel_name=channel_name,
        sections=written_sections,
    )

    # ── Phase 4: QA ──
    if not skip_qa:
        console.print("\n[bold cyan]Phase 4: QA Review[/bold cyan]")

        written_sections, rewrote = _run_qa_phase(
            topic=topic,
            config=config,
            dossier=dossier,
            report=report,
            written_sections=written_sections,
            tracker=tracker,
        )

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
            )

    # Save
    output_path = _get_report_path(topic, config, scope, channel_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    section_model = config.xai_model_for("accordion")
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
            confidence="interpretation",
            extra={"legacy_filename": "report.md"},
            provenance=ProvenanceFields(
                model=section_model,
                model_version=section_model,
                temperature=0.5,
                prompt_id="report.accordion.v1",
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
        interaction = client.interactions.create(
            input=prompt,
            agent=DEEP_RESEARCH_MODEL,
            background=True,
            tools=[
                {
                    "type": "file_search",
                    "file_search_store_names": [store_name],
                }
            ],
        )

        interaction_id = interaction.id
        if tracker:
            tracker.record_gemini_query()
        console.print(f"[dim]Job ID: {interaction_id}[/dim]")

        poll_count = 0
        while True:
            interaction = client.interactions.get(interaction_id)
            status = interaction.status
            poll_count += 1

            if status == "completed":
                console.print(f"[green]Deep Research complete ({poll_count * 15}s)[/green]")
                break
            if status == "failed":
                error = getattr(interaction, "error", "Unknown error")
                console.print(f"[red]Research failed: {error}[/red]")
                delete_store(client, store_name)
                return None
            else:
                if poll_count % 4 == 0:
                    console.print(
                        f"  [dim]Still researching... ({poll_count * 15}s, status: {status})[/dim]"
                    )

            time.sleep(15)

        result_text = ""
        if interaction.outputs:
            result_text = interaction.outputs[-1].text

        if not result_text:
            console.print("[red]Research completed but no output received[/red]")
            delete_store(client, store_name)
            return None

        return result_text

    except Exception as e:
        console.print(f"[red]Deep Research error: {e}[/red]")
        return None

    finally:
        delete_store(client, store_name)


# ─── Phase 2: Section Writing ────────────────────────────────────────


def _write_sections(  # noqa: C901 — retry integration adds necessary branching
    topic: str,
    config: DistillConfig,
    dossier: str,
    scope: str,
    channel_name: str | None,
    tagged_materials: dict[str, str],
    filter_sections: list[str] | None = None,
    tracker: CostTracker | None = None,
    active_sections: list[dict] | None = None,
) -> list[dict]:
    """Write each report section sequentially with context continuity."""
    rc = RouterConfig()
    written = []
    section_list = active_sections or REPORT_SECTIONS
    total = len(section_list)
    consecutive_failures = 0

    for i, section_def in enumerate(section_list):
        if filter_sections and section_def["id"] not in filter_sections:
            continue

        section_id = section_def["id"]
        section_title = section_def["title"]

        console.print(f"\n  [{i + 1}/{total}] [bold]{section_title}[/bold]")

        tagged = tagged_materials.get(section_id)

        prompt = section_prompt(
            section=section_def,
            topic=topic,
            research_dossier=dossier,
            previous_sections=written,
            section_index=i,
            total_sections=total,
            tagged_material=tagged,
        )

        voice = section_def.get("voice", "analytical")
        temp = 0.3 if voice == "reference" else 0.5 if voice == "analytical" else 0.6

        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        model_name = config.xai_model_for("accordion")
        content = ""

        def _make_llm_call(
            _prompt: str = prompt,
            _temp: float = temp,
            _section_title: str = section_title,
        ) -> str:
            """Execute the LLM call for this section."""
            response = llm_call(
                rc,
                workload_tag="accordion",
                prompt=_prompt,
                max_tokens=16384,
                temperature=_temp,
                call_type=f"section:{_section_title[:30]}",
            )
            if tracker:
                tracker.record(
                    TokenUsage(
                        prompt_tokens=response.input_tokens,
                        completion_tokens=response.output_tokens,
                        model=response.model,
                        call_type=f"section:{_section_title[:30]}",
                    )
                )
            return response.text

        start_time = time.monotonic()
        attempt_count = 1
        last_error: Exception | None = None

        def _on_retry(
            attempt: int,
            delay: float,
            error: Exception,
            _model_name: str = model_name,
            _prompt_hash: str = prompt_hash,
            _prompt: str = prompt,
            _temp: float = temp,
            _start_time: float = start_time,
            _section_title: str = section_title,
        ) -> None:
            nonlocal attempt_count, last_error
            attempt_count = attempt + 2  # attempt is 0-based, next call is attempt+2
            last_error = error
            # Log LLMCall for the failed attempt
            failed_call = LLMCall(
                model=_model_name,
                prompt_hash=_prompt_hash,
                prompt_text=_prompt[:4096] if len(_prompt) <= 4096 else "",
                temperature=_temp,
                max_tokens=16384,
                latency_ms=int((time.monotonic() - _start_time) * 1000),
                error_message=str(error),
                attempt=attempt + 1,
            )
            logger.warning(
                "LLM call failed for section %r (attempt %d), retrying in %.1fs: %s",
                _section_title,
                attempt + 1,
                delay,
                error,
                extra={"llm_call": failed_call.to_dict()},
            )

        try:
            content = retry_with_backoff(
                _make_llm_call,
                max_retries=3,
                base_delay=2.0,
                jitter_fraction=0.5,
                on_retry=_on_retry,
            )
            latency_ms = int((time.monotonic() - start_time) * 1000)

            # Log successful LLMCall (with attempt number for retry-success visibility)
            if attempt_count > 1:
                success_call = LLMCall(
                    model=model_name,
                    prompt_hash=prompt_hash,
                    prompt_text=prompt[:4096] if len(prompt) <= 4096 else "",
                    temperature=temp,
                    max_tokens=16384,
                    response_text=content[:2048] if content else "",
                    latency_ms=latency_ms,
                    attempt=attempt_count,
                )
                logger.info(
                    "LLM call succeeded for section %r after %d attempts",
                    section_title,
                    attempt_count,
                    extra={"llm_call": success_call.to_dict()},
                )
        except Exception as e:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            # Log final failure LLMCall
            final_call = LLMCall(
                model=model_name,
                prompt_hash=prompt_hash,
                prompt_text=prompt[:4096] if len(prompt) <= 4096 else "",
                temperature=temp,
                max_tokens=16384,
                latency_ms=latency_ms,
                error_message=str(e),
                attempt=attempt_count,
            )
            logger.error(
                "LLM call exhausted retries for section %r: %s",
                section_title,
                e,
                extra={"llm_call": final_call.to_dict()},
            )
            console.print(f"  [red]Failed after retries: {e}[/red]")
            content = ""

        if not content:
            console.print(f"  [red]Failed to write {section_title}[/red]")
            consecutive_failures += 1
            if consecutive_failures >= 3:
                console.print("[red]3 consecutive failures -- stopping section writing[/red]")
                break
            continue

        consecutive_failures = 0
        content = _clean_section_output(content)
        word_count = len(content.split())
        written.append(
            {
                "id": section_id,
                "title": section_title,
                "content": content,
                "word_count": word_count,
            }
        )
        console.print(f"  [green]{word_count:,} words[/green]")

        if i < total - 1:
            time.sleep(3)

    return written


# ─── Phase 3: Assembly ───────────────────────────────────────────────


# ─── Phase 4: QA ────────────────────────────────────────────────────


def _run_qa_phase(  # noqa: C901 — legacy, will refactor
    topic: str,
    config: DistillConfig,
    dossier: str,
    report: str,
    written_sections: list[dict],
    tracker: CostTracker | None = None,
) -> tuple[list[dict], int]:
    """Run QA review and fix failed sections. Returns (sections, rewrite_count)."""
    rc = RouterConfig()

    prompt = qa_prompt(topic, dossier, report)
    try:
        qa_response = llm_call(
            rc,
            workload_tag="accordion",
            prompt=prompt,
            max_tokens=16384,
            retries=1,
            call_type="qa_review",
        )
        qa_result = qa_response.text
        if tracker:
            tracker.record(
                TokenUsage(
                    prompt_tokens=qa_response.input_tokens,
                    completion_tokens=qa_response.output_tokens,
                    model=qa_response.model,
                    call_type="qa_review",
                )
            )
    except Exception:
        qa_result = ""

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

    rewrote = 0
    section_lookup = {s["id"]: s for s in REPORT_SECTIONS}
    for s in get_active_sections():
        section_lookup[s["id"]] = s

    for i, section in enumerate(written_sections):
        title = section["title"]
        if title not in failed_sections:
            continue

        section_def = section_lookup.get(section["id"])
        if not section_def:
            continue

        feedback = qa_by_section.get(
            title,
            "Section failed QA review. Improve specificity, add confidence labels, and ground all claims in the research.",
        )

        console.print(f"\n  Rewriting: [bold]{title}[/bold]")

        try:
            fix_response = llm_call(
                rc,
                workload_tag="accordion",
                prompt=fix_prompt(
                    section=section_def,
                    topic=topic,
                    research=dossier,
                    qa_feedback=feedback,
                    original_content=section["content"],
                ),
                max_tokens=16384,
                call_type=f"fix:{title[:25]}",
            )
            rewrite = fix_response.text
            if tracker:
                tracker.record(
                    TokenUsage(
                        prompt_tokens=fix_response.input_tokens,
                        completion_tokens=fix_response.output_tokens,
                        model=fix_response.model,
                        call_type=f"fix:{title[:25]}",
                    )
                )
        except Exception:
            rewrite = ""

        if rewrite:
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
        else:
            console.print(f"  [yellow]Rewrite failed for {title} -- keeping original[/yellow]")

    return written_sections, rewrote


def _parse_qa_failures(qa_result: str) -> list[str]:
    """Extract section titles that scored FAIL from QA output."""
    failed = []
    lines = qa_result.split("\n")
    current_section = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### ") and stripped != "### OVERALL":
            current_section = stripped[4:].strip()
        elif "**Score**" in stripped and "FAIL" in stripped.upper() and current_section:
            failed.append(current_section)
            current_section = None

    return failed


def _extract_section_feedback(qa_result: str) -> dict[str, str]:
    """Extract per-section feedback text from QA output."""
    feedback = {}
    lines = qa_result.split("\n")
    current_section = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            if current_section and current_lines:
                feedback[current_section] = "\n".join(current_lines)
            current_section = stripped[4:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section and current_lines:
        feedback[current_section] = "\n".join(current_lines)

    return feedback


def _assemble_report(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
    sections: list[dict],
) -> str:
    """Assemble written sections into the final report."""
    now = datetime.now().strftime("%B %d, %Y")
    scope_label = _scope_label(scope, topic, channel_name)

    video_count, channel_count = _count_sources(topic, config, scope, channel_name)

    lines = [
        f"# Strategic Intelligence Report: {topic.upper()}",
        "",
        f"*{scope_label} | {now}*",
        f"*{channel_count} channel(s), {video_count} videos analyzed*",
        "*Accordion method | Deep Research dossier plus section-by-section Grok writing*",
        "",
        "---",
        "",
    ]

    lines.append("## Table of Contents")
    lines.append("")
    for i, section in enumerate(sections, 1):
        lines.append(f"{i}. **{section['title']}** ({section['word_count']:,} words)")
    lines.append("")
    lines.append("---")
    lines.append("")

    for section in sections:
        lines.append(f"## {section['title']}")
        lines.append("")
        lines.append(section["content"])
        lines.append("")
        lines.append("---")
        lines.append("")

    total_words = sum(section.get("word_count", 0) for section in sections)
    lines.append(
        f"*Generated by Distill | Accordion method | {len(sections)} sections | {total_words:,} words*"
    )

    return "\n".join(lines)


# ─── Tagged Material Gathering ───────────────────────────────────────


def _gather_tagged_materials(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> dict[str, str]:
    """Gather section-specific source material from the corpus."""
    tagged = {}

    syntheses = _load_syntheses(topic, config, scope, channel_name)
    if syntheses:
        tagged["creator_consensus"] = syntheses

    vendor_insights = _load_tagged_insights(
        topic,
        config,
        scope,
        channel_name,
        keywords=["Microsoft", "Azure", "Google", "AWS", "NVIDIA", "OpenAI", "Anthropic"],
        max_chars=30000,
    )
    if vendor_insights:
        tagged["vendor_battleground"] = vendor_insights

    enterprise_insights = _load_tagged_insights(
        topic,
        config,
        scope,
        channel_name,
        keywords=["enterprise", "customer", "production", "deploy", "ROI", "TCO", "pricing"],
        max_chars=20000,
    )
    if enterprise_insights:
        tagged["enterprise_reality"] = enterprise_insights

    return tagged


def _load_syntheses(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> str:
    """Load channel and topic syntheses as supplementary material."""
    parts = []

    if scope == "channel" and channel_name:
        channels = [(topic, channel_name)]
    elif scope == "topic":
        ch_dir = config.topic_dir(topic) / "channels"
        channels = (
            [(topic, d.name) for d in sorted(ch_dir.iterdir()) if d.is_dir()]
            if ch_dir.exists()
            else []
        )
    else:
        channels = []
        topics_root = config.topics_dir()
        if topics_root.exists():
            for t_dir in sorted(topics_root.iterdir()):
                if not t_dir.is_dir():
                    continue
                ch_dir = t_dir / "channels"
                if ch_dir.exists():
                    channels.extend(
                        (t_dir.name, d.name) for d in sorted(ch_dir.iterdir()) if d.is_dir()
                    )

    for t, ch in channels:
        synth_file = find_artifact(
            config.channel_dir(t, ch),
            "synthesis",
            identity=f"{t}_{ch}",
        )
        if synth_file.exists():
            link = emit_wiki_link(f"Channel synthesis: {ch}", f"{t}_{ch}", "synthesis")
            parts.append(
                f"### {ch} Channel Synthesis\nSource: {link}\n{synth_file.read_text(encoding='utf-8')}"
            )

    topic_synth = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
    if topic_synth.exists():
        link = emit_wiki_link(f"Topic synthesis: {topic}", topic, "topic_synthesis")
        parts.append(
            f"### Topic Synthesis: {topic}\nSource: {link}\n{topic_synth.read_text(encoding='utf-8')}"
        )

    return "\n\n".join(parts) if parts else ""


def _load_tagged_insights(  # noqa: C901 — legacy, will refactor
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
    keywords: list[str],
    max_chars: int = 30000,
) -> str:
    """Load insights that mention specific keywords."""
    if scope == "channel" and channel_name:
        channels = [(topic, channel_name)]
    elif scope == "topic":
        ch_dir = config.topic_dir(topic) / "channels"
        channels = (
            [(topic, d.name) for d in sorted(ch_dir.iterdir()) if d.is_dir()]
            if ch_dir.exists()
            else []
        )
    else:
        channels = []
        topics_root = config.topics_dir()
        if topics_root.exists():
            for t_dir in sorted(topics_root.iterdir()):
                if not t_dir.is_dir():
                    continue
                ch_dir = t_dir / "channels"
                if ch_dir.exists():
                    channels.extend(
                        (t_dir.name, d.name) for d in sorted(ch_dir.iterdir()) if d.is_dir()
                    )

    matching = []
    total_chars = 0
    keywords_lower = [k.lower() for k in keywords]

    for t, ch in channels:
        videos_dir = config.videos_dir(t, ch)
        if not videos_dir.exists():
            continue
        for vid_dir in sorted(videos_dir.iterdir()):
            if not vid_dir.is_dir():
                continue
            insights_file = find_artifact(vid_dir, "insights")
            if not insights_file.exists():
                continue

            content = insights_file.read_text(encoding="utf-8")
            content_lower = content.lower()

            if any(kw in content_lower for kw in keywords_lower):
                meta_file = vid_dir / "metadata.json"
                title = vid_dir.name
                source_id = vid_dir.name
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    title = meta.get("title", vid_dir.name)
                    source_id = meta.get("video_id", vid_dir.name)

                link = emit_wiki_link(title, source_id, "insights")
                entry = f"**{title}** ({ch}) {link}:\n{content}\n"
                if total_chars + len(entry) > max_chars:
                    break
                matching.append(entry)
                total_chars += len(entry)

    return "\n---\n".join(matching) if matching else ""


# ─── Helpers ─────────────────────────────────────────────────────────


def _clean_section_output(content: str) -> str:
    """Strip word counts, numbered citations, and meta-commentary from LLM output."""
    import re

    content = re.sub(r"\n*\(Word count:?\s*[\d,]+\)\s*$", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\n*\([\d,]+\s*words?\)\s*$", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*\(Word count:?\s*[\d,]+\)", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*\([\d,]+\s*words?\)", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*\[cite:\s*[\d,\s]+\]", "", content)
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


def _get_dossier_path(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> Path:
    """Legacy path helper kept for compatibility with older callers and tests."""
    if scope == "channel" and channel_name:
        return config.channel_dir(topic, channel_name) / "dossier.md"
    elif scope == "topic":
        return config.topic_dir(topic) / "dossier.md"
    else:
        return config.library_dir / "dossier.md"


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
    if scope == "channel" and channel_name:
        channels = [(topic, channel_name)]
    elif scope == "topic":
        ch_dir = config.topic_dir(topic) / "channels"
        channels = (
            [(topic, d.name) for d in sorted(ch_dir.iterdir()) if d.is_dir()]
            if ch_dir.exists()
            else []
        )
    else:
        channels = []
        topics_root = config.topics_dir()
        if topics_root.exists():
            for t_dir in sorted(topics_root.iterdir()):
                if not t_dir.is_dir():
                    continue
                ch_dir = t_dir / "channels"
                if ch_dir.exists():
                    channels.extend(
                        (t_dir.name, d.name) for d in sorted(ch_dir.iterdir()) if d.is_dir()
                    )

    video_count = 0
    for t, ch in channels:
        vdir = config.videos_dir(t, ch)
        if vdir.exists():
            video_count += sum(
                1 for d in vdir.iterdir() if d.is_dir() and artifact_exists(d, "insights")
            )

    return video_count, len(channels)
