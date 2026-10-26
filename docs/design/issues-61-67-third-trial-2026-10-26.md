# Third trial and stopping point, October 26

Model testing is stopped at the user's request. The retained evidence supports
an explicit inconclusive recommendation for #61. Video qualification #67
remains incomplete. Stable 0.20.9 remains queued: no tag, PyPI publication or
prerelease is authorized as a substitute for the unresolved outcome.

## Authority and complete accounting

The approved window was 2026-10-26 03:35:47.041289 through 04:05:47.041289 UTC:
30 inference attempts, 30 minutes and a $3 ceiling, local inference plus the
explicit text-only OpenRouter route. The ledger records 29 actual attempts,
29 canonical calls, 38,989 input tokens and 39,484 output tokens. Summed
reported billed cost is **$0.112788**. Local inference has no API charge;
host-agent review usage and cost remain unknown. The last submitted request
was at 03:59:45.003565 UTC, with the final receipt update at 03:59:58.605243,
within the original window. No window refresh or further model test occurred.

The route identities are local `qwen3.6:27b` and the approved OpenRouter
`anthropic/claude-sonnet-5.5`. The [ledger](../research/evidence/2026-10-25/issues-61-67-third-trial/trial.json)
pins the local digest, catalog/pricing, actual provider receipts, requested and
sent reasoning controls, context/output limits and attempt outcomes. Models,
routes and default prompts were not silently changed between paired settings.
Defaults remain unchanged; the mixed route is explicit opt-in, not local-only.

The first dispatch hook observed `httpx` but missed the locked SDK's `httpx2`
requests. Two initial cloud calls were later reconciled using exact canonical
provider attempt IDs, usage, billed cost and saved responses. Their raw wire
payloads and HTTP status were not captured and remain unknown. Append-only
recovery ordinal is not chronological dispatch order. Both the original
counter snapshot and reconciliation survive. Later requests are observed by
the repaired dispatch counter. Retained request JSON must not be described as
wire-exact evidence for the two unobserved calls. No API credential or private
reasoning trace is retained.

An overnight attempt to run the final consumer failed before inference with
`ModuleNotFoundError` while importing its helper. It produced no additional
model call or qualified consumer judgment. The console failure is retained;
the user declined more testing. A single unused count is not authority to
continue outside the window.

## #61: reject or inconclusive, with actual paired evidence

Four source/task cases ran twice per boolean setting on the same local model,
actual production prompt paths and captured inputs. Cache use was disabled.
The blinded packet carries source roles and actual selections; its model and
setting key is retained separately. Independent agents judged each criterion
against exact sources. These are agent judgments, not human expert review or
a claim of general calibration. Earlier 16/16 authored-control calibration is
narrow context, not a replacement for the individual live verdicts.

| Workload | Individual verdicts | Recommendation |
| --- | --- | --- |
| Faros extraction | Four fail | Reject both local settings for this fixture; material failures cannot be averaged away. |
| Mature source screening | Four pass | Inconclusive reasoning comparison: both requests send `think=false` for structured JSON. |
| Conflicting sources and correction | Three pass, one fail | Inconclusive with a material counterexample and two repeats per setting. |
| Freshness/scorer correction | Four pass | Observed success, insufficient evidence for a general default change. |

The total is eleven pass and five fail, not a passing aggregate. Per-workload
token and elapsed observations follow, summing two repeats per setting:

| Workload | Requested false output tokens / seconds | Requested true output tokens / seconds |
| --- | --- | --- |
| Extraction | 2,018 / 47.989 | 8,192 / 187.418 |
| Screening | 720 / 17.333 | 720 / 17.458 |
| Correction | 381 / 10.035 | 4,459 / 102.665 |
| Freshness | 298 / 7.843 | 2,851 / 66.431 |

These observations include truncation, model load, transport and production
work. They do not establish stable throughput or matched acceptable quality.
Screening has no effective contrast. A boolean switch is not a token budget.
Keep defaults unchanged; rollback requires no default migration.

Separate site prompt-v4 reference calls gave Sonnet two passes on Faros and
the genuine-probability contrast; Qwen passed one and failed one. This supports
a bounded reference comparison, not a universal route recommendation or proof
that local reasoning improves source faithfulness.

Issue #61 explicitly permits a per-workload recommendation or inconclusive
result. Its bounded acceptance can therefore be closed after final mechanical
verification and an issue comment linking the exact commit, receipts, actual
checks and remaining limits. Closing it would not declare the broader baseline
or video acceptance complete. No closure is claimed in this report.

## #67: independent review still finds a coverage error

