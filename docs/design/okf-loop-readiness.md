# OKF interop and loop-ready stewardship

Status: accepted direction for the next build slice after 0.16.1.

This document records what Distill should take from the June 2026 OKF and loop
engineering wave, and what it should explicitly leave alone.

## Research signals

- Google Cloud introduced the Open Knowledge Format on 2026-06-12 as a
  vendor-neutral way to exchange agent-readable knowledge bundles: Markdown files
  with YAML frontmatter, conventional `index.md` / `log.md`, Markdown links, and
  citations. Source: [Google Cloud blog](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)
  and [OKF v0.1 spec](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md).
- Anthropic's context-engineering guidance frames agents as LLMs using tools in a
  loop, with context treated as a finite resource. The useful design pressure for
  Distill is progressive disclosure, paths-not-payloads, compact state, and
  explicit stop conditions. Source: [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
- Anthropic's tool guidance recommends programmatic agentic loops with verifiable
  outcomes, tool-call metrics, runtime metrics, token tracking, and careful tool
  descriptions. Source: [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents).
- The current coding-agent CLI wave makes external loop runners realistic:
  Codex CLI, Claude Code, Grok Build, cron, and GitHub Actions can all run
  bounded commands if Distill emits exact argv arrays, approval classes, and
  verifiers. This doc covers the loop contract; the recurring-profile and
  no-metered-cost routing details live in
  [`recurring-profiles-cost-routing.md`](recurring-profiles-cost-routing.md).
- The current loop-engineering discussion in coding-agent communities maps onto
  primitives Distill already has: durable filesystem state, audit reports,
  verify sidecars, no-TTY-safe commands, read-only MCP, spend caps, and
  convergent reruns.

## Product stance

Distill is not becoming a generic OKF editor, graph viewer, hosted wiki, or
scheduler. Distill remains the verified research-corpus producer.

The two useful additions are:

1. **OKF projection.** Export and validate a standards-shaped bundle so other
   agents and catalog systems can consume a Distill corpus without learning the
   native layout first.
2. **Loop-readable stewardship.** Emit a bounded next-action plan from audit,
   gap, staleness, cost, and failure state so external loops can decide what to
   run and know how to verify completion.

## Principles

- **Native corpus stays authoritative.** OKF export is a read-only projection
  from `library/`, not a migration or replacement.
- **Receipts survive export.** OKF concept docs must preserve source URLs,
  source artifact paths, verify sidecar paths, prompt/model provenance, and
  citations.
- **Permissive where OKF is permissive.** Missing optional fields and broken
  links warn, not fail. Missing parseable frontmatter or missing `type` fails.
- **Loop runner stays external.** Distill emits state and safe commands. Codex,
  Claude Code, cron, GitHub Actions, or a human operator owns scheduling and
  execution.
- **Verification is the stop condition.** A loop is done when the command exits
  cleanly and audit/verify state changes as expected.
- **No fake semantic gates.** The no-brittle-junk charter still applies. Python
  may validate structure and aggregate model verdicts, but it must not decide
  whether a source is good, faithful, or substantively complete by keyword or
  length proxy.

## OKF mapping

| Distill artifact | OKF `type` | Notes |
|---|---|---|
| `_Insights.md` | `Source Insight` | Include source URL, source artifact path, verify sidecar path, prompt/model fields, and citations. |
| topic / corpus / paper / site synthesis | `Synthesis` | Include synthesized source paths and synthesis verify sidecar. |
| `answers/*_Insights.md` | `Derived Answer` | Include cited source paths and strict verify result. |
| `concepts/*.md` | `Concept Playbook` | Preserve native evidence fields and backlinks. |
| `entities/*.md` | `Entity Playbook` | Same evidence model as concepts. |
| audit artifact | `Audit Report` | Export as a concept so consumers can inspect trust state. |
| source receipts | `Source Receipt` | Optional in the first slice; useful when an exported bundle should be self-contained. |

The root export should include:

- `index.md` with `okf_version: "0.1"` frontmatter and progressive-disclosure
  sections by topic and artifact type.
- `log.md` synthesized from run history, audit events, and export metadata.
- Standard Markdown links, preferably absolute bundle-relative links.
- `# Citations` sections on concept docs that make external claims.

## Loop next-action schema

`distill audit <topic|all> --next-actions --json` should return one JSON object
with a stable schema:

```json
{
  "schema_version": "next-actions.v1",
  "topic": "memory",
  "generated_at": "2026-06-18T00:00:00Z",
  "actions": [
    {
      "id": "memory.stale-synthesis.corpus",
      "kind": "refresh_synthesis",
      "severity": "warning",
      "rationale": "Corpus synthesis is older than its sources.",
      "command": ["distill", "corpus", "memory", "--verify", "strict"],
      "approval": "operator",
      "estimated_cost_usd": 0.34,
      "writes": ["topics/memory/*_Corpus_Synthesis.md"],
      "verifier": {
        "command": ["distill", "audit", "memory", "--report-only", "--json"],
        "expect": "freshness.stale == 0"
      }
    }
  ]
}
```

Required action fields:

- `id`: stable, deterministic id for de-duplication across loop runs.
- `kind`: controlled string such as `reanalyze_source`, `refresh_synthesis`,
  `fix_links`, `gap_discovery_preview`, `regenerate_orientation`, or
  `retry_failed_source`.
- `rationale`: human-readable reason grounded in an audit/gap/cost finding.
- `command`: argv array, never a shell string.
- `approval`: `none`, `operator`, or `spend`.
- `estimated_cost_usd`: nullable; omitted only when unknown. In no-metered-cost
  mode this should be `0` only when the route is known to avoid metered API
  spend; otherwise the action is blocked or downgraded to preview.
- `writes`: expected library-relative artifact paths or glob-like summaries.
- `verifier`: command plus machine-checkable expectation.

Optional fields:

- `source_paths`, `verify_sidecars`, `ingest_domains`, `blocked_by`,
  `requires_env`, `preview_id`, `from_preview_command`, `cost_mode`,
  `allowed_provider_routes`.

## Build order

1. **Roadmap and docs sync.** The current docs must accurately describe shipped
   source breadth, shipped concept playbooks, and the post-0.16 order of
   operations.
2. **OKF validator core.** Pure library code with fixtures: frontmatter parse,
   required `type`, reserved file structure, link collection, permissive warnings.
3. **OKF export mapper.** Read native artifacts, map to OKF concept docs, write
   `index.md` / `log.md`, and validate the generated bundle.
4. **Next-action planner.** Convert existing audit/gap/staleness/failure/cost
   objects into stable JSON action rows.
5. **CLI/MCP exposure.** Add CLI first, then expose a read-only MCP equivalent
   if the schema proves useful.
6. **Docs and fixtures.** Usage examples for human operators and external loops;
   fixture tests for both OKF and next-action JSON.

## Non-goals

- No scheduler, background worker, or PR bot inside Distill.
- No generic OKF editing UI.
- No graph viewer beyond optional use of external OKF visualizers.
- No OKF import/merge in the first slice. Import is a separate trust problem
  because external bundles may not carry Distill receipts or verify sidecars.
- No mandatory `llms.txt`. It can point to an exported OKF bundle, but it is not
  the control plane.

## Success criteria

- A Distill topic can be exported into an OKF bundle that passes Distill's OKF
  validator and preserves provenance links back to native artifacts.
- `distill audit --next-actions --json` is stable enough for an external loop to
  de-duplicate actions, run one command, and verify completion without reading
  console prose.
- The native corpus layout, existing MCP read surface, and existing Obsidian
  workflow continue to work unchanged.
