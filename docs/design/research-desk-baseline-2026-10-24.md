# Research-desk structural baseline, 2026-10-24

Status: draft structural receipt. Expert review was not performed. No model
judge ran. Discovery and synthesis defaults are unchanged. This note does
not ship `0.20.9` and does not close issue #61.

## Question this step answers

Can deterministic CI tell a faithful use of a frozen source from a brief
that stores the corrective body and then presents a different claim, without
turning a keyword rule into a research-quality score?

## Contract

`distill/eval/research_desk.py` scores two tracks and leaves a third
unreviewed.

Retrieval checks source identity and pool role. Essential, correction, and
later material sources must be selected as that role. Redundant, derivative,
and later immaterial sources must be selected as that role or rejected with
a reason. Omitted and inaccessible sources must stay out, with an omission
reason. Unknown ids and duplicate selections fail.

Synthesis binds each brief sentence to one frozen anchor. The sentence
passes only when its anchor id exists, `presents_as` equals that anchor's
role, and the text equals the anchor or a registered equivalent. Order does
not matter. Required coverage is by anchor id: measurement, qualification,
disagreement, unavailable evidence, history, unaffected conclusions, and
withdrawal. `invalid_extraction` must be `refused`. `zero_claim` must be
`zero_claim`. Those two variants also fail if a measurement sentence is
present. Every other variant expects `answered`.

A structural pass is retrieval and synthesis with no failing row. Semantic
rows stay `unreviewed`: faithful qualification prose, fair disagreement,
useful change explanation, and judge calibration. An unreviewed row does
not count as a pass and does not fail the structural track. Keyword
overlap, length, and a single score are not used.

`distill/eval/research_desk_cases.py` freezes the cases.
`distill/eval/research_desk_controls.py` freezes the authored selections
and briefs and builds `baseline_document()`. The published copy is
[research-desk-baseline.json](../research/evidence/2026-10-24/research-desk-baseline.json).
`gate_passed` is false. `expert_review` is `not_performed`.
`live_model_trial` is false. Cost is zero.

## Faros headline and body

The contested case freezes a small excerpt of Faros's takeaway page,
`https://www.faros.ai/blog/ai-acceleration-whiplash-takeaways`, accessed
2026-10-24. Tests do not fetch the live page.

The heading is a headline. Its metric kind is incident probability, and it
is not a measurement. The body measurement is an incidents-to-PR ratio, up
242.7%, denominator PR, population and comparison "low to high AI adoption",
causal status `not_claimed`. A qualification states that this is a ratio,
not a probability, because one pull request can be linked to more than one
incident. A full brief may therefore contain the word "probability" and
still pass. A second qualification records that the period comparison is
observational. That sentence is fixture-authored: the page describes the
period comparison and does not use the word randomized.

A contrasting synthetic source reports incident probability in a randomized
comparison. Briefing that source as probability passes. Binding the Faros
ratio sentence onto that source fails. The checker is not a rule that
always replaces "probability" with "ratio".

The talk stand-in is fixture-authored and marked derivative. It is not a
quotation of a talk and it is not independent corroboration. Selecting it
as essential fails retrieval even when the brief itself is faithful. The
full report is inaccessible: the frozen page does not include that file.
Selecting the takeaway page and then presenting the headline as the
measurement fails synthesis while retrieval passes.

A different Faros figure, monthly incidents up 57.9%, must not replace the
ratio.

## Other cases

Mature and fast-moving cases use short synthetic sources. They cover an
essential paper against a textbook derivative, a later material score
change, a later immaterial website batch, and a batch that reports no
meaningful change.

The correction episode uses authored briefs. It includes narrowing that
keeps the disagreement and the unaffected conclusion, withdrawal that
removes current reliance and keeps history, a zero-claim that must not
retire the unaffected conclusion, a refused extraction that must not appear
as a successful correction, and a homepage batch that does not change the
disagreement. These controls do not run production refresh. Selective
revision stays a planned post-1.0 capability.

## What this does not establish

No human expert reviewed the fixtures. No judge was calibrated. The
receipt's limitations name those two gaps: `expert-review` is unreviewed
and owned by `0.20.9`; `selective-revision` is planned and owned by the
post-1.0 research desk. Issue #61 stays open. Issue #63 remains the offline
recipe identity check only.
