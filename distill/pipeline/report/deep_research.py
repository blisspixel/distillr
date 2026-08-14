# pyright: strict
"""Deep Research -- Gemini Deep Research for validated intelligence."""

from pathlib import Path

from distill._console import console
from distill.config import DistillConfig
from distill.library.paths import (
    ProvenanceFields,
    artifact_path,
    base_frontmatter,
    tags_for,
    write_markdown_artifact,
)
from distill.llm.cost_policy import require_route_allowed
from distill.pipeline.citation_refs import unresolved_numbered_citation_reason
from distill.pipeline.costs import BudgetExceededError, CostTracker
from distill.pipeline.report._interactions import (
    await_interaction,
    file_search_grounding_reason,
    interaction_text,
    preflight_metered_interaction,
    require_cost_tracker,
    submit_metered_interaction,
)
from distill.pipeline.report.file_search import create_research_store, delete_store
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.report import deep_research_prompt

__all__ = [
    "_get_report_path",
    "run_deep_research",
]

DEEP_RESEARCH_MODEL = "deep-research-preview-04-2026"


def __getattr__(name: str) -> object:
    """Lazily expose ``genai`` so importing this module stays cheap.

    The google-genai SDK costs roughly a second of import time, so it is
    imported only when a report actually runs. Tests that patch
    ``distill.pipeline.report.deep_research.genai.Client`` keep working:
    this hook resolves ``genai`` to the real module on first attribute
    access.
    """
    if name == "genai":
        from google import genai

        return genai
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def run_deep_research(
    topic: str,
    config: DistillConfig,
    scope: str = "topic",
    channel_name: str | None = None,
    focus: str | None = None,
    test: bool = False,
    tracker: CostTracker | None = None,
) -> str | None:
    """Run Gemini Deep Research on the corpus using File Search grounding."""
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

    prompt = deep_research_prompt(topic, corpus_summary="", focus=focus)

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

        completed = await_interaction(client, interaction_id, console, label="Research")
        if completed is None:
            return None

        grounding_refusal = file_search_grounding_reason(completed)
        if grounding_refusal:
            console.print(f"[red]Deep research refused:[/red] {grounding_refusal}")
            return None
        result_text = interaction_text(completed)
        if not result_text:
            console.print("[red]Research completed but no output received[/red]")
            return None
        refusal = unresolved_numbered_citation_reason(result_text)
        if refusal:
            console.print(f"[red]Deep research refused:[/red] {refusal}")
            return None

        output_path = _write_report_artifact(result_text, topic, config, scope, channel_name)
        console.print(f"[green]Findings saved to {output_path}[/green]")
        return result_text
    except BudgetExceededError:
        raise
    except Exception as exc:
        console.print(f"[red]Deep research error: {exc}[/red]")
        return None
    finally:
        delete_store(client, store_name)


def _get_report_path(
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> Path:
    if scope == "channel" and channel_name:
        return artifact_path(
            config.channel_dir(topic, channel_name),
            "report",
            identity=f"{topic}_{channel_name}",
        )
    if scope == "topic":
        return artifact_path(config.topic_dir(topic), "report", identity=topic)
    return artifact_path(config.library_dir, "report", identity="library")


def _write_report_artifact(
    content: str,
    topic: str,
    config: DistillConfig,
    scope: str,
    channel_name: str | None,
) -> Path:
    if scope == "channel" and channel_name:
        directory = config.channel_dir(topic, channel_name)
        identity = f"{topic}_{channel_name}"
        title = f"Channel report: {channel_name}"
        extra = {"channel": channel_name, "legacy_filename": "report.md"}
    elif scope == "topic":
        directory = config.topic_dir(topic)
        identity = topic
        title = f"Topic report: {topic}"
        extra = {"legacy_filename": "report.md"}
    else:
        directory = config.library_dir
        identity = "library"
        title = "Library report"
        extra = {"legacy_filename": "report.md"}
    directory.mkdir(parents=True, exist_ok=True)
    return write_markdown_artifact(
        directory,
        "report",
        content,
        identity=identity,
        frontmatter=base_frontmatter(
            artifact_type="report",
            title=title,
            topic=topic if scope != "all" else "",
            source="distill",
            tags=tags_for(topic, "report") if scope != "all" else tags_for("", "report"),
            synthesis_scope="interpretation",
            extra=extra,
            provenance=ProvenanceFields(
                model=DEEP_RESEARCH_MODEL,
                model_version=DEEP_RESEARCH_MODEL,
                temperature=0.0,
                prompt_id=PROMPT_IDS["report.deep_research"],
            ),
        ),
    )
