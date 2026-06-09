# Agentic deep synthesis — distill as "agentic IaC" for a corpus

Status: design / RFC. Not yet built. This is the plan for turning distill's
one-shot synthesis into an agentic loop that produces PhD-grade analysis on its
own — no human hand-running the deep pass.

Related: [`invariants.md`](../invariants.md), [`architecture.md`](../architecture.md),
[`../../ROADMAP.md`](../../ROADMAP.md) (0.10 verify hook, `distill ask`,
self-maintaining audit, shared LLM cache).

## The ask

Today the flow is: ingest papers + videos → per-item `_Insights.md` → two-pass
synthesis (`claims.jsonl` → one synthesis doc). The synthesis is already
PhD-*shaped* (cross-source findings, named disagreements, comparison matrix,
"what no single source says", soft spots). But it has three honest gaps versus
what a researcher actually does:

1. **No top rung.** The ladder stops at "what no single source says." There's no
   dedicated **thesis / white-space** layer: the defensible novel position, the
   genuinely unoccupied space, falsifiable hypotheses. That rung is the whole
   point of serious synthesis.
2. **Corpus-closed and single-shot.** Synthesis sees the pile once and never goes
   back for more. A researcher iterates: draft → find the weakest claim /
   unresolved disagreement / thin spot → *go get more sources* → re-ground →
   redraft.
3. **No verification gate.** Numbers flow source → insight → synthesis with no
   grounding check against the receipt.

The requirement: **distill must close these gaps agentically, on its own.** Not a
manual pass. The mental model the user named is *agentic IaC* — and it is exactly
the right frame.

## The IaC mental model

Infrastructure-as-Code is declarative + idempotent + a reconciliation loop:
*desired state vs. actual state → plan the diff → apply → converge → re-running a
converged system is a no-op.* Map that onto synthesis:

| IaC concept | Deep-synthesis equivalent |
|---|---|
| Desired state | The goal-file + a quality bar: "a defensible, verified, gap-closed thesis on this topic." |
| Actual state | The current corpus + current synthesis + grounding status of each claim. |
| Plan (diff) | The critic pass output: ungrounded claims, unresolved disagreements, thin coverage, unverified novelty. |
| Apply | Verify-inward, discover-outward (receipted), reference-chase, re-synthesize. |
| Converge / no-op | No new high-value sources, all load-bearing claims grounded, thesis stable across an iteration. |

This frame also tells us what "done" means and guarantees termination — both of
which a one-shot pipeline lacks.

## The depth ladder (the desired-state schema)

Four rungs, each a real artifact with provenance. Two exist, one is hidden, one
is new.

1. **Facts** — `claims.jsonl` (exists). Atomic, role-tagged, grounded claims with
   dataset/metric and S-P-O triples. Today it's a hidden intermediate; promote it
   to a first-class, inspectable rung.
2. **Patterns** — cross-source clusters, comparison matrix, methodological
   patterns & shared blind spots (exists, inside synthesis).
3. **Insights** — second-order: what no single source says, named disagreements,
   soft spots (exists, inside synthesis).
4. **Thesis / white space** — NEW. The defensible novel position, the unoccupied
   space, falsifiable hypotheses, "if the corpus is right, then X follows." Each
   thesis claim must cite the rungs below it and carry a grounding status.

## The agentic reconciliation loop (the apply engine)

```
load goal + corpus
  │
  ▼
┌─[1] SYNTHESIZE (draft) ──────────────────────────────────┐
│  run two-pass synthesis → ladder incl. draft thesis      │
└──────────────────────────────────────────────────────────┘
  │
  ▼
┌─[2] CRITIC / ASSESS (the "plan") ────────────────────────┐
│  emit a structured action plan:                          │
│   • load-bearing claims with no receipt grounding        │
│   • unresolved disagreements                             │
│   • thin / single-source findings                        │
│   • thesis/white-space claims needing an external check  │
└──────────────────────────────────────────────────────────┘
  │
  ▼
┌─[3] ACT (the "apply") ───────────────────────────────────┐
│  • verify-inward: grep/regex + small-local-model check    │
│      each load-bearing number/name against its receipt    │
│  • discover-outward: turn each gap + novelty-check into a  │
│      `discover` query; INGEST RESULTS AS RECEIPTED        │
│      ARTIFACTS (dedup against existing corpus)            │
│  • reference-chase: pull strongest citations out of the   │
│      ingested papers as new candidates                   │
└──────────────────────────────────────────────────────────┘
  │
  ▼
┌─[4] RE-SYNTHESIZE ───────────────────────────────────────┐
│  fold new receipts + verification results back in        │
└──────────────────────────────────────────────────────────┘
  │
  ▼
[5] CONVERGE? ── no ──► back to [2]
  │ yes
  ▼
write ladder artifacts + a run ledger (what it ingested, verified, changed)
```

**Convergence (any of):** gap-driven discover returns nothing above the rigor
threshold; every load-bearing claim is grounded; the thesis is unchanged across
an iteration; OR a hard cap is hit (max iterations, budget ceiling). This is the
IaC "no changes" steady state.

## Invariant compliance — the tension and how it's resolved

distill's charter is the *verifiable corpus*: synthesize only the receipts,
anti-hallucination, no free-floating external facts. "Do more searches during
synthesis" must not violate that. How each step stays in-charter:

