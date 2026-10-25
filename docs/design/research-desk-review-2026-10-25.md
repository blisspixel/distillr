# Research-desk baseline review, 2026-10-25

Status: offline agent review and production evidence-selection characterization
for queued `0.20.9`. This is not human expert review, a calibrated model-judge
trial, production selective revision, or a release. The quality gate remains
closed and defaults remain unchanged. Work starts from
`51d0c187fd71b03a387f8ecdee3d61ea2d09ed46` on clean `main`.

## Scope and authority

The operator requested agentic continuation and independent subagent review,
without waiting for a human expert. The bounded outcome is a more credible
offline baseline: review authored answers against their frozen evidence, repair
misleading positive examples, and observe actual production paper selection.
No inference trial, model download, package installation, issue publication,
push, merge, security change, or release is part of this slice. The frozen
environment was already synchronized; `uv sync --frozen` changed no packages.

Distillr supplies evidence and detailed insights. Repository applicability and
deduplicated action proposals remain downstream responsibilities. No shared
corpus, portfolio orchestrator, new dependency, or evaluation platform is added.

## Production evidence-selection challenge

`tests/unit/eval/test_production_paper_selection.py` runs `analyze_paper` through
the real receipt builder, character-based token estimator, chunker, structural
selector, multipass orchestration, and prompt builders. Acquisition, provider
metadata and model transport are replaced. Model responses are inert text and
cannot establish research-answer quality. No artifact publication is exercised:
the full receipt is the document returned by `analyze_paper`.

The paper is wholly fixture-authored with identity `synthetic-selection-v1`
and locator `https://example.invalid/paper`. Its ratio/caveat sentences are
authored stress inputs, not additional Faros quotations or corroboration.
The original frozen Faros page and authored contrast remain in the existing
baseline. No current source was fetched for these tests.

| Challenge | Observed evidence boundary | Interpretation |
|---|---|---|
| Late caveat under `Erratum` or `Population Notes` | Full returned receipt retains it; none of the three narrow-context analysis prompts receives it | A structural heading match does not establish sufficient evidence selection |
| Same caveat under `Limitations` | Implications pass receives it; methods pass does not | Evidence is separated between passes; this alone does not prove final-answer failure |
| Repeated derivative recap sections inside one paper | Recaps can exhaust the methods selection budget before the primary result and its qualification | Within-paper order/budget failure; cross-source discovery and deduplication are not tested |
| Larger-context control | Same full receipt reaches single-pass analysis, including the late caveat | Broader context preserves access here; no claim of improved model quality |
| Adequate multipass capacity with a matched combined heading | Measurement and qualification both reach the evidence pass while a long irrelevant appendix keeps the document above the threshold | Multipass itself is not universally lossy; sufficiency depends on actual selection |
| Below, at, and above 80% of configured context | Real estimator selects single pass below the boundary and multipass at/above it | Confirms current routing mechanics, not runtime-tokenizer accuracy or an optimal threshold |

Every analysis pass has a structural heading match in the initial challenge,
so the production reranker is bypassed even when a rerank route is available.
The transport spy fails if that unexpected ranking call occurs. These tests
make an existing failure visible; their green status is not a passing semantic
baseline. Selection policy and the 80% threshold are not optimized here.

One additional configuration limitation was identified during review:
`paper.py` resolves context metadata for `analysis`, while single-pass transport
uses workload `site`; multipass transport uses `analysis`. Explicitly different
workload routes can therefore describe different models. The mocked metadata
in this challenge does not qualify that runtime boundary. It remains a bounded
follow-up to reproduce before changing routing behavior.

## Semantic review method

Independent agent inspection reads each source anchor, pool role, required
coverage set, authored candidate selection, and final prose. Review criteria
are source/claim fidelity, preservation of material qualification, visible
history and uncertainty, fair disagreement, and usefulness for the stated
question. A structural pass does not determine any semantic verdict.

The initial review is not blinded: reviewers can inspect authored expected
outcomes. There is no held-out calibration set, repeated sampling, or live
production answer. These limits preclude a calibrated quality claim.
An independent agent assessment must not be relabeled as human review. The
original `expert_review`, `judge_calibration`, and release-gate fields remain
honest about the evidence they actually represent.

