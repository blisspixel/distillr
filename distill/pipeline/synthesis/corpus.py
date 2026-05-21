"""Mixed-source topic corpus synthesis."""

from __future__ import annotations

from pathlib import Path

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
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.synthesis import corpus_synthesis_prompt

__all__ = [
    "synthesize_corpus",
]


def _collect_subdir_sections(
    parent_dir: Path,
    topic: str,
    artifact_type: str,
    section_prefix: str,
    link_title_prefix: str,
) -> dict[str, str]:
    """Collect per-subdirectory synthesis artifacts (channels or sites) as
    labeled corpus sections, each prefixed with a wikilink to its source."""
    sections: dict[str, str] = {}
    if not parent_dir.exists():
        return sections
    for sub_dir in sorted(parent_dir.iterdir()):
        if not sub_dir.is_dir():
            continue
        identity = f"{topic}_{sub_dir.name}"
        synth_file = find_artifact(sub_dir, artifact_type, identity=identity)
        if not synth_file.exists():
            continue
        link = emit_wiki_link(f"{link_title_prefix}: {sub_dir.name}", identity, artifact_type)
        sections[f"{section_prefix}: {sub_dir.name}"] = f"Source: {link}\n" + synth_file.read_text(
            encoding="utf-8"
        )
    return sections


def synthesize_corpus(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    source_sections: dict[str, str] = {}

    topic_dir = config.topic_dir(topic)

    # Read per-channel video syntheses directly rather than the rolled-up
    # topic_synthesis file. The topic_synthesis identity is written by both the
    # video producer (synthesize_topic) and the website producer
    # (synthesize_site_topic); in a mixed-source run the website synthesis
    # overwrites the video one, which previously dropped all video intelligence
    # from the corpus. It also goes unwritten entirely for single-channel topics
    # (synthesize_topic needs >=2 channels). Reading channels directly mirrors
    # how site syntheses are read and makes the corpus complete regardless.
    source_sections.update(
        _collect_subdir_sections(
            topic_dir / "channels", topic, "synthesis", "Video channel", "Channel synthesis"
        )
    )

    paper_synth = find_artifact(topic_dir, "paper_synthesis", identity=topic)
    if paper_synth.exists():
        link = emit_wiki_link(f"Paper synthesis: {topic}", topic, "paper_synthesis")
        source_sections["Paper Synthesis"] = f"Source: {link}\n" + paper_synth.read_text(
            encoding="utf-8"
        )

    source_sections.update(
        _collect_subdir_sections(
            config.sites_dir(topic), topic, "site_synthesis", "Site", "Site synthesis"
        )
    )

    if not source_sections:
        return ""

    # Skip corpus synthesis when the only input is the paper synthesis itself.
    # Running it would be a summary-of-a-summary: zero new information over
    # paper_synthesis.md, and the model can only meta-comment on its single
    # input. Corpus synthesis is only meaningful when bridging multiple source
    # types (YouTube/sites/papers). For papers-only topics the paper synthesis
    # IS the corpus synthesis.
    if list(source_sections.keys()) == ["Paper Synthesis"]:
        return ""

    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=corpus_synthesis_prompt(topic, source_sections),
        call_type="corpus_synthesis",
    )
    synthesis = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="corpus_synthesis",
            )
        )
    write_markdown_artifact(
        topic_dir,
        "corpus_synthesis",
        synthesis,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="corpus-synthesis",
            title=f"Corpus synthesis: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "mixed"),
            synthesis_scope="corpus-consensus",
            extra={"legacy_filename": "corpus_synthesis.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id="synthesis.corpus.v1",
            ),
        ),
    )
    return synthesis
