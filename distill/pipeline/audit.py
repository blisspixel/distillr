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
from distill.library.paths import (
    artifact_path,
    base_frontmatter,
    find_artifact,
    tags_for,
    write_markdown_artifact,
)
from distill.pipeline.audit_video_duplicates import (
    ExactVideoDuplicateGroup,
    VideoOccurrence,
    collect_exact_video_duplicates,
    render_exact_video_duplicates_section,
)
from distill.pipeline.next_actions import (
    LoopMetadata,
    NextAction,
    NextActionPlan,
    NextActionVerifier,
    action_id,
    loop_metadata,
)
from distill.pipeline.profile_health import (
    ProfileHealth,
    collect_profile_health,
    render_profile_health_section,
)
from distill.prompts.registry import PROMPT_IDS, parse_prompt_id

_action_id = action_id
_loop = loop_metadata

__all__ = [
    "AuditReport",
    "ExactVideoDuplicateGroup",
    "LibraryHygiene",
    "LoopMetadata",
    "NextAction",
    "NextActionPlan",
    "NextActionVerifier",
    "ProfileHealth",
    "StalenessRollup",
    "SynthesisFreshness",
    "VerifyRollup",
    "VideoOccurrence",
    "build_next_action_plan",
    "collect_exact_video_duplicates",
    "collect_library_hygiene",
    "collect_profile_health",
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
    """Verification coverage for a topic's insights, from ``_Verify.json`` sidecars.

    Synthesis artifacts are counted separately (0.13.1): they are verified
    against their own inputs rather than a source receipt, and a synthesis
    predating the synthesis-verify gate is expected, not alarming. Their
    flags land in the shared ``flagged`` list so the audit treats a flagged
    synthesis claim as a finding like any other.
    """

    insights_total: int
    checked: int
    clean: int
    flagged: list[dict] = field(default_factory=list)  # {insight, token, kind, context}
    synthesis_total: int = 0
    synthesis_checked: int = 0
    synthesis_clean: int = 0

    @property
    def never_checked(self) -> int:
        return self.insights_total - self.checked

    @property
    def synthesis_never_checked(self) -> int:
        return self.synthesis_total - self.synthesis_checked


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
    exact_video_duplicates: list = field(default_factory=list)  # list[ExactVideoDuplicateGroup]
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
            + len(self.exact_video_duplicates)
            + len(self.freshness.stale)
            + len(self.freshness.shadowed_legacy)
        )


def _audit_json_command(topic: str) -> list[str]:
    return ["distill", "audit", topic, "--next-actions", "--json"]


def _has_no_major_gap(report: AuditReport) -> bool:
    return all("No major research gaps" in gap for gap in report.gaps)


def _topic_orientation_missing(topic_dir: Path) -> bool:
    return not (topic_dir / "CLAUDE.md").exists() or not (topic_dir / "AGENTS.md").exists()


def _append_action(actions: list[NextAction], action: NextAction) -> None:
    if not any(existing.id == action.id for existing in actions):
        actions.append(action)


def _reanalysis_argvs(library_dir: Path, topic: str, stale: list[dict]) -> list[list[str]]:
    """Concrete re-analysis argv arrays for stale artifacts."""
    commands: list[list[str]] = []
    for item in stale:
        rel = str(item.get("insight", ""))
        try:
            text = (library_dir / rel).read_text(encoding="utf-8")
        except OSError:
            text = ""
        url = frontmatter_field(text, "url")
        source = frontmatter_field(text, "source")
        if source == "arxiv" and url:
            arxiv_id = url.rstrip("/").rsplit("/", 1)[-1]
            commands.append(["distill", "papers", arxiv_id, "--topic", topic, "--limit", "1"])
        elif url and (
            any(h in url for h in _INGESTABLE_HOSTS) or url.lower().endswith((".rss", ".xml"))
        ):
            commands.append(["distill", "ingest", url, "--topic", topic])
    return commands


