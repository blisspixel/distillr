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
from dataclasses import dataclass, field
from pathlib import Path

from distill.library.insights import discover_insights
from distill.library.links import BrokenLink
from distill.library.paths import base_frontmatter, tags_for, write_markdown_artifact

__all__ = [
    "AuditReport",
    "VerifyRollup",
    "collect_verify_rollup",
    "render_audit_md",
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
class AuditReport:
    """Everything one audit run found for one topic."""

    topic: str
    health_warnings: list[str]
    contested: list[dict]  # {name, kind, helpful, harmful, sources}
    broken_links: list[BrokenLink]
    gaps: list[str]
    next_actions: list[str]
    verify: VerifyRollup

    @property
    def issue_count(self) -> int:
        return (
            len(self.health_warnings)
            + len(self.contested)
            + len(self.broken_links)
            + len(self.gaps)
            + len(self.verify.flagged)
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
        _health_section,
        _contested_section,
        _links_section,
        _gaps_section,
    ):
        lines += section(report)
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
