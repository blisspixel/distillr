# Distill: agentic & exceptional on any topic - master refinement plan

Status: design / RFC. The vision plan for turning distill from a linear,
single-shot, fixed-persona pipeline into a **goal-driven, adaptive** research
system that produces better output on *any* topic - research, competitive intel,
academic, or hobby.

Companion spec: [`agentic-deep-synthesis.md`](agentic-deep-synthesis.md) is the
detailed design for Pillar 3 (the synthesis loop); this doc is the whole-pipeline
plan that contains it. Anchored to [`../invariants.md`](../invariants.md) and the
[`../../ROADMAP.md`](../../ROADMAP.md).

## Status: shipped vs. planned (read this first)

Be precise about the word "agentic" - most of this doc is still plan, not built.

- **Shipped (0.9.24 / 0.9.25), and it improves the *core* pipeline in place - no
  new workflow commands:**
  - **Better analyze output** - per-source insights are written through a lens
    that fits the topic (`research`/`practitioner`/`competitive`/`academic`/
    `general`) instead of one hardcoded enterprise persona (Pillar 2).
  - **Goal-aware end-to-end** - a persisted `CorpusIntent` flows into analysis,
    so the pipeline is no longer goal-blind after discovery (Pillar 1).
  - **Deeper synthesize output** - the thesis / white-space rung (Pillar 3).
  - **Graceful failure** - clean provider errors + opt-in local fallback (Pillar 7).
- **NOT built - still plan:** the self-correcting *loop* (verify → find gaps →
  re-search → re-synthesize → converge). Today each pipeline step still runs a
  single, smarter, goal-shaped pass. "Agentic" in the autonomous-loop sense is
  Pillars 4-6/8 below, and when built it lands as **flags on the existing
  commands** (`discover` / `synthesize` / `audit`), not new verbs.

So today's honest claim: **same core process, materially better and more
goal-aware outputs - not an autonomous loop.**

## The one-line goal (the vision, not today's state)

A user declares an *intent* and distill **reconciles a corpus toward it** -
discovering, analyzing, verifying, synthesizing, re-searching until it is good
enough, then keeping it that way. The self-correcting half of this is the planned
work above, not what ships today.

## What's actually wrong today (grounded in the 2026-06-09 dogfood)

A live run on the `agentic-harness` corpus exposed the structural gaps. These are
evidence, not speculation:

| # | Finding | Evidence |
|---|---------|----------|
| F1 | **Per-item analysis hardcodes a pre-sales enterprise persona.** `pass2_synthesis_prompt` makes every video insight a "pre-sales architect" doc with *Vendor Watch / Business Value Signals / Customer Conversation Starters*. | All 12 video insights in a *research* corpus carry "Customer Conversation Starters." |
| F2 | **The goal is goal-blind after discovery.** Intent shapes `discover`'s queries/rerank, then vanishes; analysis and synthesis never see it. | `paper_insight_prompt` / `pass1`/`pass2` take title + content, never the goal. |
| F3 | **No top rung.** Synthesis stops at "what no single source says"; there is no thesis / white-space / falsifiable-hypothesis layer. | `claim_synthesis_prompt` has no thesis section; the OpenSteward "name the unoccupied space" answer had to be read out by hand. |
| F4 | **Linear & single-shot.** No verify, no gap-fill, no convergence; the pipeline sees each pile exactly once. | No loop anywhere in `pipeline/`. |
| F5 | **No corpus-aware dedup; non-deterministic plans.** `discover` re-suggests already-ingested items; identical previews size to 12 then 10 with different queries. | Preview vs. preview drift; rerank shortlist included ingested videos. |
| F6 | **Brittle failure.** A known 403 "out of credits" dumped a raw `openai` traceback; no fallback to an available local model; left a non-resumable partial state (5 papers, no synthesis, no videos). | The crash that interrupted this very run. |
| F7 | **Weak relevance floor on discovery.** The `steward` topic is polluted with enterprise *data-stewardship* content from a bare keyword. | `steward` corpus = Atlan/Aiven/Neo4j "context layer." |

The throughline: **distill assumes one lens, runs once, trusts itself, and breaks
loudly.** Every pillar below removes one of those assumptions.

## The reframe: one desired-state object, flowing through agentic stages

Today intent is a transient string in `discover`. Make it a first-class object,
`CorpusIntent`, that **every stage consumes**:

```
CorpusIntent {
  goal:        the research goal (free text or goal-file)
  lens:        research | competitive-intel | practitioner | academic | market | exec | …
  audience:    who reads the output (shapes register, not facts)
  rigor:       strict | balanced | loose  (relevance floor + verification depth)
  quality_bar: convergence criteria (coverage, grounding %, thesis stability)
  budget:      per-run ceiling (usd / tokens / iterations)
}
```

Then every stage becomes a small **assess → plan → act → converge** loop over that
intent, instead of a one-shot transform. The same reconcile engine powers
discovery and synthesis (Pillar 4). That is the agentic spine.

## The eight pillars