def _actions_for_report(library_dir: Path, report: AuditReport) -> list[NextAction]:
    """Build rule-owned next actions from one deterministic audit report."""
    actions: list[NextAction] = []
    topic = report.topic
    topic_dir = library_dir / "topics" / topic

    if report.broken_links:
        action_id = _action_id(topic, "fix-links")
        _append_action(
            actions,
            NextAction(
                id=action_id,
                kind="fix_links",
                severity="warning",
                rationale=f"{len(report.broken_links)} wiki-link(s) are unresolved.",
                command=["distill", "doctor", "--links", "--fix"],
                approval="operator",
                estimated_cost_usd=0.0,
                writes=[f"topics/{topic}/**/*.md"],
                verifier=NextActionVerifier(
                    command=_audit_json_command(topic),
                    expect=f"no action with id '{action_id}'",
                ),
                loop=_loop(action_id),
            ),
        )

    if topic_dir.exists() and _topic_orientation_missing(topic_dir):
        action_id = _action_id(topic, "regenerate-orientation")
        _append_action(
            actions,
            NextAction(
                id=action_id,
                kind="regenerate_orientation",
                severity="warning",
                rationale="Topic orientation files are missing or incomplete.",
                command=["distill", "claude-md", topic],
                approval="none",
                estimated_cost_usd=0.0,
                writes=[f"topics/{topic}/CLAUDE.md", f"topics/{topic}/AGENTS.md"],
                verifier=NextActionVerifier(
                    command=_audit_json_command(topic),
                    expect=f"no action with id '{action_id}'",
                ),
                loop=_loop(action_id),
            ),
        )

    stale_commands = _reanalysis_argvs(library_dir, topic, report.staleness.stale)
    if stale_commands:
        action_id = _action_id(topic, "reanalyze-stale")
        _append_action(
            actions,
            NextAction(
                id=action_id,
                kind="reanalyze_stale",
                severity="warning",
                rationale=f"{len(report.staleness.stale)} artifact(s) use stale prompt versions.",
                command=stale_commands[0],
                approval="spend",
                estimated_cost_usd=None,
                writes=[f"topics/{topic}/**/*_Insights.md", f"topics/{topic}/**/*_Verify.json"],
                verifier=NextActionVerifier(
                    command=_audit_json_command(topic),
                    expect="staleness.stale decreases or reaches 0",
                ),
                loop=_loop(action_id, max_attempts=3),
            ),
        )

    if report.freshness.stale:
        action_id = _action_id(topic, "refresh-synthesis")
        _append_action(
            actions,
            NextAction(
                id=action_id,
                kind="refresh_synthesis",
                severity="warning",
                rationale=f"{len(report.freshness.stale)} synthesis artifact(s) predate sources.",
                command=["distill", "corpus", topic],
                approval="spend",
                estimated_cost_usd=None,
                writes=[f"topics/{topic}/*_Corpus_Synthesis.md"],
                verifier=NextActionVerifier(
                    command=_audit_json_command(topic),
                    expect="freshness.stale == 0",
                ),
                loop=_loop(action_id, max_attempts=3),
            ),
        )

    missing = set(report.gaps)
    if not _has_no_major_gap(report):
        action_id = _action_id(topic, "gap-discovery-preview")
        _append_action(
            actions,
            NextAction(
                id=action_id,
                kind="gap_discovery_preview",
                severity="info",
                rationale="Coverage gaps exist; preview candidate sources before ingest.",
                command=["distill", "discover", "--from-gaps", "--topic", topic, "--preview"],
                approval="spend",
                estimated_cost_usd=None,
                writes=[".distill/previews/*.json"],
                verifier=NextActionVerifier(
                    command=_audit_json_command(topic),
                    expect="preview exits 0 and records a preview id",
                ),
                loop=_loop(action_id, max_attempts=1),
            ),
        )

    if "Mixed-source corpus synthesis is missing for a multi-source topic." in missing:
        action_id = _action_id(topic, "build-corpus-synthesis")
        _append_action(
            actions,
            NextAction(
                id=action_id,
                kind="build_corpus_synthesis",
                severity="warning",
                rationale="A multi-source topic is missing its mixed-source corpus synthesis.",
                command=["distill", "corpus", topic],
                approval="spend",
                estimated_cost_usd=None,
                writes=[f"topics/{topic}/*_Corpus_Synthesis.md"],
                verifier=NextActionVerifier(
                    command=_audit_json_command(topic),
                    expect=f"no action with id '{action_id}'",
                ),
                loop=_loop(action_id, max_attempts=3),
            ),
        )

    if "No topic diff is available yet." in missing:
        action_id = _action_id(topic, "write-diff")
        _append_action(
            actions,
            NextAction(
                id=action_id,
                kind="write_diff",
                severity="info",
                rationale="No topic diff baseline exists yet.",
                command=["distill", "diff", topic],
                approval="none",
                estimated_cost_usd=0.0,
                writes=[f"topics/{topic}/*_Topic_Diff.md"],
                verifier=NextActionVerifier(
                    command=_audit_json_command(topic),
                    expect=f"no action with id '{action_id}'",
                ),
                loop=_loop(action_id),
            ),
        )

    if "No topic trend summary is available yet." in missing:
        action_id = _action_id(topic, "write-trends")
        _append_action(
            actions,
            NextAction(
                id=action_id,
                kind="write_trends",
                severity="info",
                rationale="No topic trend summary exists yet.",
                command=["distill", "trends", topic],
                approval="none",
                estimated_cost_usd=0.0,
                writes=[f"topics/{topic}/*_Topic_Trends.md"],
                verifier=NextActionVerifier(
                    command=_audit_json_command(topic),
                    expect=f"no action with id '{action_id}'",
                ),
                loop=_loop(action_id),
            ),
        )

    return actions


