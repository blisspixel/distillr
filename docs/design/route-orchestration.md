# Route orchestration: using several validated routes together

> Status: design charter. Extends [`recurring-profiles-cost-routing.md`](recurring-profiles-cost-routing.md),
> which defines the *route layer* (validate a single CLI/local/cloud route, prove
> its no-metered status, and pick the cheapest one that clears `distill eval`).
> This doc adds the *orchestration layer* on top: how to use several already
> validated routes *together* on one workload. It runs inside
> [`agentic-balance.md`](agentic-balance.md) (rule vs judgment) and
> [`model-judgment-vs-brittle-fallbacks.md`](model-judgment-vs-brittle-fallbacks.md)
> (no deterministic proxy for a semantic call), and reuses the bounded
> external-worker adapter contract from the cost-routing doc verbatim.

## The gap this closes

The route layer answers "which single route should serve this workload." That is
already better than round robin: a route is used only after adapter doctor proves
a session/plan credential (not an API key), `distill eval` shows its output
clears the workload bar, and the usage ledger plus `quota_stop` metadata keep a
rate-limited or exhausted route out of the live pool.

But picking one route throws away the real advantage of holding several plan
quotas and a local GPU at once: using them *together*. A user who has a Claude
plan, a Codex plan, a Grok plan, and a local 4090 should be able to get output
that is better than any one of those routes alone, not just "whichever single
route eval liked best." That is the orchestration layer.

The unit of selection changes accordingly. The route layer selects a **route**;
the orchestration layer selects a **strategy**, which is a small rule-owned plan
over one or more routes plus a model-judged verifier. `distill eval` then scores
`(workload, strategy)` pairs on **cost per accepted change**, and recommends the
cheapest strategy that clears the bar, not merely the cheapest route.

## Research signals (2026)

The strategy choices below are grounded in current multi-agent and LLM-judge
research, not intuition. The findings line up with the charter and sharpen a few
decisions.