- **Pure corpus / provenance-first.** Discover-outward never writes web claims
  into prose. It ingests sources as real artifacts (standard frontmatter +
  `ProvenanceFields`) *before* they can inform synthesis. The thesis cites only
  receipts. (User decision: receipted-outward + inward-verify.)
- **No LLM as verifier-of-record.** Verify-inward is grep/regex first, small
  local model second — the elaboration/helper role, never the decision role.
  Matches the roadmap's verify-hook design and the alias-resolution stance.
- **No cheap mode.** The loop reuses the existing calibrated analysis/synthesis
  prompts. Only the critic and thesis prompts are new, and they enter the golden
  eval gate like any other prompt (`prompt_id`-versioned).
- **Cost discipline.** The loop is budget-bounded (per-run ceiling — generalizes
  the user's "$3" instinct, and is already a 0.10 guardrail item). Caching of LLM
  intermediates (claims, critiques, re-synth) by content hash via the planned
  `distill/llm/cache.py` makes re-synthesis cheap.
- **Termination guaranteed.** Hard caps on iterations + budget + a gap threshold;
  idempotent on a converged corpus.

## This is the capstone that unifies four roadmap items

Deep synthesis is not a new direction — it's the integration of pieces already on
the roadmap into one loop:

- **0.10 run-time verify hook** (claim grounding) → the verify-inward step.
- **gap-driven `discover`** (shipped) → the discover-outward step.
- **`distill ask` output→input loop** (0.10) → the thesis/answer is filed back as
  a receipted artifact, gated on the verify hook (exactly the existing safety
  argument).
- **self-maintaining `audit`** (next) → the critic/assess step is an audit scoped
  to one synthesis.
- **shared LLM cache** (beyond-1.0) → makes the loop affordable.

Framing for the roadmap: this is the milestone that turns distill from a
*pipeline* into an agentic *steward of its own corpus* — the same gather → act →
verify loop Anthropic's Agent SDK formalizes, applied to research synthesis. It
deserves to be named as the thing those four items add up to, not scattered.

## Surface

- **`distill deepen <topic>`** — run the reconciliation loop to convergence.
  Flags: `--max-iterations`, `--budget <usd>`, `--rigor`, `--style`,
  `--dry-run` (show the plan/diff without applying — the IaC `plan` verb),
  `--no-discover` (verify + re-synthesize only, no new ingest).
- **Artifacts**: `<topic>_Facts.md` (or keep `claims.jsonl` + a rendered view),
  `<topic>_Synthesis.md` (patterns + insights, today's output), and a new
  `<topic>_Thesis.md` (the top rung). Plus a `<topic>_Deepen_Ledger.md` run
  ledger: queries issued, sources ingested, claims verified/flagged, thesis
  deltas per iteration. The ledger is the IaC "apply log."
- **MCP parity**: a `deepen` tool and a `thesis(topic)` read tool.

## Build plan (phased, each shippable)

1. **Thesis rung (prompt-only).** Add a thesis/white-space synthesis prompt over
   the existing claim set. New `prompt_id`, golden-eval fixture. No loop yet —
   immediately upgrades output quality.
2. **Verify-inward.** Implement the claim-grounding check (grep/regex + optional
   local model) as a standalone pass writing a `_verify.json` sidecar. This is
   the 0.10 hook; deep-synthesis consumes it.
3. **Critic / plan.** A pass that reads synthesis + verify sidecar and emits a
   structured action plan. Add `--dry-run` to print it.
4. **The loop.** Wire critic → discover-outward (receipted) + reference-chase →
   re-synthesize, with convergence + budget caps and the run ledger.
5. **Caching + idempotence.** `distill/llm/cache.py`; make a converged re-run a
   near-free no-op.

## Open questions (for refinement)

- Does the thesis rung live in its own `_Thesis.md`, or as the capstone section of
  the existing synthesis? (Leaning: own file, so it can be regenerated/cited
  independently.)
- Reference-chasing needs reference extraction from paper PDFs — is that in scope
  for v1 or deferred? (Leaning: defer; gap-driven discover covers most of it.)
- Convergence on the thesis: "unchanged across an iteration" needs a stability
  metric. Semantic diff of thesis claims, or claim-set equality? (Leaning:
  claim-set equality on the thesis claims' grounding handles.)
- Budget arbitration when discover-outward wants to ingest more than the ceiling
  allows: rank by expected gap-closure and take the top-k within budget.

## QA notes from the dogfood run that motivated this

Found while running `distill discover` on the `agentic-harness` corpus:

- **discover re-suggests already-ingested items** (no dedup of the rerank
  shortlist against the existing corpus). The reconciliation loop's idempotence
  requirement fixes this directly — convergence *means* "no new sources," which
  requires corpus-aware dedup.
- **Non-deterministic plan size and query generation** across identical runs
  (preview sized to 12 then 10; query sets differ run-to-run). Agentic IaC needs
  reproducible plans; seed/cache the query-generation + rerank.
- **`steward` topic is polluted** with enterprise *data-stewardship* content
  (Atlan/Aiven/Neo4j "context layer") — the bare word "steward" pulled the wrong
  field. A rigor/relevance floor on discover queries would have caught it.
