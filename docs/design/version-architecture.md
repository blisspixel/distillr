# Version architecture: 0.x -> 1.0 -> 2.0 -> 3.0

Status: design / vision. The near-term spine (releases, milestones,
quality gates) lives in [`../../ROADMAP.md`](../../ROADMAP.md) and stays the
operational source of truth; this document is the longer horizon -- what each
major version *promises*, in what order, and where the detail for each piece
lives or will live. Versions are ordered by dependency, never by calendar.
Anchored to [`../invariants.md`](../invariants.md): the invariants hold across
every era below, or the era is wrong.

## The eras, by promise

Each major version is a promise to users, not a feature count. A major version
ships when its promise is true and tested, and not before.

### 0.x (now) -- "The loop works"

The promise being built: one tool takes a research goal to a verified,
agent-legible, self-auditing local corpus. As of 0.16.1, the main loop is
substantially true: goal-aware convergent discovery, lens-aware analysis,
write-time claim grounding on every emit path, eight source types, the full
audit trust surface, `ask`/`--save`, read-only MCP, sub-agent summaries,
estimator accountability, the local entailment tier, verify-on-synthesis,
agent-grade `--json`, `distill update`, and the blocking golden-corpus eval
gate have all shipped.

Remaining before the 1.0 gate opens, in dependency order:

1. **0.17 OKF interop + loop-ready stewardship.** Export and validate native
   corpora as OKF v0.1 bundles, and emit audit-derived next-action plans that
   external loops can run and verify.
2. **0.18 decomposition finish + batch-run visibility.** Delete the remaining
   `_logic.py` monolith, then add live progress, running cost, verbosity, and
   consistent help examples for the batch commands.
3. **0.19 recurring research profiles + no-metered-cost routing.** Make
   ongoing topics like AI developer news and live agentic dev first-class
   profiles, then add a fail-closed cost policy for local inference and
   explicitly configured plan-quota CLI routes.
4. **Harden passes interleaved.** Keep the established rhythm for security,
   robustness, dependency, and parse-don't-crash sweeps.

### 1.0 -- "You can build on it"

The promise: **stability and a defended quality bar.** Contracts (CLI flags,
MCP schemas, library layout, frontmatter, OKF export schema, next-action JSON
schema, profile config schema, and cost-mode semantics) are versioned and
frozen; prompts stay versioned-but-revisable when evals or model changes
justify it; branch coverage >=95%; Pyright-strict; parse-don't-validate
boundaries; the structural golden-corpus eval gate plus model-judged live
`distill eval`; verification depth on the deterministic core; the presentation
pass (screenshots/recordings land here, by deliberate deferral). An external
system -- Deepr, a stranger's agent stack, a lab's cron job -- can depend on
distill without expecting churn.

Full spec: [`../../ROADMAP.md`](../../ROADMAP.md), "1.0.0 -- Stability
commitment + quality bar". Decision due before the freeze: the project name
(rename window closes at 1.0).

### 2.0 -- "Runs on whatever you have, unattended, and compounds"

The promise: **provider-plural, loop-native, and self-improving under audit.**
Everything here exists in committed-direction form already; 2.0 is where the
promises graduate from additive surfaces to default posture:

- **Provider breadth + plan-quota compute** (the committed post-1.0
  milestone): 0.19 establishes no-metered-cost policy and the first adapter
  contract; 2.0 broadens it across cloud adapters (xAI, Google, Anthropic,
  OpenAI, Bedrock, Foundry) and plan-quota CLIs your subscriptions already
  license. Every backend graduates only through `distill eval`. The 2.0-level
  promise: *the default route is whatever clears the quality bar cheapest on
  your hardware and plans*, re-evaluated by the eval harness, not by vibes.
- **Stewardship loops mature**: goal-file watch refresh, scheduled audit, and
  reconcile behavior (assess -> plan -> act -> verify) folded into the core
  workflows. Distill remains the loopable primitive; the loop runner stays
  external.
- **The trust ceiling rises**: audit gains trend lines, evaluator calibration
  improves, and external loop transcripts become fixtures for improving tool
  descriptions and next-action schemas.