The primary synthetic source is the same 125-second audio/visual MP4 retained
by the second trial, SHA256
`d5c98513f7342ab63409a677d3f797aa6dccc686d0f5f9dafee19025bee3e9cc`.
The ASR transcript identity is
`c24c5a5d1fbe9d9726732df23eedef8c24641c95f2f36f7a205c58d894cbaf99`.
Actual sample identities and blind intervals survive. No full-source native
video ingestion or real external source journey was newly performed.

The local Qwen video pipeline passed its own review, but independent review
failed unsupported creator interpretation, claims about event/speech timing
from requested sample positions, and omission of the recurring initial slide.
A self-pass is not independent acceptance.

The explicit mixed route kept image processing and the final sampled-image
review local with Qwen. Sonnet performed the two text extraction and synthesis
passes. The route also self-passed.
Independent review found one remaining material error: "The source's full
length and completeness are unknown." The acquired local source duration is
known to be 125,000 ms. Semantic completeness and upstream source completeness
remain unknown. Collapsing these distinct facts discards known capture
evidence. Other core ratio, adult-population and observational qualifications
were preserved in this exact artifact.

All four relevant prompts now receive explicit captured-duration metadata,
with 80 focused mechanical tests. The final artifact was not regenerated or
independently re-reviewed after that repair. Do not edit its generated output
by hand or upgrade its verdict. Consumer applicability remains unqualified;
#67 stays open with this precise limit and its other documented acquisition,
long-source and real-source boundaries.

## Paper fixture adjudication and current code limits

The targeted paper call originally received an independent failure verdict
for missing the 242.7% magnitude and an unaffected calibration fact. Static
inspection of the exact saved request later found an invalid fixture: those
facts were authored under `Technical Details`, but the renderer included only
canonical headings such as `Methods and Evidence`. Neither positive fact ever
entered the supplied prior insight or actual model prompt.

The [new adjudication](../research/evidence/2026-10-25/issues-61-67-third-trial/paper-trial-fixture-adjudication.json)
is retained separately from the unchanged original failure verdict. This call
cannot demonstrate retention of facts it never received. Its uncertainty is
not evidence of losing supplied facts, nor is the invalid fixture a passing
end-to-end paper qualification. A future trial must assert intended positive
facts are present in the actual request before inference and retain a negative
derived-summary control.

Current bounded residual paper review adds source-coherent reconciliation,
fragment identity manifests and a repair for the impossible-heading loop;
paper prompt identity advances to v4. Its 98 focused tests are mechanical
evidence. Residual grounding and semantic retention remain future qualification
limits. These repairs must not be described as live-validated by the invalid
trial. Complete selective revision remains planned after 1.0.

## Retention, verification and release status

The [manifest](../research/evidence/2026-10-25/issues-61-67-third-trial/manifest.json)
retains all actual ledger, source-plan, verdict, request, prompt and output
artifacts, the counter-recovery snapshot, both independent video assessments,
the original and adjudicated paper verdicts, and audit recipe/console snapshots.
Exact text is a JSON UTF-8 string envelope with original byte count and SHA256.
Copied JSON uses LF and one terminal newline. The manifest identifies each
retained file and its original identity where formatting differs. PNG and
compressed source media reuse earlier retained identical artifacts. Each file
is below 1 MB. Recipe snapshots are evidence, not new execution authority.

The [recorded local full mechanical gate](../research/evidence/2026-10-25/issues-61-67-third-trial-checks.json)
passed: 8,126 tests, four skipped and nine deselected, with 95.54% combined
coverage and 91.89% branch-only coverage (14,432 of 15,706 branches). Ruff,
formatting, Pyright with zero warnings, all four import contracts, Bandit at
medium/high severity, generated contracts/distributions and source/wheel builds
also passed. Subsequent macOS CI found that the internally created audio
scratch path retained a system `/var` alias and was correctly rejected by the
unchanged direct-path input guard. Canonicalizing only that owned scratch root
repairs the acquisition path; 173 focused transcription and connected-video
tests passed after the change. The exact-commit remote matrix must verify this
last portability repair separately. Model testing remains stopped. No historical
green gate validates newer code, and separate combined/branch coverage must
remain explicit. The earlier mixed-interpreter failure is not erased by this
trial. No hooks, environment setup, model calls or remote writes were performed
to promote these artifacts.

GitHub updates should report the bounded inconclusive #61 outcome after actual
checks, leave #67 open, and retain 0.20.9 as queued. Draft release notes may be
prepared for review, but no stable tag, PyPI release or prerelease follows from
stopping model tests with acceptance still incomplete.
