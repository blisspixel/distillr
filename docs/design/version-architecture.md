# Version architecture: 0.x -> 1.0 -> 2.0 -> 3.0

Status: design / vision. The near-term spine (releases, milestones,
quality gates) lives in [`../../ROADMAP.md`](../../ROADMAP.md) and stays the
operational source of truth; this document is the longer horizon -- what each
major version *promises*, in what order, and where the detail for each piece
lives or will live. Versions are ordered by dependency, never by calendar.
Anchored to [`../invariants.md`](../invariants.md): the invariants hold across
every era below, or the era is wrong. The human-role and product-quality test
lives in [`research-desk-doctrine.md`](research-desk-doctrine.md).

## The eras, by promise

Each major version is a promise to users, not a feature count. A major version
ships when its promise is true and tested, and not before.

### 0.x (now) -- "The loop works"

The promise being built: one tool takes a research goal to a verified,
agent-legible, self-auditing local corpus. As of 0.19.72, the feature spine is
complete through OKF export/validation, loop-ready audit next-actions,
recurring research profiles, cost-mode routing, adapter doctors, and the route
availability primitives. The remaining 0.x work is an evidence-driven
refinement program: keep candidate contracts open while UX, security,
reliability, observability, accessibility, operator recovery, Pyright
strictness, parse-don't-validate boundaries, and verification depth improve.
Claim-generation currentness and derived-origin preservation are part of this
trust refinement: removed assertions must not survive refresh, and a promoted
answer must not become apparent independent evidence when claims are
re-extracted from it.
The branch-coverage floor has reached 95%. A published performance baseline,
compatibility and migration evidence, and representative onboarding and
presentation work remain readiness conditions for a future stability decision.

Harden passes stay interleaved until 1.0. They cover security, robustness,
dependency, CI/CD supply chain, and parse-don't-crash sweeps without expanding
the public surface.

### 1.0 -- "You can build on it"

The promise: **stability and a defended quality bar.** Contracts (CLI flags,
MCP schemas, library layout, frontmatter, OKF export schema, next-action JSON
schema, profile config schema, and cost-mode semantics) are versioned and
frozen; prompts stay versioned-but-revisable when evals or model changes
justify it; branch coverage >=95%; Pyright-strict; parse-don't-validate
boundaries; the structural golden-corpus eval gate plus model-judged live
`distill eval`; verification depth on the deterministic core; the presentation
pass (screenshots/recordings land here, by deliberate deferral); and a published
performance baseline that separates deterministic Distill overhead from live
provider and network time. Python remains the reference control layer, while
optional native acceleration must clear the measured gate in
[`performance-and-language-admission.md`](performance-and-language-admission.md).
An external system -- Deepr, a stranger's agent stack, a lab's cron job -- can depend on
distill without expecting churn.

Full spec: [`../../ROADMAP.md`](../../ROADMAP.md), "1.0.0 -- Stability
commitment + quality bar". Decision due before the 1.0 stability commitment:
the project name (rename window closes at 1.0).

### 2.0 -- "The corpus explains the field and compounds"

The promise: **Distillr behaves like an exceptional research desk.** It builds
the smallest trustworthy evidence portfolio that is sufficient for the current
intent, explains the field represented by that evidence, and reports meaningful
changes over time. Provider plurality and agentic loops are enabling
capabilities, not the product promise:

- **A research program organizes acquisition.** Operator intent remains stable;
  model-proposed lines of inquiry identify what evidence matters and why.
- **Discovery curates an evidence portfolio.** Candidate plans expose source
  role, expected distinct contribution, independence or derivation, redundancy,
  and likely effect on the field model. Realized contribution is assessed after
  ingest.
- **One field model spans supported source types.** A small contribution
  envelope lets source-sensitive paper, talk, site, repository, feed, podcast,
  post, and local-file analysis inform one view of established, contested,
  scope-dependent, emerging, unsupported, and unknown conclusions.