def build_next_action_plan(
    library_dir: Path,
    reports: list[AuditReport],
    *,
    topic: str,
    generated_at: str,
) -> NextActionPlan:
    """Convert deterministic audit reports into a loop-readable action plan."""
    actions: list[NextAction] = []
    for report in reports:
        actions.extend(_actions_for_report(library_dir, report))
    severity_rank = {"warning": 0, "info": 1}
    actions.sort(key=lambda a: (severity_rank.get(a.severity, 9), a.id))
    return NextActionPlan(
        schema_version="next-actions.v1",
        topic=topic,
        generated_at=generated_at,
        actions=actions,
    )


def _sidecar_flags(data: dict, artifact_path: str) -> list[dict]:
    """All flagged claims in one sidecar: numeric tier + the additive
    entailment block (schema v2; a missing block means the tier wasn't run,
    so v1 sidecars stay valid)."""
    flags: list[dict] = []
    unsupported = data.get("unsupported")
    if isinstance(unsupported, list):
        flags += [
            {
                "insight": artifact_path,
                "token": str(item.get("token", "")),
                "kind": str(item.get("kind", "")),
                "context": str(item.get("context", ""))[:200],
            }
            for item in unsupported
            if isinstance(item, dict)
        ]
    ent = data.get("entailment")
    ent_flagged = ent.get("flagged") if isinstance(ent, dict) else None
    if isinstance(ent_flagged, list):
        flags += [
            {
                "insight": artifact_path,
                "token": str(item.get("claim", ""))[:80],
                "kind": "entailment",
                "context": str(item.get("best_chunk_preview", ""))[:200],
            }
            for item in ent_flagged
            if isinstance(item, dict)
        ]
    return flags


def _synthesis_artifacts(topic_dir: Path) -> list[tuple[Path, str, str]]:
    """Every synthesis artifact a topic can carry, with its verify-sidecar
    identity: ``(artifact_path, sidecar_dir-relative artifact label, identity)``.

    Identities mirror exactly what the synthesis writers stamp (paper:
    ``<topic>-paper-synthesis`` etc.; channel/site syntheses reuse their
    artifact identity), so the audit reads the same sidecar the emit wrote.
    """
    topic = topic_dir.name
    found: list[tuple[Path, str, str]] = []
    topic_level = [
        ("paper_synthesis", f"{topic}-paper-synthesis"),
        ("corpus_synthesis", f"{topic}-corpus-synthesis"),
        ("topic_synthesis", f"{topic}-topic-synthesis"),
    ]
    for artifact_type, sidecar_identity in topic_level:
        path = find_artifact(topic_dir, artifact_type, identity=topic)
        if path.exists():
            found.append((topic_dir, path.name, sidecar_identity))
    for parent, artifact_type in (("channels", "synthesis"), ("sites", "site_synthesis")):
        parent_dir = topic_dir / parent
        if not parent_dir.exists():
            continue
        for sub_dir in sorted(parent_dir.iterdir()):
            if not sub_dir.is_dir():
                continue
            identity = f"{topic}_{sub_dir.name}"
            path = find_artifact(sub_dir, artifact_type, identity=identity)
            if path.exists():
                found.append((sub_dir, f"{parent}/{sub_dir.name}/{path.name}", identity))
    return found


