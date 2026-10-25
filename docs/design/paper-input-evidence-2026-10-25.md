# Paper route and supplied-input evidence, 2026-10-25

Status: bounded unreleased correctness work supporting queued `0.20.9`.
The reviewed research-quality baseline remains incomplete. This slice does
not change configured model defaults, selection policy, ranking prompts,
analysis prompts, or the 80% threshold. It introduces no inference trial.

## Outcome and acceptance

The actual route must determine its own context boundary, and a paper insight
must disclose supplied-chunk prompt coverage independently of semantic
sufficiency. Existing source receipts remain authoritative. The prior
[offline review](research-desk-review-2026-10-25.md) retains the counterexamples
and authored-control review; it is not overwritten by this implementation.

Single-pass paper analysis keeps workload `site`. Its initial fit decision
uses `site` metadata. If multipass is needed, that path keeps workload
`analysis` and obtains its own metadata for chunking and pass selection.
This repairs a route/window mismatch rather than choosing a new provider.
Opposite route capacities must both be exercised. No-result multipass
analysis must fail explicitly rather than silently publish a lead-only answer.
Only models returned by current contributing responses may name the resulting
insight; an earlier tracker entry or configured model is not proof of execution.
For example, a large `site` window with a smaller `analysis` window must not
force multipass unnecessarily. A small `site` window with a larger `analysis`
window must not send the full source through `site` merely because `analysis`
could hold it. Correcting this decision can change the path used under explicit
workload overrides; the configured workload/provider meanings stay the same.

An internal `paper_input_evidence` JSON scalar carries input evidence through
the existing two-value analysis return. The publication seam extracts it into
a content-addressed sibling JSON receipt before publishing the insight. The
persisted insight retains only compact reference, digest and coverage fields;
the full manifest cannot crowd synthesis or claim-extraction context. The
receipt binds the exact analyzer input, acquisition mode, estimated planning
budget, chunk identities and hashes, and actual per-pass chunk picks. It also
binds the normalized published source body and insight body. No separate
database or publication seam is introduced.

Single-pass receives the whole returned document as one supplied chunk.
Multipass records transformed chunk text hashes, not an invented byte partition
of the source: the chunker strips whitespace and inserts continuation headings.
Selected and omitted identities refer to that supplied chunk set. The existing
source writer also normalizes bold-wrapped Markdown headings, so analyzer-input
and published-receipt body digests are separate identities. This slice does not
claim to preserve the original PDF bytes. Context metadata describes the
requested workload's planning window, not measured effective fallback context.
The content budget uses the existing character estimate and 20% reserve. It is
not a runtime-tokenizer measurement or a hard bound on the entire rendered
prompt, whose instructions also consume context.

`prompt_chunk_coverage` is `all_supplied_chunks`, `some_supplied_chunks`, or
`unknown`. It is never a quality score or proof of full-source capture. An
abstract-only capture can supply all of its chunks while omitting the PDF.
`semantic_sufficiency` stays `not_assessed`. A legacy result with no reliable
executed chunk IDs stays unknown, with omitted IDs unknown rather than empty.
Skipped passes cannot contribute planned IDs, while a shared chunk can appear
in several actual passes and is counted once in their union. Empty outputs
remain visibly empty even if their inputs were supplied.

`original_source_completeness` remains `not_established`, including when
`source_capture` is `full_pdf`. That legacy label means nonempty PDF-derived
text was available. Existing PDF extraction caps at 200 pages and two million
characters without returning a truncation flag. Neither all supplied chunks
nor this label proves the original PDF tail was captured. This slice exposes
that limitation rather than inventing a full-source qualification.

## Capture generations and publication failure

One per-paper publication lock covers prior-capture retention, current metadata
and source writes, input evidence, verification, and insight publication.
Before replacing a capture, its exact prior bytes are retained under
`.history/paper-receipts/<sha256>.md`. Identical archived bytes are reused;
corrupt retained content or a failed archive write refuses the replacement.
No prior capture is deleted. The published source stamps its normalized body
digest as `receipt_sha256`, and every newly written insight carries
`paper_receipt_body_sha256`, including callers without a chunk manifest.

