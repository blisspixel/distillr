"""Accordion method -- Deep Research dossier + section-by-section Grok writing."""

import json
import time
from datetime import datetime
from pathlib import Path

from google import genai
from rich.console import Console

from distill.artifacts import (
    artifact_exists,
    artifact_path,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.config import DistillConfig, router_config_from_distill
from distill.costs import CostTracker, TokenUsage
from distill.file_search import create_research_store, delete_store
from distill.llm import call as llm_call
from distill.prompts_accordion import (
    REPORT_SECTIONS,
    dossier_prompt,
    fix_prompt,
    get_active_sections,
    qa_prompt,
    section_prompt,
)
from distill.research import _get_report_path

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
    client = genai.Client(api_key=config.gemini_api_key)

    # Upload corpus to File Search store for semantic retrieval
    console.print("[cyan]Preparing research corpus...[/cyan]")
    store_name, file_count = create_research_store(client, topic, config, scope, channel_name)

    if file_count == 0:
        console.print("[red]No content found for research scope[/red]")
        delete_store(client, store_name)
        return None

    # Build prompt — no corpus inline, Deep Research will search the store
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

        if tracker:
            tracker.record_gemini_query()

        return result_text

    except Exception as e:
        console.print(f"[red]Deep Research error: {e}[/red]")
        return None

    finally:
        # Always clean up the store
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
    active_sections: list[dict] | None = None,
) -> list[dict]:
    """Write each report section sequentially with context continuity."""
    rc = router_config_from_distill(config)
    written = []
    section_list = active_sections or REPORT_SECTIONS
    total = len(section_list)
    consecutive_failures = 0

    for i, section_def in enumerate(section_list):
        # Filter if specific sections requested
        if filter_sections and section_def["id"] not in filter_sections:
            continue

        section_id = section_def["id"]
        section_title = section_def["title"]

        console.print(f"\n  [{i + 1}/{total}] [bold]{section_title}[/bold]")

        # Get tagged material for this section
        tagged = tagged_materials.get(section_id)

        # Build prompt
        prompt = section_prompt(
            section=section_def,
            topic=topic,
            research_dossier=dossier,
            previous_sections=written,
            section_index=i,
            total_sections=total,
            tagged_material=tagged,
        )

        # Lower temperature for reference/analytical sections, slightly higher for actionable
        voice = section_def.get("voice", "analytical")
        temp = 0.3 if voice == "reference" else 0.5 if voice == "analytical" else 0.6

        # Call via router
        try:
            response = llm_call(
                rc,
                workload_tag="accordion",
                prompt=prompt,
                max_tokens=16384,
                temperature=temp,
                call_type=f"section:{section_title[:30]}",
            )
            content = response.text
            if tracker:
                tracker.record(
                    TokenUsage(
                        prompt_tokens=response.input_tokens,
                        completion_tokens=response.output_tokens,
                        model=response.model,
                        call_type=f"section:{section_title[:30]}",
                    )
                )
        except Exception as e:
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

        # Brief delay between sections to be kind to the API
        if i < total - 1:
            time.sleep(3)

    return written


# ─── Phase 3: Assembly ───────────────────────────────────────────────


# (assembly code below)


# ─── Phase 4: QA ────────────────────────────────────────────────────


def _run_qa_phase(
    topic: str,
    config: DistillConfig,
    dossier: str,
    report: str,
    written_sections: list[dict],
    tracker: CostTracker | None = None,
) -> tuple[list[dict], int]:
    """Run QA review and fix failed sections. Returns (sections, rewrite_count)."""
    rc = router_config_from_distill(config)

    # Run QA review
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

    # Parse which sections need rewrite
    failed_sections = _parse_qa_failures(qa_result)

    # Display QA results
    pass_count = len(written_sections) - len(failed_sections)
    console.print(f"  [green]{pass_count} PASS[/green]  [red]{len(failed_sections)} FAIL[/red]")

    if not failed_sections:
        console.print("  [green]All sections passed QA[/green]")
        return written_sections, 0

    for title in failed_sections:
        console.print(f"  [red]FAIL: {title}[/red]")

    # Extract per-section QA feedback
    qa_by_section = _extract_section_feedback(qa_result)

    # Rewrite failed sections (one attempt each)
    rewrote = 0
    # Build lookup from both full list and active sections
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
        # Match section headers like "### Executive Briefing"
        if stripped.startswith("### ") and stripped != "### OVERALL":
            current_section = stripped[4:].strip()
        # Match score lines
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
            # Save previous section
            if current_section and current_lines:
                feedback[current_section] = "\n".join(current_lines)
            current_section = stripped[4:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    # Save last section
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

    # Load channel synthesis for creator_consensus section
    syntheses = _load_syntheses(topic, config, scope, channel_name)
    if syntheses:
        tagged["creator_consensus"] = syntheses

    # Load vendor-specific insights for vendor_battleground
    vendor_insights = _load_tagged_insights(
        topic,
        config,
        scope,
        channel_name,
        keywords=[
            "Microsoft",
            "Azure",
            "Google",
            "AWS",
            "NVIDIA",
            "OpenAI",
            "Anthropic",
        ],
        max_chars=30000,
    )
    if vendor_insights:
        tagged["vendor_battleground"] = vendor_insights

    # Load customer/enterprise insights
    enterprise_insights = _load_tagged_insights(
        topic,
        config,
        scope,
        channel_name,
        keywords=[
            "enterprise",
            "customer",
            "production",
            "deploy",
            "ROI",
            "TCO",
            "pricing",
        ],
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
            parts.append(f"### {ch} Channel Synthesis\n{synth_file.read_text(encoding='utf-8')}")

    # Topic synthesis
    topic_synth = find_artifact(config.topic_dir(topic), "topic_synthesis", identity=topic)
    if topic_synth.exists():
        parts.append(f"### Topic Synthesis: {topic}\n{topic_synth.read_text(encoding='utf-8')}")

    return "\n\n".join(parts) if parts else ""


def _load_tagged_insights(
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

            # Check if any keyword appears
            if any(kw in content_lower for kw in keywords_lower):
                # Get title from metadata
                meta_file = vid_dir / "metadata.json"
                title = vid_dir.name
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    title = meta.get("title", vid_dir.name)

                entry = f"**{title}** ({ch}):\n{content}\n"
                if total_chars + len(entry) > max_chars:
                    break
                matching.append(entry)
                total_chars += len(entry)

    return "\n---\n".join(matching) if matching else ""


# ─── Helpers ─────────────────────────────────────────────────────────


def _clean_section_output(content: str) -> str:
    """Strip word counts, numbered citations, and meta-commentary from LLM output."""
    import re

    # Remove trailing "(Word count: 1,128)" or "(1247 words)" patterns
    content = re.sub(r"\n*\(Word count:?\s*[\d,]+\)\s*$", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\n*\([\d,]+\s*words?\)\s*$", "", content, flags=re.IGNORECASE)
    # Also catch them mid-text at end of paragraphs
    content = re.sub(r"\s*\(Word count:?\s*[\d,]+\)", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*\([\d,]+\s*words?\)", "", content, flags=re.IGNORECASE)
    # Strip numbered citation artifacts like [cite: 1], [cite: 2,3], [cite: 1, 2]
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