def _read_sidecar(sidecar: Path, label: str) -> tuple[bool, list[dict]] | None:
    """Read one ``_Verify.json`` sidecar. Returns ``(is_clean, flags)`` or
    ``None`` when the file is absent/unreadable/not an object -- the caller
    counts ``None`` as never-checked (parse-don't-crash over local state)."""
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    flags = _sidecar_flags(data, label)
    return (not flags, flags)


def collect_verify_rollup(topic_dir: Path) -> VerifyRollup:
    """Roll up ``_Verify.json`` sidecars across a topic's insight directories.

    One sidecar per source directory (written beside the insight). Sidecars
    that fail to parse count as never-checked rather than crashing the audit
    (parse-don't-crash over corruptible local state). Synthesis artifacts are
    swept too (their sidecars are keyed by the writer's identity), counted
    separately from insights.
    """
    insights = discover_insights(topic_dir)
    checked = 0
    clean = 0
    flagged: list[dict] = []
    for ref in insights:
        sidecars = sorted(ref.path.parent.glob("*_Verify.json"))
        result = _read_sidecar(sidecars[0], ref.artifact_path) if sidecars else None
        if result is None:
            continue
        checked += 1
        is_clean, flags = result
        flagged += flags
        clean += int(is_clean)

    synthesis_total = 0
    synthesis_checked = 0
    synthesis_clean = 0
    for sidecar_dir, label, identity in _synthesis_artifacts(topic_dir):
        synthesis_total += 1
        sidecar = artifact_path(sidecar_dir, "verify", identity=identity, extension="json")
        result = _read_sidecar(sidecar, label)
        if result is None:
            continue
        synthesis_checked += 1
        is_clean, flags = result
        flagged += flags
        synthesis_clean += int(is_clean)

    return VerifyRollup(
        insights_total=len(insights),
        checked=checked,
        clean=clean,
        flagged=flagged,
        synthesis_total=synthesis_total,
        synthesis_checked=synthesis_checked,
        synthesis_clean=synthesis_clean,
    )


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
    if report.verify.synthesis_total:
        lines.append(
            f"- Syntheses: {report.verify.synthesis_total} | verified clean: "
            f"{report.verify.synthesis_clean} | never checked: "
            f"{report.verify.synthesis_never_checked} (syntheses are verified against "
            "their own inputs at write time; pre-0.13 syntheses re-check on regeneration)"
        )
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


def _exact_video_duplicates_section(report: AuditReport) -> list[str]:
    return render_exact_video_duplicates_section(report.exact_video_duplicates)


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
        _exact_video_duplicates_section,
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
    profiles: ProfileHealth = field(default_factory=ProfileHealth)

    @property
    def issue_count(self) -> int:
        # test_named is informational, not a finding -- a deliberately named
        # validation topic is not wrong, just worth listing for cleanup.
        return (
            len(self.empty) + len(self.unreadable) + len(self.unindexed) + self.profiles.issue_count
        )


_TEST_NAME_RE = re.compile(r"(^|-)(test|tests|validate|validation|scratch|tmp|wwt)(-|\d|$)")


def collect_library_hygiene(library_dir: Path) -> LibraryHygiene:
    """Classify every topic directory by objective filesystem status."""
    from distill.library.claude_md import count_topic_sources
    from distill.library.freshness import collect_synthesis_freshness

    profile_health = collect_profile_health(library_dir)
    topics_dir = library_dir / "topics"
    if not topics_dir.is_dir():
        return LibraryHygiene(profiles=profile_health)
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
        profiles=profile_health,
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
    topic_issue_count = len(hygiene.empty) + len(hygiene.unreadable) + len(hygiene.unindexed)
    if topic_issue_count == 0 and not hygiene.test_named:
        lines += ["", "- Every topic directory is readable, indexed, and non-empty."]
    lines.append("")
    lines += render_profile_health_section(hygiene.profiles)
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