### P1 - `CorpusIntent` as a first-class object (the backbone)
**Problem:** F2. Intent dies at discovery.
**Change:** Define `CorpusIntent` (a frozen Pydantic model, parsed once at the
boundary per the 1.0 "parse, don't validate" rule). Thread it through
discover → analyze → synthesize → deepen. Persist it as `topics/<t>/intent.json`
so refreshes, audits, and the orchestrator all read the same desired state.
**Why it generalizes:** the intent is the *only* thing that should differ between a
physics corpus and a competitive-intel corpus. Make it explicit and everything
downstream can adapt.
**Phase:** 1 (foundation; everything else reads it). Shipped 0.9.24/0.9.25.
**Follow-up (with the P4 loop work): intent-driven source-mix policy.** Today the
papers/videos/sites mix per goal is emergent - whatever search returns, shaped by
the rerank's complementarity score. `CorpusIntent` already knows the lens and
rigor, so `discover` could derive a deliberate mix policy from it: a research goal
weights papers + expert lectures; a "current social view" goal weights X + recent
YouTube; a vendor evaluation weights official docs. A refinement *inside*
`discover` (per-source quota weighting before the rerank slice), no new surface.

### P2 - Adaptive analysis lens (kill the hardcoded persona)
**Problem:** F1. One sales persona for all topics.
**Change:** Replace the fixed sections in `pass2_synthesis_prompt` /
`paper_insight_prompt` / `site_page_insight_prompt` with **lens-selected section
sets** driven by `CorpusIntent.lens`. Enterprise pre-sales becomes *one* lens
(`competitive-intel`), not the default. A `research` lens emits Claim / Method /
Evidence / Limitation / Open-question sections; `practitioner` emits
How-it-works / Gotchas / When-to-use; etc. Default lens is inferred from the goal
when unset. Per-item analysis also receives the goal so extraction prioritizes
goal-relevant signal (today it extracts "everything of substance," goal-blind).
**Why it generalizes:** this is *the* change that makes output good on any topic.
The quality floor stops fighting the subject matter.
**Phase:** 1 (highest single-change leverage).

### P3 - Depth ladder + thesis rung (the exceptional output)
**Problem:** F3. No top rung.
**Change:** Promote the implicit ladder to explicit artifacts:
**Facts** (`claims.jsonl`, exists) → **Patterns** (comparison matrix, blind spots,
exists) → **Insights** ("what no single source says," exists) → **Thesis /
white-space** (NEW: the defensible novel position, the unoccupied space,
falsifiable hypotheses). Each thesis claim cites the rungs below it and carries a
grounding status. Full spec in
[`agentic-deep-synthesis.md`](agentic-deep-synthesis.md).
**Why it generalizes:** "what's the defensible new thesis / where's the white
space" is the payoff of *any* serious synthesis, not just OpenSteward's.
**Phase:** 1 (prompt-only thesis rung) → 3 (loop-driven).

### P4 - Agentic loops everywhere (one reconcile engine)
**Problem:** F4. Linear & single-shot.
**Change:** Build one `reconcile(intent, corpus)` engine - assess gap to desired
state → emit a plan (diff) → act → re-assess → converge - and use it twice:
- **Discovery loop:** ingest → assess coverage vs. goal (reuse `research_gaps`) →
  gap-fill via `discover --from-gaps` → converge when no new high-value source
  clears the rigor floor.
- **Synthesis loop:** the deep-synthesis reconciliation (verify-inward + receipted
  discover-outward + reference-chase + re-synthesize → converge).
