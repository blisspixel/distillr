"""Synthesis -- per-channel and per-topic knowledge bases."""

import json
import logging

from distill._console import console
from distill.config import DistillConfig
from distill.library.paths import (
    ProvenanceFields,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.library.wikilinks import emit_wiki_link
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import BudgetExceededError, CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.synthesis import channel_synthesis_prompt, topic_synthesis_prompt

logger = logging.getLogger(__name__)

__all__ = [
    "synthesize_channel",
    "synthesize_topic",
]


def _video_link_header(video_dir) -> str:
    """Wiki-link header for one video's insight, from its metadata.json (best
    effort -- a missing or corrupt metadata file falls back to the dir name)."""
    title = source_id = video_dir.name
    meta_file = video_dir / "metadata.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                title = meta.get("title", title)
                source_id = meta.get("video_id", source_id)
        except (json.JSONDecodeError, OSError):
            pass
    return emit_wiki_link(title, source_id, "insights")


def _gather_video_insights(videos_dir) -> str:
    """Concatenate every video insight under a channel, each with a source link."""
    parts: list[str] = []
    for video_dir in sorted(videos_dir.iterdir()):
        if not video_dir.is_dir():
            continue
        path = find_artifact(video_dir, "insights")
        if not path.exists():
            continue
        link = _video_link_header(video_dir)
        parts.append(f"\n\n---\nSource: {link}\n{path.read_text(encoding='utf-8')}")
    return "".join(parts)


def synthesize_channel(
    topic: str,
    channel_name: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    """Generate channel-level synthesis from all video insights."""
    channel_dir = config.channel_dir(topic, channel_name)
    videos_dir = channel_dir / "videos"

    if not videos_dir.exists():
        console.print(f"  [yellow]No videos directory for {channel_name}[/yellow]")
        return ""

    context_file = channel_dir / "channel_context.md"
    channel_context = context_file.read_text(encoding="utf-8") if context_file.exists() else ""

    all_insights = _gather_video_insights(videos_dir)
    if not all_insights:
        console.print(f"  [yellow]No insights found for {channel_name}[/yellow]")
        return ""

    console.print(f"  [cyan]Synthesizing videos for {channel_name}...[/cyan]")

    try:
        rc = RouterConfig()
        prompt = channel_synthesis_prompt(channel_name, channel_context, all_insights)
        response = llm_call(
            rc, workload_tag="synthesis", prompt=prompt, call_type="channel_synthesis"
        )
        synthesis = response.text
        if tracker:
            tracker.record(
                TokenUsage(
                    prompt_tokens=response.input_tokens,
                    completion_tokens=response.output_tokens,
                    model=response.model,
                    call_type="channel_synthesis",
                )
            )
    except BudgetExceededError:
        # The spend cap is a hard stop, never a per-channel issue to swallow
        # (the 0.12.13 defect class: each call spends before recording).
        raise
    except Exception as e:
        console.print(f"  [red]Channel synthesis API error: {e}[/red]")
        return ""

    # Verify the synthesis against its own inputs (the per-video insights are
    # the receipt); strict mode refuses the write and keeps any previous
    # channel synthesis in place.
    from distill.pipeline.verify import run_synthesis_verify

    if run_synthesis_verify(
        channel_dir,
        synthesis,
        all_insights,
        verify_mode=config.distill_verify,
        identity=f"{topic}_{channel_dir.name}",
        insight_name=f"{channel_name} channel synthesis",
        source_name="per-video insights",
        notify=lambda line: console.print(f"  [yellow]{line}[/yellow]"),
    ):
        console.print(
            f"  [yellow]Channel synthesis for {channel_name} not written (verify strict)[/yellow]"
        )
        return ""

    output_file = write_markdown_artifact(
        channel_dir,
        "synthesis",
        synthesis,
        identity=f"{topic}_{channel_dir.name}",
        frontmatter=base_frontmatter(
            artifact_type="channel-synthesis",
            title=f"Channel synthesis: {channel_name}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "youtube"),
            synthesis_scope="corpus-consensus",
            extra={"channel": channel_name, "legacy_filename": "synthesis.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_IDS["synthesis.channel"],
            ),
        ),
    )
    console.print(f"  [green]Saved {output_file}[/green]")

    return synthesis


def _gather_channel_syntheses(topic: str, channels_dir) -> dict[str, str]:
    """Read every channel synthesis under a topic, each prefixed with its link."""
    syntheses: dict[str, str] = {}
    for channel_dir in sorted(channels_dir.iterdir()):
        if not channel_dir.is_dir():
            continue
        identity = f"{topic}_{channel_dir.name}"
        synth_file = find_artifact(channel_dir, "synthesis", identity=identity)
        if not synth_file.exists():
            continue
        link = emit_wiki_link(f"Channel synthesis: {channel_dir.name}", identity, "synthesis")
        syntheses[channel_dir.name] = f"Source: {link}\n" + synth_file.read_text(encoding="utf-8")
    return syntheses


def synthesize_topic(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    *,
    style: str = "",
) -> str:
    """Generate topic-level synthesis from all channel syntheses.

    ``style`` selects an optional register (see ``prompts.synthesis.STYLE_GUIDANCE``).
    """
    topic_dir = config.topic_dir(topic)
    channels_dir = topic_dir / "channels"

    if not channels_dir.exists():
        return ""

    channel_syntheses = _gather_channel_syntheses(topic, channels_dir)

    if len(channel_syntheses) < 2:
        console.print(
            f"  [dim]Only {len(channel_syntheses)} channel(s) -- skipping topic synthesis[/dim]"
        )
        return ""

    console.print(
        f"  [cyan]Synthesizing topic '{topic}' across {len(channel_syntheses)} channels...[/cyan]"
    )

    try:
        rc = RouterConfig()
        prompt = topic_synthesis_prompt(topic, channel_syntheses, style=style)
        response = llm_call(
            rc, workload_tag="synthesis", prompt=prompt, call_type="topic_synthesis"
        )
        synthesis = response.text
        if tracker:
            tracker.record(
                TokenUsage(
                    prompt_tokens=response.input_tokens,
                    completion_tokens=response.output_tokens,
                    model=response.model,
                    call_type="topic_synthesis",
                )
            )
    except BudgetExceededError:
        # Hard stop -- swallowing it here would let a capped multi-channel
        # sweep keep spending (the 0.12.13 defect class).
        raise
    except Exception as e:
        console.print(f"  [red]Topic synthesis API error: {e}[/red]")
        return ""

    # Verify against the channel syntheses the prompt was built from; the
    # sidecar identity is distinct from the artifact's so the three
    # topic-level syntheses can't collide.
    from distill.pipeline.verify import run_synthesis_verify

    if run_synthesis_verify(
        topic_dir,
        synthesis,
        "\n\n".join(channel_syntheses.values()),
        verify_mode=config.distill_verify,
        identity=f"{topic}-topic-synthesis",
        insight_name=f"{topic} topic synthesis",
        source_name="channel syntheses",
        notify=lambda line: console.print(f"  [yellow]{line}[/yellow]"),
    ):
        console.print(f"  [yellow]Topic synthesis for {topic} not written (verify strict)[/yellow]")
        return ""

    output_file = write_markdown_artifact(
        topic_dir,
        "topic_synthesis",
        synthesis,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="topic-synthesis",
            title=f"Topic synthesis: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "youtube"),
            synthesis_scope="corpus-consensus",
            extra={"legacy_filename": "topic_synthesis.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_IDS["synthesis.topic"],
            ),
        ),
    )
    console.print(f"  [green]Saved {output_file}[/green]")

    # Refresh the agent-orientation CLAUDE.md for this topic + the library index.
    # Best-effort: pure templating over what we just wrote, but a failure here
    # must never fail an otherwise-successful synthesis.
    try:
        from distill.library import claude_md

        claude_md.refresh_for_topic(config.library_dir, topic_dir, topic)
    except Exception as exc:
        console.print(f"  [dim]CLAUDE.md refresh skipped: {exc}[/dim]")

    return synthesis
