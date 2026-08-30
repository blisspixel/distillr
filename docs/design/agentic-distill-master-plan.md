# Agentic pipeline refinement plan

Status: design / RFC. This is the implementation plan for turning Distill from
a linear, single-shot, fixed-persona pipeline into a goal-driven, adaptive
research-corpus system. Agentic execution is a technique in service of the
research desk, not the product identity or success condition.

Companion spec: [`agentic-deep-synthesis.md`](agentic-deep-synthesis.md) is the
detailed design for Pillar 3 (the synthesis loop); this doc is the whole-pipeline
plan that contains it. Anchored to [`../invariants.md`](../invariants.md) and the
[`../../ROADMAP.md`](../../ROADMAP.md).
The product outcomes, human role, research-state boundaries, and feature rubric
are defined in [`research-desk-doctrine.md`](research-desk-doctrine.md).

## Status: shipped vs. planned (read this first)

Be precise about the word "agentic" - most of this doc is still plan, not built.

- **Shipped (0.9.24 / 0.9.25), and it improves the *core* pipeline in place - no
  new workflow commands:**
  - **Better analyze output** - per-source insights are written through a lens
    that fits the topic (`research`/`practitioner`/`competitive`/`academic`/
    `general`) instead of one hardcoded enterprise persona (Pillar 2).
  - **Goal-aware end-to-end** - a persisted `CorpusIntent` flows into analysis,
    so the pipeline is no longer goal-blind after discovery (Pillar 1).
  - **Deeper synthesize output** - a thesis / white-space section (Pillar 3).
    Future revisions must allow the evidence to support no novel thesis.
  - **Graceful failure** - clean provider errors + opt-in local fallback (Pillar 7).
- **NOT built - still plan:** the self-correcting *loop* (verify → find gaps →
  re-search → re-synthesize → converge). Today each pipeline step still runs a
  single, smarter, goal-shaped pass. "Agentic" in the autonomous-loop sense is
  Pillars 4-6/8 below, and when built it lands as **flags on the existing
  commands** (`discover` / `synthesize` / `audit`), not new verbs.

So today's honest claim: **same core process, materially better and more
goal-aware outputs - not an autonomous loop.**

## The one-line implementation goal

A user declares an intent and Distill reconciles a bounded evidence portfolio
toward it: discovering, curating, analyzing, verifying, synthesizing, and
researching again only when another pass is likely to matter. The
self-correcting half remains planned work, not shipped behavior.

## What the 2026-06-09 dogfood found

A live run on the `agentic-harness` corpus exposed the structural gaps below.
The shipped-versus-planned status near the top of this document is the current
truth; this table preserves the evidence that motivated the work.

| # | Finding | Evidence |
|---|---------|----------|
| F1 | **Per-item analysis hardcodes a pre-sales enterprise persona.** `pass2_synthesis_prompt` makes every video insight a "pre-sales architect" doc with *Vendor Watch / Business Value Signals / Customer Conversation Starters*. | All 12 video insights in a *research* corpus carry "Customer Conversation Starters." |
| F2 | **The goal is goal-blind after discovery.** Intent shapes `discover`'s queries/rerank, then vanishes; analysis and synthesis never see it. | `paper_insight_prompt` / `pass1`/`pass2` take title + content, never the goal. |
| F3 | **No top rung.** Synthesis stops at "what no single source says"; there is no thesis / white-space / falsifiable-hypothesis layer. | `claim_synthesis_prompt` has no thesis section; the OpenSteward "name the unoccupied space" answer had to be read out by hand. |
| F4 | **Linear & single-shot.** No verify, no gap-fill, no convergence; the pipeline sees each pile exactly once. | No loop anywhere in `pipeline/`. |
| F5 | **No corpus-aware dedup; non-deterministic plans.** `discover` re-suggests already-ingested items; identical previews size to 12 then 10 with different queries. | Preview vs. preview drift; rerank shortlist included ingested videos. |
| F6 | **Brittle failure.** A known 403 "out of credits" dumped a raw `openai` traceback; no fallback to an available local model; left a non-resumable partial state (5 papers, no synthesis, no videos). | The crash that interrupted this very run. |
| F7 | **Weak relevance floor on discovery.** The `steward` topic is polluted with enterprise *data-stewardship* content from a bare keyword. | `steward` corpus = Atlan/Aiven/Neo4j "context layer." |

