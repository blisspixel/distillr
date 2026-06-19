# Current State Analysis

Status note from the autonomous roadmap loop on 2026-06-19.

## Read Scope

I read the tracked Markdown inventory through the repository index, headings,
priority markers, and the full source docs that control near-term work:
`README.md`, `ROADMAP.md`, `docs/roadmap.md`, `docs/design/agentic-balance.md`,
`docs/design/model-judgment-vs-brittle-fallbacks.md`,
`docs/design/recurring-profiles-cost-routing.md`,
`docs/design/cli-adapter-runbook.md`, `docs/design/okf-loop-readiness.md`,
`docs/design/version-architecture.md`, `docs/design/how-we-build.md`,
`docs/design/logic-decomposition.md`, and `docs/architecture.md`. I also
inspected the tracked generated example corpus files as outputs, not edit
targets.

## Alignment Summary

The project is aligned around one product promise: Distill is the verified,
plain-Markdown research-corpus layer for humans and agents. It is not a memory
layer, a generic RAG store, a hosted app, a scheduler, or a graph UI. The
README, roadmap, architecture, cost docs, and agentic-balance charter all point
to the same spine:

- Acquire current public sources from eight source types.
- Analyze and synthesize from captured receipts.
- Verify before committing durable corpus artifacts.
- Expose the corpus through files, MCP, `ask`, OKF export, and loop-readable
  next actions.
- Keep orchestration external while making Distill commands safe for unattended
  loops.

## Agentic Balance

The governing rule is clear and internally consistent: model judgment belongs
on semantic questions, while Python owns structure, safety, cost policy,
bookkeeping, thresholds, verifiers, and final accept or refuse decisions.
Specifically:

- Agentic judgment: source fit, novelty, relevance, synthesis planning,
  contradiction interpretation, analysis lensing, and faithfulness verdicts.
- Rule-owned structure: schemas, paths, URLs, cost-mode refusal, action ids,
  exact argv arrays, approval class, dedup bookkeeping, receipts, ledgers, and
  verifier stop conditions.
- Judgment then rule: a model emits per-criterion verdicts, then Python
  aggregates, thresholds, records, and gates.

The main trap to avoid is deterministic quality scoring by keyword, length,
cosine, or other surface proxies. The dual trap is ripping out legitimate
structural checks. Number-in-source checks, parseability, URL safety, path
confinement, and ledger policy are correct rule-owned gates.

## Roadmap State

The shipped center of gravity is strong: write-time verification, audit,
entailment tier, ask/save, OKF export and validation, next-action JSON, profile
schema, profile examples, and profile preview are already present. The current
near-term dependency chain is:

1. Finish 0.19 recurring-profile run and no-metered-cost routing.
2. Finish local route policy and zero-dollar ledger accounting.
3. Add adapter doctor and support-statement checks before any plan-quota route
   can be trusted.
4. Extend cross-route eval before recommending any adapter.
5. Continue `_logic.py` decomposition and 1.0 quality ratchets in parallel.

## Implementation State Found

The live code already had:

- `distill profile preview <name|path>`.
- Profile schema and checked-in examples with `cost_mode: no-metered`.
- Local/provider availability helpers that ask the router rather than checking
  only `XAI_API_KEY`.
- An `AgentProvider`, adapter doctor scaffold, strict manifest parser, and local
  config auth-marker scanning, but without official installed-session auth
  proof, support statement, adapter-specific workload wiring, native usage
  signals, and eval proof needed for no-metered routing.

One documentation inconsistency was fixed before this file was created: roadmap
notes still described an old MCP count of 22 to 21 tools, while the live code,
README, and MCP docs count 24 tools.

## First Implementation Slice

The safest first atomic work is the rule-owned cost-policy foundation. Profile
run and plan-quota adapters are dangerous without it because they can otherwise
turn recurring loops into surprise API spend. Cost policy is structural, so it
does not violate agentic balance. The slice in this branch:

- Parses `DISTILL_COST_MODE=auto|no-metered|paid-ok`.
- Classifies provider routes conservatively.
- Allows local Ollama and LM Studio in `no-metered`.
- Blocks cloud APIs and unproven adapter routes in `no-metered`.
- Keeps plan-quota CLIs blocked until adapter doctor, support statement,
  included-plan auth proof, adapter-specific workload wiring, ledger, and eval
  proof exist.

External spend used so far: `$0.00`.

## Subsequent Implementation Updates

Cycle 2 added the top-level `distill --cost-mode <mode>` override and made
no-metered profile preview commands carry that override explicitly. That keeps
loop runners from depending on ambient `.env` state.

Cycle 3 added `distill profile run <name|path>` as the next structural slice.
The command plans by default and requires `--yes` before execution. When
approved, it executes the generated `distill ...` argv rows through the
existing ingest and analysis commands, records per-command outcomes, and writes
resume state under `.distill/profiles/<profile>/run_state.json`. Exact feed
items and YouTube videos complete once. Standing seeds remain repeatable so
recurring profiles keep checking for new material.

