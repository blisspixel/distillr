"""Website page analysis and synthesis helpers."""

from __future__ import annotations

from rich.console import Console

from distill.config import DistillConfig
from distill.ingestors.sites.scraper import SitePage, build_page_document
from distill.library.paths import (
    ProvenanceFields,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.synthesis import (
    site_page_insight_prompt,
    site_synthesis_prompt,
    site_topic_synthesis_prompt,
)

__all__ = [
    "analyze_site_page",
    "synthesize_site",
    "synthesize_site_topic",
]

console = Console()


def analyze_site_page(
    page: SitePage,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
) -> str:
    """Analyze a site page. ``router_config`` lets a caller (e.g. the eval
    harness) force a specific model/provider; defaults to the configured routing."""
    rc = router_config or RouterConfig()
    prompt = site_page_insight_prompt(
        page.title,
        page.url,
        page.site_name,
        page.page_type,
        build_page_document(page),
    )
    response = llm_call(rc, workload_tag="site", prompt=prompt, call_type="site_page")
    result = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="site_page",
            )
        )
    safe_title = page.title.replace('"', '\\"')
    return (
        f"---\n"
        f'page_title: "{safe_title}"\n'
        f"site: {page.site_name}\n"
        f"page_type: {page.page_type}\n"
        f"url: {page.url}\n"
        f"analyzed_by: {response.model}\n"
        f"model: {response.model}\n"
        f"model_version: {response.model}\n"
        f"temperature: 0.0\n"
        f'prompt_id: "analysis.site_page.v1"\n'
        "---\n\n"
        f"{result}\n"
    )


def synthesize_site(
    topic: str,
    site_name: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    pages_dir = config.site_pages_dir(topic, site_name)
    if not pages_dir.exists():
        return ""

    parts = []
    for page_dir in sorted(pages_dir.iterdir()):
        if not page_dir.is_dir():
            continue
        insights_file = find_artifact(page_dir, "insights")
        if not insights_file.exists():
            continue
        parts.append(f"\n\n---\n{insights_file.read_text(encoding='utf-8')}")

    if not parts:
        return ""

    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=site_synthesis_prompt(site_name, "".join(parts)),
        call_type="site_synthesis",
    )
    synthesis = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="site_synthesis",
            )
        )
    site_dir = config.site_dir(topic, site_name)
    write_markdown_artifact(
        site_dir,
        "site_synthesis",
        synthesis,
        identity=f"{topic}_{site_dir.name}",
        frontmatter=base_frontmatter(
            artifact_type="site-synthesis",
            title=f"Site synthesis: {site_name}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "website"),
            synthesis_scope="corpus-consensus",
            extra={"site": site_name, "legacy_filename": "synthesis.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id="synthesis.site.v1",
            ),
        ),
    )
    return synthesis


def synthesize_site_topic(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
) -> str:
    sites_dir = config.sites_dir(topic)
    if not sites_dir.exists():
        return ""

    site_summaries: dict[str, str] = {}
    for site_dir in sorted(sites_dir.iterdir()):
        if not site_dir.is_dir():
            continue
        synth_file = find_artifact(
            site_dir,
            "site_synthesis",
            identity=f"{topic}_{site_dir.name}",
        )
        if synth_file.exists():
            site_summaries[site_dir.name] = synth_file.read_text(encoding="utf-8")

    if not site_summaries:
        return ""

    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=site_topic_synthesis_prompt(topic, site_summaries),
        call_type="site_topic_synthesis",
    )
    synthesis = response.text
    if tracker:
        tracker.record(
            TokenUsage(
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                model=response.model,
                call_type="site_topic_synthesis",
            )
        )
    write_markdown_artifact(
        config.topic_dir(topic),
        "topic_synthesis",
        synthesis,
        identity=topic,
        frontmatter=base_frontmatter(
            artifact_type="topic-synthesis",
            title=f"Topic synthesis: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "website"),
            synthesis_scope="corpus-consensus",
            extra={"legacy_filename": "topic_synthesis.md"},
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id="synthesis.site_topic.v1",
            ),
        ),
    )
    return synthesis