At the time, the throughline was: **distill assumed one lens, ran once, trusted
itself, and broke loudly.** Every pillar below removes one of those assumptions.

## The reframe: stable intent plus evolving research state

Intent was once a transient string in `discover`. `CorpusIntent` made the
operator-owned desired state first-class and available to every stage:

```
CorpusIntent {
  goal:        the research goal (free text or goal-file)
  lens:        research | competitive-intel | practitioner | academic | market | exec | …
  audience:    who reads the output (shapes register, not facts)
  rigor:       strict | balanced | loose  (relevance floor + verification depth)
  budget:      per-run ceiling (usd / tokens / iterations / wall clock)
}
```

Do not overload `CorpusIntent` with changing judgments about coverage, quality,
or thesis stability. A model-proposed research program decomposes the intent
into inquiries. A regenerated corpus assessment records what is established,
contested, scope-dependent, or unknown. A bounded research plan proposes exact
next actions. Intent stays operator-owned while those derived views evolve.

When a loop is justified, its shape is **assess -> plan -> act -> reassess**.
The same bounded control pattern can serve discovery and synthesis without
pretending that every workflow needs autonomous reconciliation.

## The eight pillars

### P1 - `CorpusIntent` as a first-class object (the backbone)
**Problem:** F2. Intent dies at discovery.
**Change:** Define `CorpusIntent` (a frozen Pydantic model, parsed once at the
boundary per the 1.0 "parse, don't validate" rule). Thread it through
discover → analyze → synthesize → deepen. Persist it as `topics/<t>/intent.json`
so refreshes, audits, and the orchestrator all read the same desired state.
**Why it generalizes:** intent defines why the corpus exists, while a separate
research program captures what must be understood. Making both roles explicit
lets downstream work adapt without mixing operator input with model judgment.
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
**Why it generalizes:** the stable envelope stays inspectable while the model
preserves what makes a paper, lecture, repository, postmortem, or commentary
worth having. Adaptive analysis must not flatten every source into a different
fixed persona template.
**Phase:** 1 (highest single-change leverage).

### P3 - Depth ladder + field model
**Problem:** F3. No top rung.
**Change:** Promote the implicit ladder to explicit artifacts:
**Facts** (`claims.jsonl`, exists) → **Patterns** (comparison matrix, blind spots,
exists) → **Field model** (established, contested, scope-dependent, emerging,
unsupported, unknown, trajectory, implications, and optional hypotheses or
white space). Each compiled claim cites the rungs below it and carries an
honest grounding state. Full spec in
[`agentic-deep-synthesis.md`](agentic-deep-synthesis.md).
**Why it generalizes:** serious synthesis explains the body of evidence. A
novel thesis can be valuable, but requiring one creates novelty theater. The
correct result may be convergence, a scope-explained disagreement, or
insufficient evidence.
**Phase:** 1 (deeper prompt, shipped) → 3 (bounded field-model reconciliation).

### P4 - Bounded reconciliation where it earns its keep
**Problem:** F4. Linear & single-shot.
**Change:** Build one bounded `reconcile(intent, program, corpus)` control
pattern: assess the field model, identify an important uncertainty, emit a
reviewable plan, act within limits, then reassess. Candidate uses are:
- **Discovery loop:** ingest → assess coverage vs. goal (reuse `research_gaps`) →
  gap-fill via `discover --from-gaps` → stop when a model judges that no
  accessible candidate is likely to materially improve an important inquiry.
- **Synthesis loop:** the deep-synthesis reconciliation (verify-inward + receipted
  discover-outward + reference-chase + re-synthesize → reassess).
Both terminate under deterministic budget, time, source, and iteration caps.
A semantic sufficiency verdict is recorded separately from the mechanical
reason the run stopped.
**Why it generalizes:** bounded reassessment is useful across topics, while an
always-on loop would increase cost and activity without proving research value.
**Phase:** 3.

