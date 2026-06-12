"""The self-maintaining audit: one health surface, one report artifact.

The Karpathy-pattern "monthly health check", composed from signals distill
already produces rather than new analysis (a packaging milestone, per the
roadmap): corpus-health warnings (stale syntheses, thin artifacts), contested
concepts, broken wiki-links, coverage gaps with next actions, and -- the piece
that makes the audit a *trust* surface -- the verify-sidecar rollup, which
distinguishes "verified clean" from "flagged" from "never checked" for every
insight in the topic.

Everything here is deterministic filesystem reads; an audit run costs nothing.
The report is written as ``<topic>_Audit.md`` -- itself a corpus artifact an
agent or human can read later -- and the action menu lives in the command
layer, not here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from distill.library.freshness import SynthesisFreshness, collect_synthesis_freshness
from distill.library.insights import discover_insights
from distill.library.links import BrokenLink
from distill.library.paths import base_frontmatter, tags_for, write_markdown_artifact
from distill.prompts.registry import PROMPT_IDS, parse_prompt_id

__all__ = [
    "AuditReport",
    "LibraryHygiene",
    "StalenessRollup",
    "SynthesisFreshness",
    "VerifyRollup",
    "collect_library_hygiene",
    "collect_staleness",
    "collect_synthesis_freshness",
    "collect_verify_rollup",
    "frontmatter_field",
    "reanalysis_commands",
    "render_audit_md",
    "render_library_audit_md",
    "write_audit_artifact",
]


@dataclass(frozen=True)
class VerifyRollup:
    """Verification coverage for a topic's insights, from ``_Verify.json`` sidecars."""

    insights_total: int
    checked: int
    clean: int
    flagged: list[dict] = field(default_factory=list)  # {insight, token, kind, context}

    @property
    def never_checked(self) -> int:
        return self.insights_total - self.checked


@dataclass(frozen=True)
class StalenessRollup:
    """Prompt-version drift across a topic's insights.

    Frontmatter ``prompt_id`` (recorded since 0.7) compared against the
    central registry (`distill.prompts.registry`) -- the same dict the
    writers stamp from, so the floor table cannot itself drift. "Stale"
    means a newer prompt version exists for that family: the artifact is not
    wrong, but a re-analysis would apply lessons the prompt has learned
    since.
    """

    current: int = 0
    stale: list[dict] = field(default_factory=list)  # {insight, recorded, current}
    unknown_family: int = 0  # prompt families the registry no longer knows
    no_provenance: int = 0  # artifacts predating provenance stamping


@dataclass(frozen=True)
class AuditReport:
    """Everything one audit run found for one topic."""

    topic: str
    health_warnings: list[str]
    contested: list[dict]  # {name, kind, helpful, harmful, sources}
    broken_links: list[BrokenLink]
    gaps: list[str]
    next_actions: list[str]
    verify: VerifyRollup
    staleness: StalenessRollup = field(default_factory=StalenessRollup)
    near_duplicates: list = field(default_factory=list)  # list[DuplicateGroup]
    freshness: SynthesisFreshness = field(default_factory=SynthesisFreshness)

    @property
    def issue_count(self) -> int:
        return (
            len(self.health_warnings)
            + len(self.contested)
            + len(self.broken_links)
            + len(self.gaps)
            + len(self.verify.flagged)
            + len(self.staleness.stale)
            + len(self.near_duplicates)
            + len(self.freshness.stale)
            + len(self.freshness.shadowed_legacy)
        )


