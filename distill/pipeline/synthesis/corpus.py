# pyright: strict
"""Mixed-source topic corpus synthesis."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
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
from distill.prompts.registry import PROMPT_IDS
from distill.prompts.synthesis import corpus_synthesis_prompt

__all__ = [
    "has_corpus_synthesis_inputs",
    "has_two_pass_synthesis_inputs",
    "synthesize_corpus",
    "synthesize_corpus_from_claims",
]

logger = logging.getLogger(__name__)

_CLAIM_HANDLE_RE = re.compile(r"(?<![A-Za-z0-9_])C(\d+)(?![A-Za-z0-9_])")


def _unknown_claim_handles(synthesis: str, claim_count: int) -> tuple[str, ...]:
    """Return cited claim handles that are outside the rendered claim set."""
    allowed = {f"C{index}" for index in range(1, claim_count + 1)}
    unknown: list[str] = []
    seen: set[str] = set()
    for match in _CLAIM_HANDLE_RE.finditer(synthesis):
        handle = f"C{match.group(1)}"
        if handle in allowed or handle in seen:
            continue
        unknown.append(handle)
        seen.add(handle)
    return tuple(unknown)


def synthesize_corpus_from_claims(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    *,
    style: str = "",
    now_iso: str | None = None,
) -> str | None:
    """Two-pass corpus synthesis: extract claims, then synthesize over the set.

    Pass 1 runs ``run_claims`` to build/refresh the per-topic ``claims.jsonl``
    (one LLM call per not-yet-extracted insight). Pass 2 feeds the full claim
    set to ``claim_synthesis_prompt`` so the model clusters claims, names
    contradictions, and cites each statement back to specific claims.

    Returns the synthesis text, ``""`` when no claims could be extracted
    (the caller falls back to single-pass), or ``None`` when verify strict
    refused the write -- a refusal must not trigger the paid fallback
    fallback, it must surface. Writes the same ``corpus_synthesis``
    artifact as the single-pass path, tagged with the claim-synthesis prompt id
    and ``two_pass: true`` provenance.
    """
    from distill.claims.exports import read_claims
    from distill.claims.pipeline import run_claims
    from distill.prompts.claims import (
        CLAIM_SYNTHESIS_PROMPT_ID,
        claim_synthesis_prompt,
        claims_receipt,
    )

    topic_dir = config.topic_dir(topic)
    rc = RouterConfig()

    run_claims(topic, topic_dir, rc=rc, tracker=tracker, now_iso=now_iso)
    claims = read_claims(topic_dir)
    if not claims:
        logger.info("Two-pass synthesis: no claims extracted for %s", topic)
        return ""

    response = llm_call(
        rc,
        workload_tag="synthesis",
        prompt=claim_synthesis_prompt(topic, claims, style=style),
        call_type="corpus_synthesis_two_pass",
        usage_tracker=tracker,
    )
    synthesis = response.text
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="corpus_synthesis_two_pass"))

    unknown_handles = _unknown_claim_handles(synthesis, len(claims))
    if unknown_handles:
        logger.warning(
            "corpus synthesis for %s not written: unknown claim handle(s): %s",
            topic,
            ", ".join(unknown_handles),
        )
        return None

    # Verify against the rendered claim set -- exactly the evidence the
    # synthesis prompt embedded, so a number or assertion the model introduced
    # beyond the claims is flagged. Strict refuses the write and keeps any
    # previous corpus synthesis in place.
    from distill.pipeline.verify import run_synthesis_verify

    if run_synthesis_verify(
        topic_dir,
        synthesis,
        claims_receipt(claims),
        verify_mode=config.distill_verify,
        identity=f"{topic}-corpus-synthesis",
        insight_name=f"{topic} corpus synthesis (two-pass)",
        source_name="extracted claim set",
        notify=logger.warning,
    ):
        logger.warning("corpus synthesis for %s not written (verify strict)", topic)
        return None

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
            extra={
                "legacy_filename": "corpus_synthesis.md",
                "two_pass": True,
                "claim_count": len(claims),
            },
            provenance=ProvenanceFields(
                model=response.model,
                model_version=response.model,
                temperature=0.0,
                prompt_id=CLAIM_SYNTHESIS_PROMPT_ID,
            ),
        ),
    )

    try:
        from distill.library import claude_md

        claude_md.refresh_for_topic(config.library_dir, topic_dir, topic)
    except Exception as exc:
        logger.debug("CLAUDE.md refresh skipped for %s: %s", topic, exc)

    return synthesis


def _iter_subdir_artifacts(
    parent_dir: Path,
    topic: str,
    artifact_type: str,
    *,
    identity_prefix: str | None = None,
) -> Iterator[tuple[Path, Path]]:
    if not parent_dir.exists():
        return
    prefix = identity_prefix or topic
    for sub_dir in sorted(parent_dir.iterdir()):
        if not sub_dir.is_dir():
            continue
        identity = f"{prefix}_{sub_dir.name}"
        synth_file = find_artifact(sub_dir, artifact_type, identity=identity)
        if synth_file.exists():
            yield sub_dir, synth_file


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
    for sub_dir, synth_file in _iter_subdir_artifacts(parent_dir, topic, artifact_type):
        identity = f"{topic}_{sub_dir.name}"
        link = emit_wiki_link(f"{link_title_prefix}: {sub_dir.name}", identity, artifact_type)
        sections[f"{section_prefix}: {sub_dir.name}"] = f"Source: {link}\n" + synth_file.read_text(
            encoding="utf-8"
        )
    return sections


def has_corpus_synthesis_inputs(topic: str, config: DistillConfig) -> bool:
    """Return true when single-pass corpus synthesis would make an LLM call."""
    topic_dir = config.topic_dir(topic)
    channel_count = sum(
        1 for _ in _iter_subdir_artifacts(topic_dir / "channels", topic, "synthesis")
    )
    site_count = sum(
        1 for _ in _iter_subdir_artifacts(config.sites_dir(topic), topic, "site_synthesis")
    )
    has_paper = find_artifact(topic_dir, "paper_synthesis", identity=topic).exists()
    source_count = channel_count + site_count + int(has_paper)
    return source_count > 0 and not (source_count == 1 and has_paper)


def has_two_pass_synthesis_inputs(topic: str, config: DistillConfig) -> bool:
    """Return true when claim-based synthesis has evidence to process.

    Per-source insights are discovered recursively so this covers every ingest
    layout, including X posts, papers, repositories, feeds, and local files.
    Existing claims also count: they remain valid synthesis inputs when the
    extraction pass has already completed.
    """
    from distill.claims.exports import read_claims
    from distill.library.insights import discover_insights

    topic_dir = config.topic_dir(topic)
    return bool(discover_insights(topic_dir) or read_claims(topic_dir))


def synthesize_corpus(
    topic: str,
    config: DistillConfig,
    tracker: CostTracker | None = None,
    *,
    style: str = "",
    two_pass: bool = False,
    now_iso: str | None = None,
) -> str:
    # Opt-in two-pass: synthesize over an extracted claim set instead of the
    # per-source summaries. Falls back to single-pass when no claims could be
    # extracted (e.g. a topic with no insights yet), so the flag never silently
    # produces an empty synthesis where single-pass would have produced one.
    if two_pass:
        result = synthesize_corpus_from_claims(
            topic, config, tracker=tracker, style=style, now_iso=now_iso
        )
        if result is None:
            # Verify strict refused the two-pass write. Falling back would
            # spend again on a synthesis built from the same flagged corpus.
            return ""
        if result:
            return result
        logger.info("Two-pass produced no claims for %s; falling back to single-pass", topic)

    source_sections: dict[str, str] = {}

    topic_dir = config.topic_dir(topic)

    # Read per-channel video syntheses directly rather than summarizing the
    # rolled-up topic synthesis a second time. The rollup is also absent for
    # single-channel topics because ``synthesize_topic`` requires two channels.
    # Reading channels directly mirrors site collection and keeps the corpus
    # complete regardless of whether a modality-specific rollup exists.
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
        prompt=corpus_synthesis_prompt(topic, source_sections, style=style),
        call_type="corpus_synthesis",
        usage_tracker=tracker,
    )
    synthesis = response.text
    if tracker:
        tracker.record(TokenUsage.from_response(response, call_type="corpus_synthesis"))

    # Verify against the per-source sections the prompt was built from; the
    # corpus synthesis bridges source types, so an attribution swap here is
    # exactly the class the hook exists to catch.
    from distill.pipeline.verify import run_synthesis_verify

    if run_synthesis_verify(
        topic_dir,
        synthesis,
        "\n\n".join(source_sections.values()),
        verify_mode=config.distill_verify,
        identity=f"{topic}-corpus-synthesis",
        insight_name=f"{topic} corpus synthesis",
        source_name="per-source syntheses",
        notify=logger.warning,
    ):
        logger.warning("corpus synthesis for %s not written (verify strict)", topic)
        return ""

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
                prompt_id=PROMPT_IDS["synthesis.corpus"],
            ),
        ),
    )

    # Refresh the agent-orientation CLAUDE.md for this topic + the library index.
    # Best-effort: a failure here must never fail an otherwise-successful run.
    try:
        from distill.library import claude_md

        claude_md.refresh_for_topic(config.library_dir, topic_dir, topic)
    except Exception as exc:
        logger.debug("CLAUDE.md refresh skipped for %s: %s", topic, exc)

    return synthesis