### P5 - Verification fabric (the trust layer)
**Problem:** F4 (self-trust). The corpus is only as good as the check on what
enters it.
**Change:** Implement the 0.10 run-time verify hook as a reusable pass: extract
load-bearing claims (numbers, named entities, dates) and ground each against its
source receipt. Deterministic checks own exact structural facts such as number
and span presence; configured model judges own semantic support, with Python
aggregating and enforcing the verdict. No model self-certifies the artifact it
just wrote. Emit `_verify.json` sidecars;
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
- verify + field-model refinement → inside `synthesize` / `resynthesize`,
- the assess/critique step → as a future extension of the existing `audit`
  surface.
So "more agentic" shows up in the tools people already use, with no new command.
**Why:** the core capture → analyze → synthesize flow self-corrects; the surface
stays the same size. The 2026 "loop engineering" framing makes the boundary
crisp: distill is the loopable primitive + persistent state layer (idempotent,
convergent, verify-gated, report-emitting); the loop *runner* is the layer above
(cron, an agent harness, OpenSteward) and stays out of this repo.
**Phase:** 4 - and only the parts that earn their keep; the goal-file + `discover`
already cover the common case.

## Phased build order (each phase shippable, dependency-ordered)

- **Phase 1 - Adaptive quality (shipped foundation):**
  P1 `CorpusIntent` + P2 adaptive lens + the first P3 deeper-synthesis prompt.
  The next revision treats that output as a field model and makes novel theses
  optional.
- **Phase 2 - Trust & resilience:** P5 verify fabric + P6 dedup/determinism/cache
  + P7 robustness. Makes the corpus trustworthy and runs survivable.
- **Phase 3 - Research-desk baseline:** representative mature, fast-moving, and
  contested-field fixtures for portfolio selection, source contribution,
  disagreement, meaningful change, reading paths, and stopping.
- **Phase 4 - Bounded reconciliation:** P4 control pattern inside discovery and
  synthesis only after the research-desk fixtures show that another pass adds
  material value.
- **Phase 5 - Fold earned behavior into existing commands:** discovery planning
  inside `discover`, field-model refinement inside `synthesize`/`resynthesize`,
  and bounded next actions inside `audit`. No new command unless an existing
  owner cannot express the proven workflow.

## Invariant compliance (must not break the charter)

- **Pure-Markdown corpus / provenance-first:** outward search ingests receipts; no
  prose-only external claims. Lenses change *sections*, never *fabrication rules*.
- **No cheap mode:** lenses and loops reuse calibrated prompts; new prompts
  (thesis, critic, lens variants) are `prompt_id`-versioned and enter the golden
  eval gate. Adaptive lens is not "shorter/cheaper," it's "right-shaped."
- **Judgment then rule for semantic verification:** P5 uses deterministic
  checks for structural facts and separate model verdicts for semantic support;
  Python owns aggregation and the write gate.
- **Calibration debt:** each new lens is calibration surface; cap the lens set
  (≈5) and gate additions on `distill eval`, mirroring the source-adapter cap.
- **Termination & budget:** every loop is iteration- and budget-bounded and
  idempotent at steady state.

## What "exceptional" measures (success criteria)

- A research topic produces zero pre-sales sections; analysis preserves the
  source's actual contribution and matches intent. (P2)
- Synthesis distinguishes established, contested, scope-dependent, emerging,
  unsupported, and unknown findings; it emits a novel thesis only when the
  evidence warrants one. (P3)
- Every load-bearing number in a synthesis is grounded to a receipt or flagged.
  (P5)
- Discovery explains why selected sources belong, avoids redundant spend, and
  records expected versus realized contribution. (P4/P6)
- A refresh distinguishes meaningful change from new-document volume. (P4)
- Re-running on an unchanged evidence set is a near-free no-op. (P4/P6)
- A provider outage degrades to local or a clean message, never a traceback, and
  resumes. (P7)
- A bounded recipe takes an intent from empty to a trustworthy, navigable,
  maintained evidence portfolio and reports honestly when important gaps
  remain. (P8)

## QA findings index

F1-F7 above are tracked as the motivating defects. The quick wins already isolated
and ready to implement independently of the big plan: **P7's error+fallback fix**
(F6) and **P2's lens swap** (F1) are the two highest-leverage, lowest-risk changes.
