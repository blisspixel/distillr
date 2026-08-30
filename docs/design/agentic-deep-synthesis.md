# Bounded field-model reconciliation

Status: design / RFC, partially built. This document defines how Distillr can
turn one-shot synthesis into a bounded research loop without confusing
agentic activity with product value.

Related: [`research-desk-doctrine.md`](research-desk-doctrine.md),
[`../invariants.md`](../invariants.md),
[`architecture.md`](../architecture.md), and
[`../../ROADMAP.md`](../../ROADMAP.md).

## The product problem

Today the core flow is:

```text
ingest sources
-> source-sensitive analysis
-> atomic claims
-> corpus synthesis
```

That flow already produces cross-source findings, disagreements, a comparison
matrix, second-order insights, soft spots, and an optional thesis and white-space
section. It still has three important limits:

1. Synthesis sees the available corpus once. It does not identify which
   additional evidence would most improve the field model.
2. Source acquisition and synthesis are not yet one bounded reconciliation
   process. The user must decide when to discover, ingest, verify, and
   resynthesize again.
3. Claim evidence can be structurally present without being sufficient for the
   exact proposition, scope, or time period used by the synthesis.

The goal is not to make the pipeline perform more steps. The goal is to reduce
decision-relevant uncertainty with a small, trustworthy evidence portfolio.

## The reconciliation model

The useful part of the Infrastructure-as-Code analogy is declarative intent,
inspectable plans, bounded application, and idempotent reruns. It does not imply
that research has one objectively complete end state.

| Reconciliation concept | Research-desk equivalent |
|---|---|
| Operator intent | Goal, audience, rigor, boundaries, freshness, cost, and time |
| Actual state | Current receipts, claims, lineage, field model, and known gaps |
| Assessment | Model judgments about support, disagreement, importance, and uncertainty |
| Plan | Exact proposed sources or verification actions with expected contribution |
| Apply | Approved ingest, verification, reference chase, and resynthesis |
| Stop | An honest sufficiency state or a deterministic resource boundary |

The desired state is not "produce a novel thesis." It is "make the field model
sufficient for this intent, or explain precisely why it is not."

## The compiled field model

Four layers remain useful when each is inspectable and provenance-preserving:

1. **Evidence.** Captured source material with producer provenance and stable
   evidence locations.
2. **Claims.** Atomic source and derived claims with role, scope, time, lineage,
   and grounding state.
3. **Field model.** Established, contested, scope-dependent, emerging,
   unsupported, and unknown conclusions, plus methodological and historical
   relationships.
4. **Implications.** Practical consequences, reading guidance, and testable
   hypotheses when the evidence warrants them.

The current synthesis includes a thesis and white-space section. Treat that as
an optional implications surface. Requiring novelty on every run creates
novelty theater and makes an honest "the evidence is insufficient" result look
like failure.

## The bounded research loop

```text
load intent + current corpus
-> compile or refresh the field model
-> assess important uncertainty
-> propose exact evidence actions
-> preview cost, scope, and expected contribution
-> obtain approval when required
-> ingest or verify through normal receipt-producing paths
-> assess realized contribution
-> recompile the field model
-> classify meaningful change
-> stop or propose one bounded follow-up pass
```

The user does not need to see every internal assessment. They do need an
inspectable plan before material acquisition, an accurate run ledger afterward,
and a clear explanation of what changed.

## Assessment and action planning

The assessment pass should return per-criterion semantic verdicts, not a single
quality score. At minimum it should identify:

- load-bearing conclusions with weak or unresolved evidence;
- important inquiries with missing source roles or methods;
- apparent contradictions that may be explained by scope, method, population,
  benchmark, definition, assumptions, geography, or time;
- genuine disagreements that remain under comparable conditions;
- conclusions supported by derivative rather than independent evidence;
- sources that appear redundant or off-goal;
- evidence that could materially strengthen, weaken, qualify, reframe, or
  resolve the field model;
- whether another pass is likely to be worth its cost.

The resulting plan must contain exact candidate identities, expected
contributions, cost and time estimates, approval class, write scope,
verification condition, and stop condition. Python validates and enforces
those structural facts. A model judges the research meaning.

## Verification

Verification has two distinct jobs:

### Structural verification

Deterministic checks answer questions such as:

- Does the source artifact exist?
- Does the claim resolve to the current source generation?
- Does the evidence handle point inside the admitted receipt?
- Is the producer origin source, derived, or unknown?
- Did the approved action stay inside its budget and write scope?

### Semantic verification

Model judgment answers questions such as:

- Does the cited passage support this exact proposition?
- Is the scope or time qualifier preserved?
- Are two sources genuinely independent?
- Is the disagreement real or explained by different methods?
- Would the proposed evidence materially affect the field model?

For consequential publication or irreversible action, the model returns
per-criterion verdicts with evidence handles. Python aggregates those verdicts,
records them, and applies the policy gate. Keyword search can locate candidate
passages, but it cannot serve as the semantic verifier of record.

