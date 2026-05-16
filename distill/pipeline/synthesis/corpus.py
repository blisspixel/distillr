"""Mixed-source topic corpus synthesis."""

from __future__ import annotations

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


def synthesize_corpus(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    source_sections: dict[str, str] = {}

    topic_dir = config.topic_dir(topic)
    topic_synth = find_artifact(topic_dir, "topic_synthesis", identity=topic)
    if topic_synth.exists():
        link = emit_wiki_link(f"Topic synthesis: {topic}", topic, "topic_synthesis")
        source_sections["YouTube / Website Topic Synthesis"] = (
            f"Source: {link}\n" + topic_synth.read_text(encoding="utf-8")
        )

    paper_synth = find_artifact(topic_dir, "paper_synthesis", identity=topic)
    if paper_synth.exists():
        link = emit_wiki_link(f"Paper synthesis: {topic}", topic, "paper_synthesis")
        source_sections["Paper Synthesis"] = f"Source: {link}\n" + paper_synth.read_text(
            encoding="utf-8"
        )

    sites_dir = config.sites_dir(topic)
    if sites_dir.exists():
        for site_dir in sorted(sites_dir.iterdir()):
            if not site_dir.is_dir():
                continue
            synth_file = find_artifact(
                site_dir,
                "site_synthesis",
                identity=f"{topic}_{site_dir.name}",
            )
            if synth_file.exists():
                link = emit_wiki_link(
                    f"Site synthesis: {site_dir.name}",
                    f"{topic}_{site_dir.name}",
                    "site_synthesis",
                )
                source_sections[f"Site: {site_dir.name}"] = (
                    f"Source: {link}\n" + synth_file.read_text(encoding="utf-8")
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