## Agent review findings and fixture repairs

| Case or control IDs | Before review | Repair and agent verdict |
|---|---|---|
| `faros-full`, `faros-concise`, `faros-reordered` | Ratio, denominator, reported change, population and observational limit were faithful; final prose did not disclose the uncaptured full report | Add required authored `faros-report-not-captured` gap to all briefs. Adequate for the frozen takeaway-page question; full-report evidence remains unavailable |
| `probability-as-probability` | Actual synthetic probability stays probability; the ratio rewrite fails | Retained. Adequate metric contrast; not a real randomized trial |
| `mature-selection` | Adult estimate and pediatric omission were present, but applicability uncertainty was implicit | Add required authored `pediatric-applicability-unknown` qualification. Adequate for the limited synthetic question, without claiming no pediatric effect |
| `fast-material-change`, `fast-no-meaningful-change` | New score and history were distinct; no-change brief did not explain why the website batch was immaterial | Require an explicit authored no-score-change explanation for the latter. Adequate for the fixed synthetic corpus; no production refresh measured |
| `correction-narrowing`, `correction-withdrawal` | An old A=10 result appeared in present tense after replacement/withdrawal; hidden anchor roles did not repair reader-facing ambiguity | Use explicit `method-a-10-history` prose and role, exclude the old current-result anchor, retain B and unaffected calibration. Adequate historical distinction for the authored episode |
| All correction episodes | One source pool mixed narrowing, withdrawal, refusal and homepage events across variants | Give each variant only A, B and its applicable event. Cross-episode source selection now fails identity checks |
| `correction-zero-claim`, `correction-refused` | Positive briefs could drop B or unaffected calibration; zero-claim preservation was not explicit | Require both existing findings and calibration, plus a zero-new-claims explanation or refusal. Adequate non-retirement control; no new correction is inferred |

The independent reviewer identified these weaknesses before editing the
controls. The implementation adds 18 adversarial parametrized cases for
dropped limitations, distorted history, unavailable events and preservation of
current evidence. This is agent assessment of authored controls, not a
statistical estimate of research quality. Synthetic source metadata has capture
dates, not a complete publication/revision timeline; distinct event identities
and historical prose do not establish production provenance completeness.

## Exploratory blind agent check

After the repairs, a separate agent received 16 frozen evidence packets and
candidate answers with expected verdicts and control IDs withheld. It read only
the supplied packet and returned six per-criterion verdicts with source and
sentence evidence. The agent did not read the answer key or repository controls.
Only after its verdict file existed were IDs and reviewed expectations joined.

The result agrees on all 16 authored examples: eight acceptable candidates and
eight rejected candidates, with no inconclusive result. Two rejections concern
selection of derivative sources as essential even though their final prose is
faithful. The other rejections include metric substitution, causal inflation,
missing disagreement and a refusal presented as a successful correction.

Inputs and full judgments are retained separately:

- [Frozen blind inputs](../research/evidence/2026-10-25/blind-agent-review-inputs.json)
- [Per-criterion verdicts and hash binding](../research/evidence/2026-10-25/blind-agent-review.json)

This is a useful exploratory agreement check, not the `0.20.9` calibrated judge
gate. The parent selected a small authored set, source notes expose provenance
and episode scope, positives were already repaired, and there is one judge and
one attempt. No held-out production outputs or repeated-run variability were
measured. Host model identity and host usage cost were not independently pinned.
The baseline's original structural receipt still marks semantic rows unreviewed;
the separate agent receipt records exactly this narrower review. No human
review, provider inference trial, or change in release status is claimed.

## Caption coverage corrective maintenance

Read-only inspection of the already implemented #67 timing slice found two
deterministic defects. A first cue at 120 seconds could omit the leading gap
and report complete coverage. Nested cues could shorten the previous covered
end and invent an interior or trailing gap. The correction scans sorted cue
intervals from zero while retaining the furthest covered end. Leading gaps
strictly longer than 60 seconds now make coverage partial; overlaps do not
create false gaps. Known-duration tails use the union end. Unknown duration
still invents no tail. Eight regression cases cover these boundaries.