## Discovery as evidence-portfolio improvement

Discover-outward never injects free-floating web claims into synthesis. It
produces candidates, and approved candidates enter through normal receipted
ingest before they may affect the field model.

Candidate selection should consider:

- inquiry fit and decision relevance;
- expected distinct contribution;
- source role and primary-source proximity;
- method, viewpoint, and temporal diversity;
- likely independence or derivation;
- redundancy with admitted evidence;
- expected acquisition and analysis cost.

The plan should group candidates as essential core, gap-closing additions,
perspective or method breadth, and peripheral or redundant. These remain model
judgments with rationale, not numeric cutoffs over popularity or citation
count.

After ingest, Distillr should compare expected and realized contribution. A
source may materially change the field model, fill a gap, add independent
support, clarify scope, explain a contradiction, add useful context, prove
redundant, prove off-goal, or remain unevaluable.

## Meaningful change

The loop converges on understanding for the current intent, not on a stable
document hash. Every pass should classify field-model changes as:

- `new`;
- `strengthened`;
- `weakened`;
- `qualified`;
- `reframed`;
- `resolved`;
- `unchanged`.

Each material change names the affected inquiry and resolves to current
evidence. A new source count is operational metadata, not proof that the field
changed.

## Honest stopping

Research does not have universal completion. The assessment should choose an
honest state relative to current intent:

- `sufficient_for_current_intent`;
- `next_pass_likely_valuable`;
- `important_gap_no_accessible_evidence`;
- `source_access_blocked`;
- `budget_limited`;
- `evidence_too_weak_for_conclusion`;
- `operator_decision_required`.

A model judges which semantic state applies and explains why. Python enforces:

- maximum follow-up passes;
- time and cost ceilings;
- allowed tools and source boundaries;
- exact approved action ids;
- duplicate-source refusal;
- verifier and approval requirements.

Reaching a hard cap is a bounded stop, not evidence of research sufficiency.
Finding no high-value accessible source can justify a no-op, but only with the
unresolved uncertainty preserved.

## Product surface

This should strengthen existing workflows rather than add an agent platform or
a large new command surface:

- `discover` owns inquiry-aware candidate planning and gap filling;
- `synthesize` and `resynthesize` own field-model compilation;
- `verify` owns claim and evidence assessment;
- `audit` owns structural health and can expose semantic assessment results;
- profiles own scheduled, selective refresh within an approved intent.

A bounded deepen or verify flag may compose these steps. The loop runner remains
external. Every autonomous action must still resolve to a normal Distill
command, receipt, action id, and run record.

## Build plan

Each slice is independently useful and must clear research-desk evaluation
fixtures before becoming a default:

1. **Research-desk baseline.** Create expert-authored fixtures for source
   selection, redundancy, disagreement causes, field-model quality, meaningful
   change, and honest stopping. Measure current behavior before expanding it.
2. **Current evidence.** Complete claim-generation currentness, derived-origin
   preservation, and inspectable evidence anchors for load-bearing claims.
3. **Research program.** Derive revisable lines of inquiry from operator intent,
   without allowing derived state to rewrite the goal file.
4. **Contribution envelope.** Give every supported source type a common,
   provenance-preserving handoff into one field model while keeping
   source-sensitive analysis.
5. **Portfolio planning.** Record candidate rationale and expected contribution,
   then compare it with realized contribution after ingest.
6. **Field-model compiler.** Replace section-first synthesis planning with an
   inquiry-aware view of findings, disagreements, lineage, gaps, history, and
   implications.
7. **Meaningful refresh.** Explain what changed in the field model and skip
   low-value reprocessing for stable inquiries.
8. **Bounded reconciliation.** Compose assessment, approved actions,
   verification, resynthesis, and honest stopping with a run ledger.
9. **Caching and idempotence.** Reuse content-addressed intermediate judgments
   so a no-change rerun is inexpensive without hiding changed evidence.

## Open questions

- Which current artifact should hold the research program without creating a
  second source of operator intent?
- What is the smallest contribution envelope that works across papers, talks,
  sites, repositories, feeds, podcasts, posts, and local files?
- Which evidence locations can be made exact now, and which must remain
  unknown-safe until a source adapter can preserve them?
- How should research-desk verdicts be calibrated across fields without
  pretending one universal rubric fits every domain?
- Which existing report surface can present reading paths and meaningful change
  before a new command is justified?

## Dogfood observations that motivated the loop

- Discovery has re-suggested already ingested items. Idempotence requires
  corpus-aware source identity and duplicate refusal.
- Identical runs have produced different plan sizes and query sets. Plans should
  remain reproducible or explicitly record the model and sampling conditions
  responsible for variation.
- Broad goal terms have admitted adjacent but irrelevant fields. Inquiry-aware
  source-fit judgment and operator-visible rationale should catch that before
  ingest.
- Direct-ingest source types do not all participate in the same synthesis path.
  The contribution envelope must eventually give the field model one explicit
  evidence boundary across every supported source type.