def collect_verify_rollup(topic_dir: Path) -> VerifyRollup:
    """Roll up ``_Verify.json`` sidecars across a topic's insight directories.

    One sidecar per source directory (written beside the insight). Sidecars
    that fail to parse count as never-checked rather than crashing the audit
    (parse-don't-crash over corruptible local state).
    """
    insights = discover_insights(topic_dir)
    checked = 0
    clean = 0
    flagged: list[dict] = []
    for ref in insights:
        sidecars = sorted(ref.path.parent.glob("*_Verify.json"))
        if not sidecars:
            continue
        try:
            data = json.loads(sidecars[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        checked += 1
        unsupported = data.get("unsupported") or []
        if not isinstance(unsupported, list) or not unsupported:
            clean += 1
            continue
        for item in unsupported:
            if isinstance(item, dict):
                flagged.append(
                    {
                        "insight": ref.artifact_path,
                        "token": str(item.get("token", "")),
                        "kind": str(item.get("kind", "")),
                        "context": str(item.get("context", ""))[:200],
                    }
                )
    return VerifyRollup(insights_total=len(insights), checked=checked, clean=clean, flagged=flagged)


def frontmatter_field(text: str, name: str) -> str:
    """Pull one scalar field out of an artifact's frontmatter block, or ''."""
    if not text.startswith("---"):
        return ""
    end = text.find("---", 3)
    if end == -1:
        return ""
    match = re.search(rf'^{re.escape(name)}:\s*"?([^"\r\n]+?)"?\s*$', text[:end], re.MULTILINE)
    return match.group(1).strip() if match else ""


def _frontmatter_prompt_id(text: str) -> str:
    return frontmatter_field(text, "prompt_id")


def collect_staleness(topic_dir: Path) -> StalenessRollup:
    """Compare each insight's recorded ``prompt_id`` to the current registry."""
    current = 0
    stale: list[dict] = []
    unknown_family = 0
    no_provenance = 0
    for ref in discover_insights(topic_dir):
        try:
            text = ref.path.read_text(encoding="utf-8")
        except OSError:
            continue
        recorded = _frontmatter_prompt_id(text)
        if not recorded:
            no_provenance += 1
            continue
        parsed = parse_prompt_id(recorded)
        if parsed is None:
            unknown_family += 1
            continue
        family, version = parsed
        current_id = PROMPT_IDS.get(family)
        if current_id is None:
            unknown_family += 1
            continue
        current_parsed = parse_prompt_id(current_id)
        if current_parsed is not None and version < current_parsed[1]:
            stale.append(
                {"insight": ref.artifact_path, "recorded": recorded, "current": current_id}
            )
        else:
            current += 1
    return StalenessRollup(
        current=current,
        stale=stale,
        unknown_family=unknown_family,
        no_provenance=no_provenance,
    )


_INGESTABLE_HOSTS = ("x.com", "twitter.com", "github.com")


def reanalysis_commands(library_dir: Path, topic: str, stale: list[dict]) -> list[str]:
    """Concrete re-analysis lines for stale artifacts (printed, never run).

    Re-ingesting a source re-runs analysis on the *current* prompt -- that is
    the artifact-level trigger the 0.12 spec asks for (no blanket re-runs).
    Where the recorded ``url`` routes through ``distill ingest`` (X, GitHub,
    feeds), the exact command is printed; arXiv papers re-ingest via
    ``distill papers``; anything else gets the artifact named so the operator
    re-runs its original verb.
    """
    lines: list[str] = []
    for item in stale:
        rel = str(item.get("insight", ""))
        try:
            text = (library_dir / rel).read_text(encoding="utf-8")
        except OSError:
            text = ""
        url = frontmatter_field(text, "url")
        source = frontmatter_field(text, "source")
        recorded = item.get("recorded", "?")
        if source == "arxiv" and url:
            arxiv_id = url.rstrip("/").rsplit("/", 1)[-1]
            lines.append(f'distill papers "{arxiv_id}" --topic {topic} --limit 1  # was {recorded}')
        elif url and (
            any(h in url for h in _INGESTABLE_HOSTS) or url.lower().endswith((".rss", ".xml"))
        ):
            lines.append(f"distill ingest {url} --topic {topic}  # was {recorded}")
        else:
            lines.append(f"# {rel} (was {recorded}) -- re-run its original ingest verb")
    return lines


def _staleness_section(report: AuditReport) -> list[str]:
    s = report.staleness
    lines = [
        "## Prompt staleness (analysis quality drift)",
        "",
        f"- On current prompts: {s.current} | stale: {len(s.stale)} | "
        f"no provenance recorded: {s.no_provenance} | unknown family: {s.unknown_family}",
    ]
    if s.stale:
        lines += [
            "",
            "### Stale artifacts (a newer prompt version exists; re-analysis would apply "
            "lessons learned since)",
            "",
        ]
        lines += [
            f"- `{item['insight']}` -- recorded `{item['recorded']}`, current `{item['current']}`"
            for item in s.stale[:15]
        ]
        if len(s.stale) > 15:
            lines.append(f"- ... and {len(s.stale) - 15} more")
    if s.no_provenance:
        lines.append(
            "- No-provenance artifacts predate prompt stamping; they age out as sources refresh."
        )
    return lines


def _verify_section(report: AuditReport) -> list[str]:
    lines = [
        "## Verification coverage",
        "",
        f"- Insights: {report.verify.insights_total} | verified clean: {report.verify.clean} | "
        f"flagged: {len(report.verify.flagged)} | never checked: {report.verify.never_checked}",
    ]
    if report.verify.never_checked:
        lines.append(
            "- Never-checked insights predate the verify hook (or used `--verify off`); "
            "re-analysis will produce sidecars."
        )
    if report.verify.flagged:
        lines += [
            "",
            "### Flagged claims (support not found -- adjudicate, do not assume false)",
            "",
        ]
        lines += [
            f"- `{f['token']}` ({f['kind']}) in `{f['insight']}` -- {f['context']}"
            for f in report.verify.flagged[:25]
        ]
        if len(report.verify.flagged) > 25:
            lines.append(f"- ... and {len(report.verify.flagged) - 25} more")
    return lines


def _freshness_section(report: AuditReport) -> list[str]:
    f = report.freshness
    lines = ["## Synthesis freshness (stale prose reads as confidently as fresh prose)", ""]
    if not f.checked:
        return [*lines, "- No topic-level synthesis artifacts yet (see coverage gaps)."]
    if not f.stale and not f.shadowed_legacy:
        return [*lines, f"- All {f.checked} synthesis artifact(s) current with their sources."]
    for item in f.stale:
        lines.append(
            f"- `{item['synthesis']}` predates {item['behind']} newer source(s) "
            f"by {item['gap_days']}d -- regenerate with `distill corpus {report.topic}` "
            "(paper syntheses also regenerate on the topic's next `distill papers` run)."
        )
    if f.shadowed_legacy:
        lines += ["", "### Shadowed legacy syntheses (superseded file still on disk)", ""]
        lines += [
            f"- `{item['legacy']}` is superseded by `{item['active']}` -- "
            "delete the legacy file so readers cannot pick up the stale copy."
            for item in f.shadowed_legacy
        ]
    return lines


def _duplicates_section(report: AuditReport) -> list[str]:
    lines = ["## Near-duplicate insights (artifact-preserving -- surfaced, never merged)", ""]
    if not report.near_duplicates:
        return [*lines, "- No substantial body overlap between insights."]
    lines.append(
        "- Overlapping insights triple-weight one event in synthesis; three outlets "
        "repeating one press release is itself a signal. Groups by shared phrasing:"
    )
    lines.append("")
    for group in report.near_duplicates[:10]:
        lines.append(f"- {group.similarity:.0%} overlap across {group.members} insight(s):")
        lines += [f"  - `{p}`" for p in group.paths[:6]]
    if len(report.near_duplicates) > 10:
        lines.append(f"- ... and {len(report.near_duplicates) - 10} more groups")
    return lines


def _health_section(report: AuditReport) -> list[str]:
    lines = ["## Corpus health", ""]
    if report.health_warnings:
        lines += [f"- {w}" for w in report.health_warnings]
    else:
        lines.append("- No stale-synthesis or thin-artifact warnings.")
    return lines


def _contested_section(report: AuditReport) -> list[str]:
    lines = ["## Contested concepts (incompatible evidence -- strategic signal, not noise)", ""]
    if not report.contested:
        return [*lines, "- None recorded."]
    lines += [
        f"- **{c['name']}** ({c['kind']}): {c['helpful']} helpful / {c['harmful']} harmful "
        f"across {c['sources']} source(s)"
        for c in report.contested[:15]
    ]
    if len(report.contested) > 15:
        lines.append(f"- ... and {len(report.contested) - 15} more")
    return lines


def _links_section(report: AuditReport) -> list[str]:
    lines = ["## Link integrity", ""]
    if not report.broken_links:
        return [*lines, "- All wiki-links resolve."]
    lines += [
        f"- `{bl.target_slug}` unresolved in `{bl.source_file.name}`:{bl.line_number}"
        for bl in report.broken_links[:20]
    ]
    if len(report.broken_links) > 20:
        lines.append(f"- ... and {len(report.broken_links) - 20} more")
    lines.append("- Fix with `distill doctor --links --fix`.")
    return lines


def _gaps_section(report: AuditReport) -> list[str]:
    lines = ["## Coverage gaps", ""]
    if not report.gaps:
        return [*lines, "- No coverage gaps detected."]
    lines += [f"- {g}" for g in report.gaps]
    if report.next_actions:
        lines += ["", "### Suggested next actions", ""]
        lines += [f"- {a}" for a in report.next_actions]
        lines.append(
            f"- Gap-driven discovery: `distill discover --from-gaps --topic {report.topic} --preview`"
        )
    return lines


def render_audit_md(report: AuditReport, *, now_iso: str) -> str:
    """Render one topic's audit as markdown. Pure."""
    lines: list[str] = [
        f"# Audit: {report.topic}",
        "",
        f"Generated {now_iso} by `distill audit` (deterministic; no model calls). "
        f"{report.issue_count} finding(s).",
        "",
    ]
    for section in (
        _verify_section,
        _staleness_section,
        _freshness_section,
        _duplicates_section,
        _health_section,
        _contested_section,
        _links_section,
        _gaps_section,
    ):
        lines += section(report)
        lines.append("")
    return "\n".join(lines)


@dataclass(frozen=True)
class LibraryHygiene:
    """Library-wide topic-directory status, for the end of ``audit all``.

    The dev-library review (2026-06-12) found 11 of 53 topics were unlabeled
    test leftovers, one a broken reparse point, and several real corpora
    invisible to agents -- all indistinguishable from production topics in
    every existing view. Categories here are objective filesystem facts,
    except ``test_named`` which is an explicitly-labelled naming heuristic.
    """

    healthy: int = 0
    empty: list[str] = field(default_factory=list)  # no sources, no synthesis
    unreadable: list[str] = field(default_factory=list)  # broken links/reparse points
    unindexed: list[str] = field(default_factory=list)  # has sources, no CLAUDE.md
    test_named: list[str] = field(default_factory=list)  # name suggests test/scratch

    @property
    def issue_count(self) -> int:
        # test_named is informational, not a finding -- a deliberately named
        # validation topic is not wrong, just worth listing for cleanup.
        return len(self.empty) + len(self.unreadable) + len(self.unindexed)


_TEST_NAME_RE = re.compile(r"(^|-)(test|tests|validate|validation|scratch|tmp|wwt)(-|\d|$)")


def collect_library_hygiene(library_dir: Path) -> LibraryHygiene:
    """Classify every topic directory by objective filesystem status."""
    from distill.library.claude_md import count_topic_sources
    from distill.library.freshness import collect_synthesis_freshness

    topics_dir = library_dir / "topics"
    if not topics_dir.is_dir():
        return LibraryHygiene()
    healthy = 0
    empty: list[str] = []
    unreadable: list[str] = []
    unindexed: list[str] = []
    test_named: list[str] = []
    for child in sorted(topics_dir.iterdir(), key=lambda p: p.name.lower()):
        name = child.name
        if name.startswith("."):
            continue
        try:
            if not child.is_dir():
                continue
            sources = count_topic_sources(child)["total"]
            has_synth = collect_synthesis_freshness(child, name).checked > 0
        except OSError:
            unreadable.append(name)
            continue
        if _TEST_NAME_RE.search(name.lower()):
            test_named.append(name)
        if sources == 0 and not has_synth:
            empty.append(name)
        elif sources > 0 and not (child / "CLAUDE.md").exists():
            unindexed.append(name)
        else:
            healthy += 1
    return LibraryHygiene(
        healthy=healthy,
        empty=empty,
        unreadable=unreadable,
        unindexed=unindexed,
        test_named=test_named,
    )


def render_library_audit_md(hygiene: LibraryHygiene, *, now_iso: str) -> str:
    """Render the library-wide hygiene view. Pure."""
    lines = [
        "# Library audit",
        "",
        f"Generated {now_iso} by `distill audit all` (deterministic; no model calls). "
        f"{hygiene.issue_count} hygiene finding(s) across the library.",
        "",
        "## Topic-directory hygiene",
        "",
        f"- Healthy topics: {hygiene.healthy}",
    ]
    if hygiene.empty:
        lines += [
            "",
            "### Empty topic directories (no sources, no synthesis)",
            "",
            "Safe to delete -- nothing distill wrote lives there.",
            "",
        ]
        lines += [f"- `topics/{t}/`" for t in hygiene.empty]
    if hygiene.unreadable:
        lines += [
            "",
            "### Unreadable topic directories (broken links / reparse points)",
            "",
        ]
        lines += [f"- `topics/{t}/`" for t in hygiene.unreadable]
    if hygiene.unindexed:
        lines += [
            "",
            "### Topics with sources but no orientation files",
            "",
            "Invisible to agents that auto-load CLAUDE.md/AGENTS.md. "
            "Regenerate with `distill claude-md --all`.",
            "",
        ]
        lines += [f"- `topics/{t}/`" for t in hygiene.unindexed]
    if hygiene.test_named:
        lines += [
            "",
            "### Names suggesting test/validation topics (informational)",
            "",
            "Not findings -- listed so deliberate experiments are easy to sweep "
            "when they stop earning their place beside production corpora.",
            "",
        ]
        lines += [f"- `topics/{t}/`" for t in hygiene.test_named]
    if hygiene.issue_count == 0 and not hygiene.test_named:
        lines += ["", "- Every topic directory is readable, indexed, and non-empty."]
    lines.append("")
    return "\n".join(lines)


def write_audit_artifact(topic_dir: Path, report: AuditReport, *, now_iso: str) -> Path:
    """Write ``<topic>_Audit.md`` with standard frontmatter. Returns the path."""
    return write_markdown_artifact(
        topic_dir,
        "audit",
        render_audit_md(report, now_iso=now_iso),
        identity=report.topic,
        frontmatter=base_frontmatter(
            artifact_type="audit",
            title=f"Audit: {report.topic}",
            topic=report.topic,
            source="distill",
            tags=tags_for(report.topic, "audit"),
            extra={"findings": report.issue_count, "generated_at": now_iso},
        ),
    )