Both terminate on the same guarantees: budget ceiling, iteration cap, idempotent
no-op at steady state.
**Why it generalizes:** convergence ("keep going until the corpus actually serves
the goal") is topic-independent.
**Phase:** 3.

### P5 - Verification fabric (the trust layer)
**Problem:** F4 (self-trust). The corpus is only as good as the check on what
enters it.
**Change:** Implement the 0.10 run-time verify hook as a reusable pass: extract
load-bearing claims (numbers, named entities, dates) and ground each against its
source receipt (grep/regex first, small local model second - never an
LLM-as-judge-of-record, per the invariants). Emit `_verify.json` sidecars;
`--verify warn|strict|off`. The synthesis loop and the `ask`/re-ingest loop both
gate on it. Outward search during a loop **ingests receipted artifacts** before
informing prose - never free-floating web claims.
**Why it generalizes:** grounding is the universal correctness primitive.
**Phase:** 2.

### P6 - Determinism & idempotence where it matters
**Problem:** F5. Non-reproducible plans, no dedup.
**Change:** (a) **Corpus-aware dedup**: the rerank shortlist excludes/down-weights
identities already in the corpus - which is also what makes the discovery loop's
convergence meaningful. (b) **Reproducible plans**: pin temperature on query-gen
+ rerank and cache the plan by `(intent_hash, candidate_set_hash)` so a re-preview
is stable. (c) **Cached LLM intermediates** (`distill/llm/cache.py`): claims,
critiques, re-synth keyed by content hash so loops are affordable and a converged
re-run is near-free.
**Why it generalizes:** "agentic IaC" is meaningless without plan/apply
reproducibility and a real no-op steady state.
**Phase:** 2. **Status:** (a) corpus-aware dedup and (b) reproducible plans
shipped in 0.9.27 (`discover`/`papers` drop already-ingested candidates before
the rerank; query-gen + every rerank call pinned to temperature=0, on top of
the earlier preview cache / `--from-preview`). (c) cached LLM intermediates
remains.

### P7 - Robustness & graceful degradation
**Problem:** F6. Loud, lossy failure.
**Change:** (a) **Typed provider errors**: catch the credit-exhaustion / rate-limit
/ auth classes and render a one-line actionable message, never a traceback.
(b) **Local fallback**: on cloud-exhaustion, offer/auto-route remaining analysis
to Ollama (the box already has a 4090 + qwen3.5:27b) under a `--fallback local`
policy. (c) **Resume-friendly runs**: checkpoint per-item so a crash resumes
instead of restarting; partial state is detected, not re-paid.
**Why it generalizes:** any long agentic run will hit provider limits; it must
degrade, not detonate.
**Phase:** 2 (the error + fallback fix is small and was just demonstrated).

### P8 - The agentic flow lives in the existing commands (NOT a new command)
**Problem:** the pieces above should make the *core* process more agentic. They
must NOT become a new top-level verb or orchestration layer. distill's value is a
small surface; a `distill steward` / `distill apply` / `distill deepen` command
would be scope creep (and "steward" also collides with the separate OpenSteward
project - distill stewards a *corpus*, that's all).
**Change:** Nothing new to learn. The goal-file already *is* the declarative
recipe, and `discover --goal-file` already runs it; `discover --from-gaps` already
loops on coverage gaps. The reconcile / verify / thesis behavior folds into the
commands that already own each step:
- discovery loop → inside `discover` (it already re-ranks against the goal and can
  gap-fill),
- verify + thesis rung → inside `synthesize` / `resynthesize`,
- the assess/critique step → inside the planned `audit`.
So "more agentic" shows up in the tools people already use, with no new command.
**Why:** the core capture → analyze → synthesize flow self-corrects; the surface
stays the same size. The 2026 "loop engineering" framing makes the boundary
crisp: distill is the loopable primitive + persistent state layer (idempotent,
convergent, verify-gated, report-emitting); the loop *runner* is the layer above
(cron, an agent harness, OpenSteward) and stays out of this repo.
**Phase:** 4 - and only the parts that earn their keep; the goal-file + `discover`
already cover the common case.

## Phased build order (each phase shippable, dependency-ordered)

- **Phase 1 - Adaptive quality (biggest visible jump, low risk):**
  P1 `CorpusIntent` + P2 adaptive lens + P3 thesis-rung prompt. After this,
  outputs are good on any topic and synthesis has a top rung - with zero new
  control flow. *This is what I'd build first.*
- **Phase 2 - Trust & resilience:** P5 verify fabric + P6 dedup/determinism/cache
  + P7 robustness. Makes the corpus trustworthy and runs survivable.
- **Phase 3 - Agentic loops:** P4 reconcile engine → discovery loop + synthesis
  loop. Distill now self-drives to convergence.
- **Phase 4 - Fold the loop into existing commands:** discovery loop inside
  `discover`, verify + thesis inside `synthesize`/`resynthesize`, the assess step
  inside `audit`. No new command; the core process just self-corrects.

## Invariant compliance (must not break the charter)

- **Pure-Markdown corpus / provenance-first:** outward search ingests receipts; no
  prose-only external claims. Lenses change *sections*, never *fabrication rules*.
- **No cheap mode:** lenses and loops reuse calibrated prompts; new prompts
  (thesis, critic, lens variants) are `prompt_id`-versioned and enter the golden
  eval gate. Adaptive lens is not "shorter/cheaper," it's "right-shaped."
- **No LLM-as-verifier-of-record:** P5 is grep/regex-first, small-model-second.
- **Calibration debt:** each new lens is calibration surface; cap the lens set
  (≈5) and gate additions on `distill eval`, mirroring the source-adapter cap.
- **Termination & budget:** every loop is iteration- and budget-bounded and
  idempotent at steady state.

## What "exceptional" measures (success criteria)

- A research topic produces zero pre-sales sections; lens matches intent. (P2)
- Every synthesis has a thesis rung with a falsifiable claim and a named white
  space. (P3)
- Every load-bearing number in a synthesis is grounded to a receipt or flagged.
  (P5)
- Re-running `discover` / `synthesize` on a converged corpus is a near-free no-op;
  re-running with a new source ingests only the delta. (P4/P6)
- A provider outage degrades to local or a clean message, never a traceback, and
  resumes. (P7)
- One declarative recipe takes any intent from empty to an exceptional, maintained
  corpus. (P8)

## QA findings index

F1-F7 above are tracked as the motivating defects. The quick wins already isolated
and ready to implement independently of the big plan: **P7's error+fallback fix**
(F6) and **P2's lens swap** (F1) are the two highest-leverage, lowest-risk changes.