- **Self-refine does not work intra-model; external, different-family feedback
  does.** LLMs cannot reliably self-correct reasoning without external feedback,
  and self-correction can flip a correct answer to an incorrect one ([Huang et
  al. 2024, "LLMs Cannot Self-Correct Reasoning Yet"](https://arxiv.org/pdf/2310.01798)).
  The sharpest result for orchestration: a model can correct an error presented
  externally but fails to correct the identical error in its own output. This is
  the evidence base for maker-checker and critic-refine being **cross-family by
  mandate** (S3/S4): the checker must be a different model than the maker, and a
  single model looping on itself is the pattern the literature says fails.
- **Self-preference bias is large, so a judge must not grade its own family.**
  Evaluators overrate their own outputs (roughly -38% to +90% on ArenaHard), and
  larger models show stronger self-preference ([Do LLM Evaluators Prefer
  Themselves for a Reason? 2025](https://arxiv.org/pdf/2504.03846)). That is the
  quantitative basis for discipline 2.
- **Pairwise is reliable but position-biased; debias by averaging both orders.**
  Position bias is pervasive and pairwise comparison is especially exposed
  ([Judging the Judges, 2024](https://arxiv.org/abs/2406.07791)). distillr's
  pairwise judge already runs both orderings and averages (the recommended
  mitigation); the coarse faithfulness floor is absolute and anchor-free, the one
  mode without position bias.
- **Non-transitivity (circular preferences) is real.** Pairwise judging produces
  circular chains where A beats B, B beats C, and C beats A. The v1 sequential
  tournament in ``select_best`` accepts this for a small candidate pool (its
  result can depend on order under non-transitivity, documented in the code); a
  panel-of-judges jury or a round-robin aggregation is the escalation for a
  larger pool or a high-stakes pick, and a jury of diverse models is the emerging
  answer to single-judge bias.
- **Reject majority vote and consensus.** "Sycophancy cascade" is the documented
  failure where agents converge on the majority position even when it is wrong,
  manufacturing false consensus. Ensemble selection here is a receipt-grounded
  faithfulness veto plus pairwise, never a vote or a consensus-of-agreement,
  which would amplify a shared error instead of catching it.
- **Bound the orchestrator's context.** Orchestrators that accumulate every
  worker's full output overrun the context window at four or more workers.
  Ensemble fan-out carries the receipts and the per-candidate verdicts, not all N
  raw payloads, consistent with distillr's paths-not-payloads discipline.
- **The CLI substrate supports the contract.** Claude Code headless
  (`--print --output-format json`) returns `total_cost_usd` and a per-model cost
  breakdown and supports `--json-schema` structured output; Codex has a
  non-interactive mode; Gemini CLI has headless JSON but no custom output schema
  yet ([Claude Code headless](https://code.claude.com/docs/en/headless),
  [Gemini CLI headless](https://geminicli.com/docs/cli/headless/)). This is why
  the adapter contract gates on machine-readable output plus a usage signal, and
  why Gemini stays blocked on structured-output enforcement.

## The strategies

Four shapes, smallest first. Each names what it is, when it wins, its
rule-owned vs model-owned split, and its cost shape. All of them obey the
disciplines in the next section without exception.

### S1. Single route (the current default)

One route serves the workload; the receipt-grounded verifier accepts or rejects.
This is the baseline and stays the default for cheap, well-calibrated work
(candidate triage, classification, bulk draft summaries) where a strong local or
plan-quota route already clears the bar on its own.

- Rule-owned: route selection (the eval recommendation), dispatch, the
  accept/reject gate.
- Model-owned: the analysis itself, and the faithfulness verdict.
- Cost: 1x route usage.

### S2. Ensemble, best-of-N (your "fan out the same thing to all")

Dispatch the same task to every live route. Selection is two steps, each in the
judging mode the evidence supports (discipline 6). First, a coarse,
source-anchored faithfulness check (faithful / minor / unfaithful, the reliable
absolute mode, used only as a floor) drops any candidate unfaithful to the
receipts. Then, among the survivors, a cross-family pairwise judge (the reliable
comparative mode) picks the winner, or a synthesis step merges the best parts
into one output that is itself re-verified. There is no per-candidate quality
score and no argmax over scores.

- Wins on: bursty, high-judgment, hard-to-get-right work where the user holds
  free quota on several plans and the variance between routes is real
  (synthesis planning, a contested-concept read, a one-shot brief). Best-of-N
  raises the ceiling; a single weak draft no longer caps quality.
- Rule-owned: fan-out dispatch, collecting the N scratch manifests, the
  faithfulness-veto filter, the pairwise-tournament bookkeeping (or the synthesis
  merge plumbing), the budget stop.
- Model-owned: each candidate, the coarse faithfulness verdict per candidate, and
  the pairwise comparisons that order the faithful survivors.
- Cost: N x route usage. Only earns its place where the acceptance-rate or
  quality lift pays for the quota multiply (measured, not assumed).

### S3. Maker-checker (your "give that to the next and ask to check")

One route drafts; a **different-family** route verifies the draft against the
receipts and proposes concrete refinements; the maker (or a third route) applies
them. The checker's output is itself receipt-grounded, never a "looks good."

- Wins on: the highest-quality single-pass shape. A cheap or local maker plus a
  stronger plan-quota checker beats either alone, at far less quota than a full
  ensemble. This is the workhorse for reviewer passes, synthesis, and
  contradiction interpretation.
- Rule-owned: the two-stage pipeline, the diff between draft and refined output,
  the accept gate, the cross-family constraint enforcement.
- Model-owned: the draft, the critique, and the revision.
- Cost: about 2x route usage (maker + checker), often split cheap-maker plus
  one stronger-checker call.

### S4. Critic-refine (your "is this right, give me refinements", iterated)

Maker-checker run as a bounded loop: draft, critique, revise, re-verify, stop
when the receipt-grounded verifier turns green or the round/spend ceiling is hit.
The maker and critic stay cross-family across rounds.

- Wins on: a small number of genuinely hard items where one refinement pass is
  not enough and the marginal quota is worth it.
- Rule-owned: the loop, the max-rounds and max-spend bound, the stop condition
  (verifier green or budget), the per-round ledger.
- Model-owned: each draft, critique, and revision.
- Cost: bounded by the round and spend ceiling. Convergence is the verifier's
  call, never the model declaring itself done.

## The non-negotiable disciplines

These are what keep the patterns from becoming expensive slop. They come
straight from the existing charter and adapter contract.

1. **The verifier is receipt-grounded and model-judged, never self-declared.**
   Every accept decision (which ensemble candidate wins, whether a refinement is
   an improvement, whether the loop is done) is a model judgment grounded against
   the source receipts, the same faithfulness shape `distill eval` and the
   verify hook already use. A route saying "this is correct" is not a verifier
   (invariant #8).
2. **Judges never grade their own family.** The eval conflict-of-interest rule
   applies to orchestration: an ensemble judge, a maker-checker checker, and a
   critic must be a different model family than the candidate they assess. A
   model grading its own (or its family's) output is not an independent check.
   When no cross-family route is available, the strategy degrades to single-route
   plus the structural verifier and says so, rather than faking an independent
   judge.
3. **Live quota validation and eviction, not blind dispatch.** Fan-out dispatches
   only to routes the adapter doctor currently proves are authed and in-quota; a
   `quota_stop` or rate-limit signal evicts a route from the live pool for the
   rest of the run. A strategy adapts to the pool it actually has (a three-plan
   user gets three-way ensemble; a one-plan user gets maker-checker against
   local; a no-plan user gets single-route local), and labels the degradation.
4. **Rule owns the plan, the model owns the judgment.** Dispatch, collection,
   selection arithmetic, cross-family enforcement, budget stops, and quota
   eviction are deterministic. Which output is best, whether a claim is faithful,
   and what to refine are model calls. No keyword or length proxy stands in for
   any of those.
5. **No bypass of verify, ledger, or corpus invariants.** Adapters still write
   only scratch manifests; Distill still does the verification, the usage
   ledger, and the final corpus write. An orchestration strategy is a plan over
   adapter calls, not a new write path.
6. **Judge in the mode the evidence supports.** Grounding is a coarse,
   source-anchored faithfulness verdict (faithful / minor / unfaithful) used as a
   veto floor, the absolute mode where model judging is reliable. Ranking among
   the faithful (which ensemble candidate wins, whether a refinement is an
   improvement) is pairwise comparison, the reliable comparative mode. No strategy
   ranks candidates or refinements by a fine-grained absolute quality score: that
   is the brittle proxy wearing a model's clothing (the eval-gate case study in
   [`model-judgment-vs-brittle-fallbacks.md`](model-judgment-vs-brittle-fallbacks.md)),
   relocated from a regex onto the model. Pairwise for ranking, coarse absolute
   for grounding, never a quality number.

## The eval contract

`distill eval` already compares routes per workload on cost per accepted change.
The extension is that a **strategy** is an eval subject too:

- A fixture run produces, per `(workload, strategy)`: attempts, accepted
  outputs, rejected/quarantined outputs, verifier failures, elapsed time, usage
  per route, and total cost per accepted change. An output is *accepted* by the
  same gate the rest of distillr uses: the coarse source-anchored faithfulness
  veto plus pairwise at-par against the reference, both model-judged, never a
  deterministic composite score. Cost and counts are ground-truth ledger
  arithmetic over those model-judged acceptances.
- The recommendation per workload is the cheapest strategy whose accepted output
  clears the quality bar. S2/S3/S4 only win where their accept-rate or quality
  lift outweighs their quota multiply; otherwise S1 stays.
- The comparison is honest about the pool: a strategy that needs three live
  routes is only recommended for users who have them, and the eval records what
  pool each result assumed.

This is the same "measured, not assumed" gate the rest of the routing work uses.
Fan-out is not better because it is more agentic; it is better only when the
ledger says the accepted work got cheaper or better.

## Buildable now, without waiting on vendor support statements

The orchestration layer does not depend on any plan-quota vendor statement. It is
a plan over the existing scratch-manifest adapter runner, so it can be built and
tested today against local Ollama plus mock routes:

- the strategy interface (S1-S4) over the existing adapter runner;
- the cross-family judge wiring (reuse the eval faithfulness judge and its
  family-exclusion rule);
- the budget, round, and quota-eviction rules;
- the eval harness extension that scores `(workload, strategy)` on cost per
  accepted change.

Real plan-quota routes plug into the same interface the moment they graduate
through adapter doctor. So this is the non-blocked, higher-value half of 0.19:
the route layer waits on vendor policy, but the strategy layer and its eval can
land and be proven now with local and mock routes.

## Build order

1. **Strategy interface + S1.** Formalize a `RouteStrategy` over the adapter
   runner that returns a verified, ledgered result; wire single-route through it
   so it is the trivial strategy, not a special case.
2. **S3 maker-checker.** The highest value per unit of work; cross-family
   checker against the receipts, with the family-exclusion rule enforced.
3. **S2 ensemble.** Fan-out + cross-family judge selection (and an optional
   synthesis merge that is itself re-verified).
4. **S4 critic-refine.** S3 in a bounded loop with a verifier stop and spend
   ceiling.
5. **Eval extension.** Score `(workload, strategy)` on cost per accepted change;
   recommend the cheapest clearing strategy per workload, pool-aware.
6. **Wiring.** Let a profile or workload declare a preferred strategy, defaulting
   to the eval recommendation; everything still flows through verify, ledger, and
   the corpus write.

## Non-goals

- No strategy that escalates to a metered API route under `no-metered`. Cost mode
  still gates the pool; orchestration only rearranges no-metered routes unless
  the user selected `paid-ok`.
- No fan-out or refinement loop whose quota multiply is not justified by a
  measured accept-rate or quality lift. The default stays S1 until eval says
  otherwise.
- No self-grading. A strategy with no cross-family route available degrades to
  single-route plus the structural verifier and labels it, rather than letting a
  model judge its own family.
- No majority vote or consensus-of-agreement selection. Agreement across routes
  (especially same-family routes) is the sycophancy-cascade failure mode, not a
  signal of correctness; selection is the receipt-grounded faithfulness veto plus
  pairwise, never a vote.
- No new corpus write path. Strategies plan adapter calls; Distill still verifies,
  ledgers, and writes.

## Where this lands

A 0.19.x extension, sequenced after the read-only adapter prototypes (0.19.4) and
the cross-route eval (0.19.3), since both the adapter runner and the eval
comparison are its substrate. The strategy interface and S1/S3 plus their eval
can be built and proven against local and mock routes before any plan-quota
vendor statement is current.