- **Refresh reports intellectual change.** Profiles distinguish new,
  strengthened, weakened, qualified, reframed, resolved, and unchanged findings
  and avoid repeatedly processing stable inquiries without evidence of value.
- **Research navigation becomes a first-class output.** The corpus can produce
  bounded reading paths for a beginner, practitioner, researcher, historical
  review, frontier update, or contested conclusion.
- **Stewardship loops mature.** Assessment, approved action, verification,
  resynthesis, and honest stopping compose inside existing workflows while the
  loop runner stays external.
- **The trust ceiling rises.** Mature provenance adds digest-bound evidence
  anchors, explicit source-versus-derived origin, typed scope and time, and
  unknown-safe source-lineage assessments. A narrow semantic firewall admits
  model-proposed relations through schema, domain, semantic, authority, and
  commit gates without adding an ontology platform or graph database.
- **Compute becomes substitutable.** Cloud providers and plan-quota workers
  graduate only through `distill eval`, with no-metered mode failing closed on
  ambiguous billing. The router chooses among qualified routes; route breadth
  does not substitute for research quality.

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
| Research-desk product doctrine | [`research-desk-doctrine.md`](research-desk-doctrine.md) | Live; feature-admission and evaluation frame |
| Whole-pipeline agentic plan (P1-P8) | [`agentic-distill-master-plan.md`](agentic-distill-master-plan.md) | Live; P1-P3/P6/P7 shipped, P4/P5 partial |
| Bounded field-model reconciliation | [`agentic-deep-synthesis.md`](agentic-deep-synthesis.md) | Live; current synthesis shipped, loop pending |
| Version horizon (this doc) | `version-architecture.md` | Live |
| Path to 1.0 (gates + order) | [`path-to-1.0.md`](path-to-1.0.md) | Live; operational checklist |
| Contract compatibility | [`../contracts/COMPATIBILITY.md`](../contracts/COMPATIBILITY.md) | Live; freeze-ready policy |
| Offline performance baseline | [`../performance/baseline-0.19.50.md`](../performance/baseline-0.19.50.md) | Partial scale-100 evidence |
| Entailment verification tier | [`entailment-tier.md`](entailment-tier.md) | Shipped 0.13.0 and 0.13.1 |
| `distill ask` + re-ingest gating | [`ask-loop.md`](ask-loop.md) | Live; shipped 0.12.0 |
| OKF interop + loop-readable stewardship | [`okf-loop-readiness.md`](okf-loop-readiness.md) | Shipped 0.17; OKF v0.2 current |
| Evidence anchors, semantic firewall, and atomic-claim handoff | [`evidence-anchors-and-claim-handoff.md`](evidence-anchors-and-claim-handoff.md) | Accepted direction; generation/origin fix current, relation experiments and packet post-1.0 |
| Recurring profiles + no-metered-cost routing | [`recurring-profiles-cost-routing.md`](recurring-profiles-cost-routing.md) | 0.19 slice |
| Performance + implementation-language admission | [`performance-and-language-admission.md`](performance-and-language-admission.md) | 1.0 decision charter; baseline pending |
| Provider-adapter breadth | -- | 2.0-era expansion after the 0.19 contract proves out |
| Recipe format / corpus merge | -- | 3.0-era; do not write yet |

## The order of operations, in one list

Dependency-ordered, no calendar: OKF export/validation + loop-readable
next-actions -> finish `_logic.py` decomposition -> batch progress/cost UX ->
recurring profiles + no-metered-cost routing -> claim-generation currentness
and derived-origin correction -> 1.0 freeze (name decision, contract/version
policy, quality gate, presentation) -> research-desk evaluation baseline ->
evidence anchors and unified contribution handoff -> research program and
portfolio selection -> field model, meaningful refresh, and reading paths ->
bounded stewardship loops -> qualified provider breadth -> recipes, merge, and
plugins. Every step ships behind the same CI gate, starts with its dogfood
corpus and design doc where the work is architectural, and respects the
invariants. That is what "built out exceptionally well" means operationally.