Cycle 4 added the first complete zero-dollar ledger slice: cost-log rows now
record `usage_ledger`, `by_provider`, and `by_route_class`, and approved profile
runs write zero-dollar `profile-run` orchestration rows.

Cycle 5 completed richer no-metered route-block reporting: blocked policy
messages and reports now include provider, workload, cost class, required proof
when applicable, and paid-ok retry guidance for intentional metered runs.

Cycle 6 added profile loop handoff rows: `profile-run.v1` JSON now emits
`next_actions` entries using the same structural action contract as audit,
including argv commands, approval class, write scope, verifier, and loop
metadata.

Cycle 7 added audit-visible recurring profile health to `distill audit all`.
The audit remains deterministic and local-only: it reports invalid profile
files, missing goals, missing or stale run state, recorded profile command
failures, invalid state, and profiles whose local corpus is thin relative to
their saved source plan.

Cycle 8 started adapter doctor scaffolding with `distill doctor --adapters`.
The check is read-only and fail-closed: it reports candidate adapter binary
presence, version/help probes, required structured-output flags, API-key
environment blockers, route class, and support-statement status without running
adapter workloads.

Cycle 9 added the strict `adapter-result.v1` manifest boundary for future CLI
adapter runs. The parser rejects unknown fields, missing usage signals, unsafe
scratch-relative paths, unknown adapters, and no-metered results that report
metered auth, API-key blockers, or metered usage allowance. The adapter doctor
JSON report now publishes that contract so external loops can inspect it before
any route graduates.

Cycle 10 added local config auth-marker scanning to adapter doctor. It parses
known TOML and JSON config files, reports matched marker names and display
paths only, classifies API-key environment variables and API-key config fields
as metered blockers, and reports session markers as evidence without making
routes eligible.

Cycle 11 added before/after scratch workspace write checks for future adapter
runners. A runner can snapshot staged source files before execution, parse the
`adapter-result.v1` manifest afterward, and reject missing declared outputs or
unexpected new scratch files.

Cycle 12 added the generic scratch-only adapter runner primitive. It runs exact
argv arrays with shell disabled, strips known metered API-key environment
variables, enforces a timeout, captures bounded output tails, parses the result
manifest, and applies scratch write checks.

Cycle 13 structured adapter support statements as data instead of prose-only
status. Adapter doctor reports now include checked date, source URLs, required
evidence, no-metered current status, and notes for each candidate route. Planned
plan-quota routes remain blocked because their support records are not current,
and Copilot remains a credit-metered candidate rather than a no-metered default.

Cycle 14 added structured `quota_stop` metadata to the future
`adapter-result.v1` manifest boundary. Quota and rate-limit stop reasons now
require a reached flag and reason, preventing adapter runners from hiding quota
exhaustion in free-text stop output.

Cycle 15 added an adapter ledger bridge. Verified `adapter-result.v1` manifests
can now produce cost-tracker token rows and metadata, with included-plan auth
classified as zero-dollar usage and rolled up separately from local and metered
routes. This is an accounting primitive only; it does not select or enable any
adapter route.

Cycle 16 added the strict `adapter-workload.v1` input package boundary and
exposed it through adapter doctor JSON. Future read-only adapter prototypes now
have a checked scratch-relative package shape before any CLI receives prompts
or source files. The same cycle tightened manifest path normalization so raw
`.` path segments cannot be normalized away.

Cycle 17 added a checked adapter workload runner that composes
`adapter-workload.v1` packages with the scratch adapter runner. It runs exact
argv arrays only in scratch and blocks result manifests that read outside the
declared package, write outside declared outputs, or report a different cost
mode. The manifest parser now also rejects read-only results that declare
written files.

Cycle 18 added a blocked adapter command planner. It records the future Codex
read-only `codex exec --sandbox read-only` argv shape, inherits adapter doctor
blockers, and remains ineligible until the later manifest writer and remaining
route gates exist.

Cycle 19 added a native adapter result writer. It writes validated
`adapter-result.v1` scratch manifests from captured CLI output, workload input
hashes, and caller-supplied native usage metadata, and the workload runner now
allows declared capture files such as `result.txt` while blocking undeclared
scratch writes.

Cycle 20 added command-plan capture metadata and a blocked Grok read-only
template. Codex and Grok plans now record future argv shapes plus staged prompt
paths, result capture paths, and allowed scratch capture files, while remaining
ineligible until native usage collection, support proof, auth proof, and eval
evidence exist.

Cycle 21 added schema-path command-plan metadata and a blocked Claude read-only
template based on local `claude -p --help` output. Codex, Claude, and Grok
plans now record staged prompt paths, schema paths, result capture paths, and
allowed scratch capture files, while Claude remains blocked until schema
inlining, native usage collection, support proof, auth proof, and eval evidence
exist.

Remaining near-term gaps are official installed-session auth proof,
remaining adapter-specific capture wiring, remaining adapter command templates,
real native usage collection for future plan-quota adapters, and eval-gated
route graduation.
