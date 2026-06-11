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
agent-legible, self-auditing local corpus. Most of it is already true:
goal-aware convergent discovery, lens-aware analysis, write-time claim
grounding on every emit path, `distill audit`, six source types
(YouTube, websites, arXiv, X, GitHub repos, podcasts), CLAUDE.md/AGENTS.md/
SKILL.md/MCP agent surfaces. Remaining before the 1.0 gate opens, in
dependency order:

1. **Finish 0.11 breadth** -- generic audio/video files (falls out of the
   local-file dispatcher + Whisper layer), Substack/newsletter (RSS + the
   existing site scraper + per-post extraction). Each lands behind the verify
   gate on the adapter contract.
2. **0.12 compounding corpus** -- `distill ask` + verified `--save` re-ingest;
   scheduled refresh + scheduled audit; semantic dedup; artifact-level
   stale-detection; budget guardrails + estimator-accuracy accountability;
   MCP write-side gating (`DISTILL_MCP_READ_ONLY`); sub-agent summary tools.
3. **Parallel track, any time it fits: the entailment tier** -- HHEM-class
   local checker for named entities and prose claims, layered on (never
   replacing) the deterministic tier; verify on synthesis emits. Needs its own
   design doc before build (see ledger).
4. **Harden passes interleaved** per the established rhythm, plus the
   `_logic.py` decomposition ratchet (one command group per pass, removal
   criteria already defined).

### 1.0 -- "You can build on it"

The promise: **stability and a defended quality bar.** Contracts (CLI flags,
MCP schemas, library layout, frontmatter) are versioned and frozen; prompts
stay versioned-but-revisable on a documented cadence; branch coverage >=95%;
Pyright-strict; parse-don't-validate boundaries; the golden-corpus eval gate
with metamorphic robustness; verification depth on the deterministic core;
the presentation pass (screenshots/recordings land here, by deliberate
deferral). An external system -- Deepr, a stranger's agent stack, a lab's
cron job -- can depend on distill without expecting churn.

Full spec: [`../../ROADMAP.md`](../../ROADMAP.md), "1.0.0 -- Stability
commitment + quality bar". Decision due before the freeze: the project name
(rename window closes at 1.0).

### 2.0 -- "Runs on whatever you have, unattended, and compounds"

The promise: **provider-plural, loop-native, and entailment-verified.**
Everything here exists in committed-direction form already; 2.0 is where the
promises graduate from opt-in to defaults:

- **Provider breadth + plan-quota compute** (the committed post-1.0
  milestone): cloud adapters complete (xAI, Google, Anthropic, OpenAI,
  Bedrock, Foundry) and the plan-quota class (agent CLIs your subscriptions
  already license) -- every backend graduating only through `distill eval`.
  The 2.0-level promise: *the default route is whatever clears the quality
  bar cheapest on your hardware and plans*, re-evaluated by the eval harness,
  not by vibes.
- **Stewardship loops mature**: goal-file watch refresh, scheduled audit, and
  the reconcile behavior (assess -> plan -> act -> converge) folded into
  `discover`/`synthesize`/`audit` per the master plan -- distill remains the
  loopable primitive; the loop runner stays external.
- **The trust ceiling rises**: entailment-tier verification everywhere,
  including synthesis and `ask --save`; the audit gains trend lines
  (verification coverage over time).
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
- **Corpus interop**: merging and diffing corpora git-natively across people
  and machines; provenance survives the merge.
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
| Entailment verification tier | -- | **To write at slice start** (checker choice is pre-researched: HHEM-2.1-Open default, Granite via Ollama option, Auto-GDA adaptation path, QuanTemp eval fixture) |
| `distill ask` + re-ingest gating | -- | To write at 0.12 start (spec skeleton in ROADMAP) |
| Provider-adapter + plan-quota contract | -- | To write at the post-1.0 milestone start (commitments + caveats in ROADMAP) |
| Recipe format / corpus interop | -- | 3.0-era; do not write yet |

## The order of operations, in one list

Dependency-ordered, no calendar: finish 0.11 (media, Substack) -> 0.12
compounding corpus -> entailment tier whenever it fits alongside ->
harden passes + `_logic.py` ratchet throughout -> 1.0 freeze (name decision,
eval gate, presentation) -> provider breadth + plan-quota (2.0 spine) ->
stewardship loops + semantic layer (2.0 completion) -> recipes/interop/plugins
(3.0). Every step ships behind the same CI gate, starts with its dogfood
corpus and design doc, and respects the invariants -- that is what "built out
exceptionally well" means operationally.
