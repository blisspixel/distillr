# pyright: strict
"""Website page analysis and synthesis helpers."""

from __future__ import annotations

import json
from dataclasses import replace

from distill._console import console
from distill.config import DistillConfig
from distill.ingestors.sites._site_urls import (
    site_attachment_context_for_persistence,
    site_url_for_persistence,
    site_url_list_for_persistence,
)
from distill.ingestors.sites.scraper import SitePage, build_page_document
from distill.library.intent import CorpusIntent
from distill.library.paths import (
    ProvenanceFields,
    base_frontmatter,
    find_artifact,
    site_name_from_url,
    tags_for,
)
from distill.llm import call as llm_call
from distill.llm.router import RouterConfig
from distill.parsing import read_local_utf8_text
from distill.pipeline.costs import CostTracker, TokenUsage
from distill.prompts.registry import PROMPT_IDS
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


def _safe_site_name(stored: str, safe_derived: str) -> str:
    """Return a site name that cannot carry inline URL credentials.

    This used to detect an auto-derived name by comparing it against the
    *unsanitized* derivation, on the assumption that ``site_name_from_url``
    leaked userinfo. That derivation is now sanitized at the source, so the
    equality no longer identifies legacy names -- and a stored name written by
    an earlier version still contains the credential. Any ``@`` in a stored site
    name is userinfo residue (a bare host never contains one), so scrub it
    regardless of how it was produced, while still preserving a deliberate
    operator-supplied label.
    """
    if not stored or stored == safe_derived or "@" in stored:
        return safe_derived
    return stored


def _page_for_model(page: SitePage) -> SitePage:
    safe_derived_site_name = site_name_from_url(site_url_for_persistence(page.url))
    return replace(
        page,
        site_name=_safe_site_name(page.site_name, safe_derived_site_name),
        url=site_url_for_persistence(page.url),
        final_url=site_url_for_persistence(page.final_url),
        canonical_url=site_url_for_persistence(page.canonical_url),
        source_url=site_url_for_persistence(page.source_url),
        links=site_url_list_for_persistence(page.links),
        pdf_links=site_url_list_for_persistence(page.pdf_links),
        video_links=site_url_list_for_persistence(page.video_links),
        attachment_context=site_attachment_context_for_persistence(
            page.attachment_context,
            [*page.pdf_links, *page.video_links],
        ),
    )


def analyze_site_page(
    page: SitePage,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    router_config: RouterConfig | None = None,
    *,
    intent: CorpusIntent | None = None,
) -> str:
    """Analyze a site page. ``router_config`` lets a caller (e.g. the eval
    harness) force a specific model/provider; defaults to the configured routing.
    ``intent`` selects the analysis lens and goal focus; ``None`` keeps neutral."""
    safe_page = _page_for_model(page)
    rc = router_config or RouterConfig()
    goal = intent.goal if intent else ""
    lens = intent.lens if intent else ""
    prompt = site_page_insight_prompt(
        safe_page.title,
        safe_page.url,
        safe_page.site_name,
        safe_page.page_type,
        build_page_document(safe_page),
        goal=goal,
        lens=lens,
    )
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=prompt,
        call_type="site_page",
        usage_tracker=tracker,
    )
    result = response.text
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="site_page"))

    # JSON-encode page-derived values: a newline (or quote) in an ingested
    # page's title/metadata would otherwise break out of its line and inject
    # extra frontmatter fields. json.dumps quotes and escapes both.
    def _q(value: object) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    return (
        f"---\n"
        f"page_title: {_q(safe_page.title)}\n"
        f"site: {_q(safe_page.site_name)}\n"
        f"page_type: {_q(safe_page.page_type)}\n"
        f"url: {_q(safe_page.url)}\n"
        f"analyzed_by: {response.model}\n"
        f"model: {response.model}\n"
        f"model_version: {response.model}\n"
        f"temperature: 0.0\n"
        f'prompt_id: "analysis.site_page.v2"\n'
        f"lens: {lens or 'general'}\n"
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

    parts: list[str] = []
    for page_dir in sorted(pages_dir.iterdir()):
        if not page_dir.is_dir():
            continue
        insights_file = find_artifact(page_dir, "insights")
        content = read_local_utf8_text(insights_file)
        if content is None:
            continue
        parts.append(f"\n\n---\n{content}")

    if not parts:
        return ""

    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=site_synthesis_prompt(site_name, "".join(parts)),
        call_type="site_synthesis",
        usage_tracker=tracker,
    )
    synthesis = response.text
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="site_synthesis"))
    site_dir = config.site_dir(topic, site_name)

    # Verify against the per-page insights the prompt was built from; strict
    # mode refuses the write and keeps any previous site synthesis in place.
    from distill.pipeline.verify import write_verified_synthesis

    output = write_verified_synthesis(
        site_dir,
        "site_synthesis",
        synthesis,
        "".join(parts),
        verify_mode=config.distill_verify,
        artifact_identity=f"{topic}_{site_dir.name}",
        verify_identity=f"{topic}_{site_dir.name}",
        source_name="per-page insights",
        notify=lambda line: console.print(f"  [yellow]{line}[/yellow]"),
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
                prompt_id=PROMPT_IDS["synthesis.site"],
            ),
        ),
    )
    if output is None:
        console.print(
            f"  [yellow]Site synthesis for {site_name} not written (verification gate)[/yellow]"
        )
        return ""
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
        content = read_local_utf8_text(synth_file)
        if content is not None:
            site_summaries[site_dir.name] = content

    if not site_summaries:
        return ""

    rc = RouterConfig()
    response = llm_call(
        rc,
        workload_tag="site",
        prompt=site_topic_synthesis_prompt(topic, site_summaries),
        call_type="site_topic_synthesis",
        usage_tracker=tracker,
    )
    synthesis = response.text
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="site_topic_synthesis"))

    # Site and video topic rollups summarize different receipt sets. Keep both
    # the verification identity and artifact identity modality-specific so a
    # later producer cannot replace valid evidence from the other modality.
    from distill.pipeline.verify import write_verified_synthesis

    output = write_verified_synthesis(
        config.topic_dir(topic),
        "site_synthesis",
        synthesis,
        "\n\n".join(site_summaries.values()),
        verify_mode=config.distill_verify,
        artifact_identity=topic,
        verify_identity=f"{topic}-site-topic-synthesis",
        source_name="site syntheses",
        notify=lambda line: console.print(f"  [yellow]{line}[/yellow]"),
        frontmatter=base_frontmatter(
            artifact_type="site-topic-synthesis",
            title=f"Site synthesis: {topic}",
            topic=topic,
            source="distill",
            tags=tags_for(topic, "website"),
            synthesis_scope="corpus-consensus",
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=PROMPT_IDS["synthesis.site_topic"],
            ),
        ),
    )
    if output is None:
        console.print(
            f"  [yellow]Topic synthesis for {topic} not written (verification gate)[/yellow]"
        )
        return ""
    return synthesis