Readers validate that current capture binding before exposing a paper insight.
Discovery, rereading an already discovered reference, and direct paper synthesis
share the same check. When a replacement capture succeeds but its analysis is
refused or publication fails, prior insight and evidence remain historical;
they cannot masquerade as analysis of the replacement source. Legacy unbound
pairs remain compatible until a newly stamped capture establishes a current
generation. Compact input-evidence references additionally require the retained
JSON file, digest, schema, source-body and insight-body bindings to match.

The exact final rendered candidate is verified before acceptance. Successful
publication uses the existing bound-artifact path, which writes verification
before the insight and rolls back verification if the artifact write fails.
An input-receipt failure or verification-write failure cannot replace the old
insight. A refused first candidate still retains capture and diagnostic evidence.
This is structural generation and publication integrity, not semantic selective
revision of a corpus or its already-derived claim history.

## Rule and model ownership

Python records exact identities, hashes, route budgets, actual prompt inputs,
and successful response provenance. Models still judge relevance, faithfulness,
disagreement and sufficiency. No heading keyword expansion, semantic length
threshold, additional coverage pass, or extra model call is added. The existing
Erratum and repeated-recap failures remain failures of sufficient selection;
the new receipt exposes their omitted chunks rather than hiding them behind a
green structural test. Larger-context and sufficient-multipass controls remain.

## Verification boundary

Offline tests must bind recorded picks to actual analysis prompts and reproduce
the route mismatch before the fix. They also cover unknown legacy IDs, skipped
passes, shared chunks, empty output, mixed response models, reused trackers,
receipt/hash preservation through publication, and abstract-only acquisition.
Use the existing no-service guards and frozen toolchain. Run the full repository
gate and report combined and branch-only coverage separately. No installed
package change, live source, model inference, remote write or release is implied.
Semantic research quality and live route behavior remain separate acceptance.

## Before and after evidence

An isolated process loaded `paper.py` directly from base commit
`51d0c187fd71b03a387f8ecdee3d61ea2d09ed46`, leaving working-tree files untouched,
then ran the same 15 offline route, empty-response and provenance regressions.
All 15 failed against that implementation in 0.53 seconds. The identical node
set passed against the corrected working module in 0.49 seconds. Only paper
module code was reverted in that process; shared dependencies and the frozen
environment were held current. This is a targeted differential check, not a
complete historical checkout or a live-provider comparison. The logs are
`.agent/paper-input-before.log` and `.agent/paper-input-after.log`.

## Final verification and handoff

The [paper-input quality receipt](../research/evidence/2026-10-25/paper-input-quality.json)
records the tested source/artifact hashes, differential regressions, limits,
commands and actual results. Final full pytest on Windows/Python 3.15:
7,888 passed, four skipped, nine deselected, two upstream deprecation warnings
in 609.85 seconds. The four skips require POSIX FIFO, permission or no-follow
descriptor semantics. Combined coverage is 95.50%, statement coverage 96.68%,
and branch-only coverage 91.81% (14,231/15,500). The combined gate passes;
the separate 95% branch-only target remains open.

Frozen lock/sync without dependency changes, Ruff lint/format, full-package
Pyright with no errors/warnings, all four import contracts, Bandit with no
medium/high findings, dependency audit, generated public contracts and Agent
Skill checks passed. Build without build isolation, CLI help, and isolated
imports of both new modules from the wheel passed. A preliminary suite was
superseded when adversarial review found the publication failure cases; it
is not acceptance evidence. The final run includes those repairs and tests.

The slice starts at `51d0c187fd71b03a387f8ecdee3d61ea2d09ed46` with the prior
local baseline/caption changes intact. A local checkpoint retains the combined
verified patch. Its SHA is in Git history and the session handoff; the receipt
binds file contents rather than inventing a self-referential commit hash.
No push, issue publication, merge, release or live provider trial occurred.
New remote CI, platform matrices and installed-wheel trials were not run.
Repository provider calls and inference spend were zero. Host-agent usage cost
and complete session wall time across all attempts were not independently
measured; the receipt reports the measured test durations separately.

Rollback is selective source reversion or reversion of the local checkpoint.
The offline tests did not modify an operator corpus or provider configuration.
Model defaults, inference prompts and semantic selection policy remain the
same. The original Erratum/recap counterexamples remain visible selection
failures, now with exact omitted-input evidence. `0.20.9`, #61, #67, and the
broader 1.0 gates remain open. Next is a bounded, reviewed comparison of actual
selected evidence before changing selection or reasoning defaults. Live trials
still require explicit source, route, elapsed-time and spend scope.
