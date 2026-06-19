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
- An `AgentProvider`, but without the adapter doctor, support statement, usage
  ledger, scratch manifest, and eval proof needed for no-metered routing.

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
- Keeps plan-quota CLIs blocked until adapter doctor, support statement, ledger,
  scratch-manifest, and eval proof exist.

External spend used so far: `$0.00`.