This is a correction to existing coverage reporting, not admission of a new
video feature or live trial. Caption acquisition currently does not supply
video duration to the timing helper, so production tail coverage remains
unknown. `complete` remains structural text coverage under the documented gap
policy, not proof that every meaningful video moment was captured. Existing
sidecars are not rewritten automatically; the corrected rule applies when
caption evidence is generated again.

The shared test guard blocks public socket connections but permits loopback
and does not confine child-process traffic by itself. Existing component tests
do not prove a whole-chain private-media non-egress contract. A future bounded
connected test should exercise caption failure, permitted local-ASR transport,
both analysis passes, verification, materialized artifacts, late caveats,
missing paths and restart reuse. Mocked transport would establish orchestration
only; real ASR, image interpretation and semantic qualification remain separate.

## Remaining release acceptance

`0.20.9` still needs representative research-quality evidence and judge
calibration; corrected authored controls and transport observations alone
cannot close it. Issue #61 still needs paired reasoning comparisons at matched
quality, including failed attempts, time, and cost. No reasoning settings were
requested or sent by this work, and no local-runtime effect was measured.

Issue #67 stays separate. Caption timing and synthetic frame flags do not prove
connected video understanding, actual frame interpretation, or the full-chain
local-only privacy contract. Real source qualification, inference trials, and
release admission are not implied by this baseline work. Issues #33 and #63
remain closed.

The next justified action is to retain these failed selection cases alongside
the repaired authored controls, then review proposed production selection and
route corrections against the same corpus before admitting a default change.
Any live comparison still needs an explicit source, route, elapsed-time and
spend scope. No human response is required to continue offline inspection and
test development.

## Verification and handoff

The [offline quality receipt](../research/evidence/2026-10-25/offline-quality.json)
records commands, limitations, artifact paths and SHA-256 hashes. Final local
pytest: 7,786 passed, four skipped, nine deselected, two upstream deprecation
warnings in 641.04 seconds on Windows/Python 3.15. Combined coverage is 95.48%,
statement coverage 96.66%, and branch-only coverage 91.77% (14,160/15,430).
The combined gate passes; the separate 95% branch-only gate remains unmet.

Lock freshness, frozen synchronization without package changes, Ruff lint and
format, Pyright with zero errors/warnings, all four import contracts, Bandit
with no medium/high findings, dependency audit, generated public contracts and
agent distributions passed. Source/wheel build without build isolation,
required wheel members, CLI help and evidence-input hash checks also passed.
The audit ignored stale cache-deserialization warnings and found no known
vulnerabilities. Pytest warnings concern upstream Starlette/AnyIO and
google-genai/Python typing deprecations; no dependency change was made.

One preliminary full-suite run was superseded while independent edits landed.
Initial test-fixture attempts exposed stripped whitespace at the boundary and
remaining budget that still admitted the primary section. Those fixture
assumptions were corrected before the final run; the receipt preserves these
attempts separately from acceptance evidence. Total session time and host
agent usage cost were not independently measured. Repository provider calls
and inference spend were zero. No reasoning setting or runtime effect was
tested. The measured 641.04 seconds is the final pytest run only.

Base and final HEAD remain `51d0c187fd71b03a387f8ecdee3d61ea2d09ed46`.
The final working tree contains this uncommitted implementation, tests, docs
and evidence; there was no preexisting dirty work. No commit, push, issue
publication, merge or release occurred. Historical GitHub CI validates the
base SHA, not this patch. New remote CI, platform matrices, isolated installed
wheel, live journeys and whole-chain private-media trials were not run.

Rollback is selective reversion of this local patch against the base commit.
There is no corpus migration or provider configuration change. Existing
caption sidecars were not rewritten. #61 and #67 remain open, and their
remaining acceptance is recorded above. The completed handoff is stronger
authored controls, independently retained agent judgments, production
selection counterexamples and corrected caption interval coverage. Next is a
bounded production selection/route correction proposal using these same
controls, with live trials kept separately scoped.
