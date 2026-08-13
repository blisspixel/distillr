# OKF interop and loop-ready stewardship

Status: implemented; OKF projection upgraded to v0.2 in August 2026.

The exact current standards baseline and future update procedure live in
[`../interoperability.md`](../interoperability.md). This design note explains
the product mapping. The normative OKF specification remains authoritative.

This document records what Distill should take from the June 2026 OKF and loop
engineering wave, and what it should explicitly leave alone.

## Research signals

- Google Cloud introduced the Open Knowledge Format on 2026-06-12 as a
  vendor-neutral way to exchange agent-readable knowledge bundles: Markdown
  files with YAML frontmatter, conventional `index.md` / `log.md`, and Markdown
  links. The launch article describes v0.1. The current v0.2 specification adds
  first-class provenance, trust, lifecycle, freshness, and attested computation
  fields. Sources: [Google Cloud launch article](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)
  and [current OKF v0.2 spec](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md).
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
  verifiers. Sources: [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive),
  [Claude Code programmatic usage](https://code.claude.com/docs/en/headless),
  [Grok Build overview](https://docs.x.ai/build/overview), and
  [GitHub scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
  This doc covers the loop contract; the recurring-profile and no-metered-cost
  routing details live in
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
- **Receipts survive export.** OKF concept docs preserve source URLs and native
  artifact paths. Exact sibling source receipts and verify sidecars are copied
  into the bundle through bounded, no-follow reads and linked from standard
  `sources` or Distill verification metadata.
- **Trust projection fails closed.** Sidecar existence alone never produces
  OKF `verified`. The sidecar must match a supported schema, contain usable clean
  coverage, bind to the exact artifact digest, and carry a valid verification
  time. Other sidecars remain inspectable receipts with `invalid`, `incomplete`,
  `flagged`, or `unbound` status.
- **Permissive where OKF is permissive.** Missing optional fields and broken
  links warn, not fail. Missing parseable frontmatter or missing `type` fails.
- **Loop runner stays external.** Distill emits state and safe commands. Codex,
  Claude Code, cron, GitHub Actions, or a human operator owns scheduling and
  execution.
- **Verification is the stop condition.** A loop is done when the command exits
  cleanly and audit/verify state changes as expected.
- **Loop admission is explicit.** A repeated loop is allowed only for recurring
  work with an automated verifier, bounded budget, usable tools, and persisted
  state. Otherwise Distill should emit a one-shot command or operator note.
- **No fake semantic gates.** The no-brittle-junk charter still applies. Python
  may validate structure and aggregate model verdicts, but it must not decide
  whether a source is good, faithful, or substantively complete by keyword or
  length proxy.

## External runner contract

The shipped loop handoff is a contract boundary, not a scheduler. Distill owns
the state it can prove from the corpus and emits the next safe unit of work. An
external runner owns timing, policy, tool choice, and whether an action should
run at all.

Distill is responsible for:

- Emitting one parseable `next-actions.v1` JSON object.
- Keeping action ids deterministic so runners can de-duplicate across attempts.
- Returning exact argv arrays rather than shell strings.
- Classifying approval as `none`, `operator`, or `spend`.
- Estimating cost as `0.0` only for routes known to avoid metered API spend, or
  `null` when the route is unknown or model-dependent.
- Naming expected write scopes as library-relative paths or glob-like summaries.
- Providing a verifier command and expectation that define the stop condition.
- Suggesting a small loop state path and max-attempt count for external logs.

The external runner is responsible for:

- Choosing the trigger: manual run, cron, Task Scheduler, GitHub Actions,
  Codex, Claude Code, Grok Build, or another harness.
- Reading `schema_version` and refusing unknown schemas unless the runner has an
  explicit compatibility shim.
- Applying user policy: approval gates, no-metered-cost mode, provider routing,
  spend caps, wall-clock limits, and branch or worktree isolation.
- Executing `command` as an argv array without shell interpolation.
- Recording attempt state, selected route, stdout/stderr or structured events,
  verifier results, accepted artifact paths, cost or quota usage, and blocked
  reasons at the suggested `loop.state_path` or a runner-owned equivalent.
- Running the verifier after each attempt and accepting work only when the
  expectation is satisfied.
- Escalating instead of retrying when max attempts, spend, permissions, missing
  credentials, or ambiguous cost policy blocks the action.

Current runner surfaces make this contract practical without Distill embedding a
runner. Codex supports `codex exec` for scripts and CI with explicit sandbox and
approval settings plus JSONL output. Claude Code supports `claude -p` for
non-interactive runs, `--bare` for controlled scripts, tool allowlists, and
structured output. Grok Build supports headless `grok -p` usage for scripts and
automations. GitHub Actions and cron can provide the recurring trigger, with the
same rule: they run Distill commands and verifiers, they do not ask Distill to
be the scheduler.

Adapter guidance for those runners belongs in examples and profile docs. The
core contract should stay tool-neutral: JSON in, argv out, verifier decides.

## OKF mapping

| Distill artifact | OKF `type` | Notes |
|---|---|---|
| `_Insights.md` | `Source Insight` | Include source URL, `sources`, native artifact path, generation metadata, copied verification receipt, and digest-bound `verified` when clean. |
| topic / corpus / paper / site synthesis | `Synthesis` | Preserve rewritten source links and apply the same verification projection rules. |
| `answers/*_Insights.md` | `Derived Answer` | Preserve cited source paths and project the strict verify receipt without overstating trust. |
| `concepts/*.md` | `Concept Playbook` | Preserve native evidence fields and backlinks. |
| `entities/*.md` | `Entity Playbook` | Same evidence model as concepts. |
| audit artifact | `Audit Report` | Export as a concept so consumers can inspect trust state. |
| source receipts | `Source Receipt` or supplemental file | Markdown receipts are normal concepts. Exact non-Markdown sibling receipts named by sidecars are copied as supplemental files. |

The root export should include:

- `index.md` with `okf_version: "0.2"` frontmatter and progressive-disclosure
  sections by topic and artifact type, including descriptions.
- `log.md` with ISO date-grouped run history and export metadata, newest date
  first and without legacy frontmatter.
- Standard Markdown links, preferably absolute bundle-relative links.
- `sources` frontmatter for source material and stable bundle-relative receipt
  resources. Existing body citations remain intact; v0.2 no longer generates a
  legacy `# Citations` list.
- `generated: {by, at}` for the export projection. Native model and generation
  details remain available as producer extension fields.
- Absolute `stale_after` only when the native artifact already provides a valid
  absolute date. Relative profile durations are not guessed across artifacts.

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
      },
      "loop": {
        "state_path": ".distill/loops/memory.stale-synthesis.corpus.json",
        "max_attempts": 3,
        "acceptance_metric": "cost_per_accepted_change"
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
  `allowed_provider_routes`, `loop`.

Loop metadata is intentionally small:

- `state_path`: stable file where an external runner records attempts, route,
  cost, verifier result, accepted artifact paths, and blocked reasons.
- `max_attempts`: deterministic stop before a loop burns budget indefinitely.
- `acceptance_metric`: usually `cost_per_accepted_change`; Distill may compute
  it from the ledger and verifier outcomes instead of trusting a runner summary.

## Build order

1. **Roadmap and docs sync.** The current docs must accurately describe shipped
   source breadth, shipped concept playbooks, and the post-0.16 order of
   operations.
2. **OKF validator core.** Pure library code with fixtures: frontmatter parse,
   required `type`, reserved file structure, link collection, permissive warnings.
3. **OKF export mapper.** Read native artifacts, map to OKF concept docs, write
   `index.md` / `log.md`, and validate the generated bundle.
4. **Next-action planner.** Convert existing audit/gap/staleness/failure/cost
   objects into stable JSON action rows with verifier commands, loop admission
   fields, and state-path hints.
5. **CLI/MCP exposure.** Add CLI first, then expose a read-only MCP equivalent
   if the schema proves useful.
6. **Docs and fixtures.** Usage examples for human operators and external loops;
   fixture tests for OKF, next-action JSON, and loop admission failure cases.

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
- External loops can decide whether to continue, stop, or escalate by reading
  Distill state, not by parsing a model's completion claim.
- The native corpus layout, existing MCP read surface, and existing Obsidian
  workflow continue to work unchanged.