- **The semantic layer**: alias resolution over `mentions.jsonl` (the staged
  symbolic+semantic pipeline already specced), Tier-2 concept/entity playbooks
  maintained at scale, shared LLM-intermediate caching as the load-bearing
  pattern that makes loops affordable.

### 3.0 -- "Corpora outlive the tool" (directional, honestly speculative)

The promise: **the corpus as a portable, shareable, composable substrate.**
This era is sketched, not committed -- it gets real design docs only after
2.0's loops have run in the wild:

- **Shareable recipes**: a goal-file + seeds + intent as a published artifact
  anyone can reproduce or refresh a corpus from (research *intent* as the
  unit of sharing, not just outputs).
- **Corpus interop**: OKF bundles, native Distill corpora, and recipe artifacts
  can be compared and merged git-natively across people and machines;
  provenance survives the merge.
- **The plugin boundary realized**: community source adapters on the
  documented contract, gated by the golden-corpus eval -- the cap on built-in
  adapters stays, the ecosystem grows around it.
- **Local-by-default**, if and when consumer hardware clears the eval bar for
  the analysis workloads -- the router was built so this flips per-workload
  without touching pipeline code.

### Maybe later (parked, not promised)

Ideas with real merit that earn a design doc only when something concrete
pulls them forward: trend radar / evolution timelines beyond the current
diff/trends artifacts; voice/persona cards for creators; multi-topic channels
with shared transcripts; notification integrations (email/Slack digests);
additional source types beyond the plugin boundary (LinkedIn, HN, Discord
exports); a richer web UI. Each stays parked until a dogfooded need names it.

### Intentionally not -- in any era

The standing exclusions in [`../../ROADMAP.md`](../../ROADMAP.md)
("Intentionally not in scope") are version-independent: no database of
record, no proprietary viewer or SaaS, no general-purpose RAG store, no
multi-user/auth layer, no anti-bot scraping, no cheap-mode that compromises
fidelity, no loop-runner/orchestrator surface inside distill. If a future era
seems to need one of these, the era is mis-designed.

## Design-doc ledger

Per the working rhythm, a milestone gets (a) a dogfood corpus on its problem
domain and (b) a design doc, *before* build -- written at slice start, not
speculatively. Current state:

| Area | Design doc | Status |
|---|---|---|
| Whole-pipeline agentic plan (P1-P8) | [`agentic-distill-master-plan.md`](agentic-distill-master-plan.md) | Live; P1-P3/P6/P7 shipped, P4/P5 partial (deterministic verify shipped) |
| Synthesis depth / thesis loop | [`agentic-deep-synthesis.md`](agentic-deep-synthesis.md) | Live; thesis rung shipped, loop pending |
| Version horizon (this doc) | `version-architecture.md` | Live |
| Entailment verification tier | [`entailment-tier.md`](entailment-tier.md) | Shipped 0.13.0 and 0.13.1 |
| `distill ask` + re-ingest gating | [`ask-loop.md`](ask-loop.md) | Live; shipped 0.12.0 |
| OKF interop + loop-readable stewardship | [`okf-loop-readiness.md`](okf-loop-readiness.md) | Next build slice |
| Recurring profiles + no-metered-cost routing | [`recurring-profiles-cost-routing.md`](recurring-profiles-cost-routing.md) | 0.19 slice |
| Provider-adapter breadth | -- | 2.0-era expansion after the 0.19 contract proves out |
| Recipe format / corpus merge | -- | 3.0-era; do not write yet |

## The order of operations, in one list

Dependency-ordered, no calendar: OKF export/validation + loop-readable
next-actions -> finish `_logic.py` decomposition -> batch progress/cost UX ->
recurring profiles + no-metered-cost routing -> 1.0 freeze (name decision,
contract/version policy, quality gate, presentation) -> provider breadth
(2.0 spine) -> stewardship loops + semantic layer (2.0 completion) ->
recipes/merge/plugins (3.0). Every step ships behind the same CI gate, starts
with its dogfood corpus and design doc where the work is architectural, and
respects the invariants. That is what "built out exceptionally well" means
operationally.
