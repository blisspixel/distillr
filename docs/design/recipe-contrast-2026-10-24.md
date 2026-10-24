# Offline recipe contrast, 2026-10-24

Status: identity and accounting only. This note does not establish that any
recipe answers better. Semantic trials stay under the `0.20.9` research
baseline. Production prompts and defaults are unchanged.

## Question this step answers

Can Distill schedule a small recipe comparison without letting two prompt
variants share one cached analysis, and without turning a missing judgment
into a pass?

## Reference

Harness² commit `1cfe254e8d25b15f37048c3730134686abe60335` is a reference for
separating a method from its executor and for binding a completed run to a
fingerprint. Distill does not import that repository. It does not copy
finals-only selection, and it does not open a network or disable a sandbox.

## Contract

`distill/eval/recipe_contrast.py` holds four hand-authored variants:

- `current-baseline`, the unchanged baseline, with empty section text
- `source-interpretation-qualification`
- `version-correction-check`
- `explicit-composition`, which names both of the sections above

A `ResearchRecipe` has an id, component names, and section text. It has no
grader and no acceptance threshold. `recipe_digest(None)` equals the baseline
digest, so an eval that passes no recipe still hits the baseline cache.

The analysis cache key is `analysis-v3`. It includes the recipe digest and a
hash of the injected analyzer's module, qualname, and bytecode. A saved row
is reusable only when its `recipe_digest` matches. A missing or mismatched
manifest is recomputed. Errored analyses stay uncached, so a retry runs.
The existing atomic JSON writer is the only cache store.

`can_reuse` refuses a blank output, an unfinished stage, a digest mismatch,
and a missing required artifact. The general eval cache can still store a
successful empty string. The experiment ledger must pass that output through
`can_reuse` before treating it as done.

`contrast_identity` hashes the recipe, the prompt section, the runner, the
fixture id, and the source text. Rendered production prompt, runtime,
configuration, and evaluator version stay the word `unknown` when this
offline step does not have them.

`AttemptLedger` counts planned, completed, failed, cancelled, rejected, and
abstained rows. A cache hit and a retry are details on those rows. Answer
level abstention is the `abstained` state. It is a different event from an
experiment level `rejected` row.

`decide` returns only:

- `inconclusive` when any judgment is missing, or when the result would
  otherwise adopt a candidate
- `keep-baseline` when the candidate is rejected and a baseline result exists
- `reject-all` when the baseline and the candidate are both rejected

No return value selects a candidate.

## Fixture report

`tests/unit/eval/test_recipe_contrast.py` is the deterministic report.

The paper workload, one model, and an injected analyzer show that each of
the four recipes misses the cache on first use, and that a later run with
`recipe=None` is served from the baseline cache.

Four fixed sources go through the same analyzer: qualification extraction,
a two source correction, an unanswerable price question, and an answerable
battery size control on the same note. Mocked completions are checked for
required substrings. Swapping the recipe digest misses the cache. The recipe
section text is not written into the fixture source.

A raised analyzer error is a failed attempt and is not cached. The next call
runs again. Blank output, an interrupted stage, a missing artifact, and a
mismatched digest fail `can_reuse`.

## What this does not show

The report shows cache identity, ledger states, and the decision policy.
It does not show qualification retention, citation entailment, or a
transferable gain. No model was called for this step. No candidate edited a
grader. Held out semantic trials remain separately budgeted, after the
`0.20.9` baseline has expert review.
