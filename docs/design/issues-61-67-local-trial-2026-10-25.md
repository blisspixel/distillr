# Bounded local reasoning and visual qualification, October 25

The trial rejects a default change and leaves both issues open. Four Faros
outputs fail a material faithfulness criterion under both thinking settings.
The synthetic video route materializes evidence, but its model descriptions
hallucinate tables instead of reading the slides. The visual review is malformed
and the consumer artifact is explicitly incomplete. A successful transport or
an aggregate of passing examples cannot override these failures.

## Authority, identity and accounting

The user authorized existing installed models, frozen fixtures and synthetic
local media: at most 24 inference attempts in 15 minutes, zero API spending,
no installs, downloads or cloud fallback. The earliest setup started at
2026-10-26 00:15:23.040118 UTC (October 25 locally); the diagnostic ended at
00:23:57.371900 UTC. The whole window was 514.332 seconds, including the failed
setup, manual inspection and diagnostic. There were 22 inference attempts:
16 text comparisons, five connected visual/analysis/review calls, and one
single-frame diagnostic. The first setup failed with `OSError` before any
inference. The main execution took 53.528 seconds; this is not the whole window.

The base was `a38c5d2bfefd8eb82c17e8c097a8b60e65e3705c`, with uncommitted
provider, router and video evidence changes under test. This is working-tree
qualification, not an immutable released-build receipt. The retaining commit
and final quality gate must be reported separately by the implementation handoff.

The actual route was local Ollama 0.40.4, `gemma4:e2b`, digest
`7fbdbf8f5e45a75bb122155ed546e765b4d9c53a1285f62fd9f506baa1c5a47e`.
Uncached locality proof passed. Metadata advertised thinking and vision plus
131,072 context tokens. A trial-only transport wrapper uniformly requested
`num_ctx=16384`, temperature zero and no retries. Text outputs were capped at
1,536 tokens; the final diagnostic at 512. This avoids comparing different
requested contexts, but does not establish actual allocated context or image
patch capacity. Production context policy is unchanged. The server returned
only a 13-character template string; full rendered model-template identity
remains unknown. Exact application prompts are retained by hash.

All 22 attempts, including unusable outputs, reported 17,275 input tokens and
9,722 output tokens. Repository API spending was $0 through proven local
inference. Host-agent review usage and dollar cost are unknown, not claimed
free. Time and tokens include failed semantic attempts. No raw thinking trace
was retained: receipts contain requested/sent controls and trace presence.

## Issue 61: paired quality result

Four fixtures ran twice in alternating setting order, using actual site
analysis, source selection and question-answer paths with caches disabled.
The source pool is fixture-authored, not live discovery. One blinded agent
reviewed shuffled outputs with source anchors and per-criterion reasoning;
the setting and repeat key was withheld until after verdicts. These are agent
semantic judgments, not human expert review or independently calibrated judge
performance. Exact inputs, verdicts and the revealed key are retained.
The earlier offline agent calibration agreed on 16 of 16 authored controls
(eight intended passes and eight intended failures), as retained in the
[offline review](research-desk-review-2026-10-25.md). This is narrow authored
control agreement, not a measured generalization result or a broader baseline
pass. No human expert review was performed.

| Case | Results | Interpretation |
| --- | --- | --- |
| Frozen Faros extraction | Four failures, two per setting | All repeat the headline's tripled probability as a finding while also retaining ratio qualifications. Correct details elsewhere do not repair the unsupported claim. |
| Mature source selection | Four passes | Only the captured primary adult review is selected. The derivative and uncaptured pediatric cohort are not treated as independent support. |
| Correction and disagreement | Four passes | Current A=11/adults, historical A=10, unresolved B=16/unspecified population and unaffected calibration survive. This is fixed-receipt synthesis, not production selective revision. |
| Scorer update | Four passes | 70 to 81 is a scorer correction, not model improvement; the website redesign is not another score change. |

For example, the first Faros answer says, "The probability of a production
incident has more than tripled for every code change merged." The source body
instead measures an incidents-to-PR ratio rising 242.7% between lower and higher
adoption periods. The answer even says the ratio is not a probability. This
internal conflict is a material failure, not partial success. No prompt repair
or post-repair model run is claimed here.

For the six pairs with an actual effective control contrast, `think=false`
used 3,370 input/1,435 output tokens and 12.100 transport seconds;
`think=true` used 3,412 input/5,040 output tokens and 21.242 seconds.
All enabled cases returned a trace; disabled cases did not. Actual response
receipts report `trace_present` for enabled cases and `unknown` for disabled
cases. Absence of a trace is not independent proof that hidden reasoning was
disabled. These small
totals include model load and alternating order, not a stable throughput
benchmark. They establish no general quality equivalence or safe reasoning
reduction. Both settings fail Faros.

The four structured screening calls sent `think=false` under both requested
settings, as required by the existing JSON policy. Their receipts retain the
different requested values, actual `think=false` and effective `unknown`, with
support explaining the JSON constraint; they are a no-effective-contrast
control, excluded from the paired cost comparison. Defaults remain unchanged.

## Issue 67: actual pixels, unsuccessful understanding

The source is a local, silent, synthetic 125-second MP4, SHA256
`127e891d459d22309598b07a7eb0924241f6a2c5cfc80e525af07005ec89b8b7`.
Its initial slide lasts 65 seconds, a decisive qualification appears for five
seconds, and the initial slide returns. The transcript is explicitly authored
fixture text, not acquired speech. It mentions a later qualification without
supplying its denominator or population. It must not be called ASR success.

Regular requests at 0, 60 and 120 seconds miss the qualification. A targeted
request at 67 seconds acquires a distinct PNG. The actual transport attaches
the two unique image byte hashes rather than only their paths or descriptions:

| Extracted frame | SHA256 |
| --- | --- |
| Initial slide | `50469bde6415f7d66ba0732cf25d0295738c9139fa6b9d276340b5005fe6f43c` |
| Qualification | `63bc4a5511685351c6c5f1938036d93afaf9061cc8eb00e2b19baca86c5c474d` |

These are requested seek positions, not independently measured presentation
timestamps. All intervals between samples and the tail remain blind; sampling
does not establish source completeness. Restart acquisition reuse is recorded.
The baseline and targeted manifests preserve their sample identities and blind
intervals. Successful acquisition does not prove perception.

The model describes a "complex table with many rows and columns" for the
slide images. Targeting the decisive frame does not fix its description. The
two text passes produce an insight that repeats this false visual description
and never recovers the decisive qualification. The review returns strings
instead of the required criterion verdict objects, so the route refuses a
qualified result with `status=incomplete` and `review=null`. Its apparent
`source_fidelity=pass` must not be accepted. The extra single-frame diagnostic
returns a sequence of numbers and stops at the length limit. No usable
visual understanding, justified repository applicability or supported consumer
judgment was demonstrated.

Local captionless ASR is blocked: `faster_whisper` was absent in the inspected
project/system environment, installation and download were not authorized,
and this fixture is silent. Native video/audio ingestion was not exercised.
Actual local still-image transport is distinct from capable source-video
processing. No provider configuration is offered as proof of the latter.

## Retention, verification and next acceptance

The [artifact manifest](../research/evidence/2026-10-25/issues-61-67-local-trial/manifest.json)
records SHA256 and bytes for the exact responses, prompts, source plan,
setup failure, diagnostic, blinded assessment, both sample manifests, synthetic
source and key PNGs. These are research evidence snapshots, not published
corpus outputs. Text is normalized to repository LF; the manifest also retains
the original workspace hash where newline normalization changed bytes.
Copied receipts intentionally retain original scratch paths;
use the manifest and retained relative artifact names to locate their copies.
The generated insight is retained unchanged as evidence of a rejected result.
The nine prompt files and generated insight use JSON string envelopes named
`<prompt-sha>.txt.json` and `video-insight.md.json`. To reconstruct exact original
bytes, decode the envelope JSON, encode `utf8_text` as UTF-8, and verify its
`original_sha256` and `original_bytes`. This preserves terminal whitespace and
newlines without weakening repository whitespace hooks. Envelope hashes in
the manifest identify the retained files; their original hashes identify the
actual supplied prompts and generated insight. Historical trial receipts are
unchanged. Other retained text uses repository LF with original workspace
hashes recorded when normalization changed bytes.

Five [audit recipe snapshots](../research/evidence/2026-10-25/issues-61-67-local-trial/recipe/issue61_67_trial.py.txt)
retain the exact executed trial, media generator, process-budget wrapper,
single-frame diagnostic and blind-input preparation scripts as `.txt` files.
They are evidence, not supported production entry points or hidden runnable
defaults. Running them again requires renewed trial authority and a fresh
bounded authority record. The trial guards socket connections to the local
Ollama endpoint, counts transport attempts before execution, observes the
shared deadline and uses an outer process time/memory guard. It permits the
event loop's local socket pair. The context override verifies advertised
capacity before pinning 16,384 requested tokens; it does not change production
policy. These Python guards do not prove a whole-chain OS-level outbound
denial boundary across subprocesses or the model daemon.

Focused provider/proof/local-reasoning checks after the trace fix passed 188
tests; focused Ruff, formatting and Pyright passed. The implementation pass
also passed lock/frozen sync, repository Ruff/format, Pyright with no warnings,
all four import contracts, Bandit at medium/high severity, pip-audit,
public-contract and skill-distribution checks, source/wheel builds, all ten
wheel assets and dependency floors, existing-environment wheel-resource smoke,
and skill archive inspection. An initial full-suite run was interrupted at
45% with no reported failures after final review found and fixed stream
completion metadata handling. The restarted suite reported 8,085 passed,
four skipped, nine deselected and one module-size failure: the router grew
to 503 lines against its unchanged 500-line cap. A redundant nested model
selection check was simplified without changing precedence. That run measured
95.54% combined coverage and 91.88% branch-only coverage. The complete pre-push
gate must validate the repaired tree; these figures are not a passing run.
These checks validate
mechanics, not the live semantic verdicts. Full working-tree gates, separate
combined/branch coverage and platform skips belong to the final implementation
receipt. The trial did not demonstrate the complete outbound-denied local-only
chain, live captionless ASR or real-source visual qualification.

For #61, reject both extraction alternatives on this case. Screening is
inconclusive because there is no effective contrast. Correction and freshness
are inconclusive beyond their observed passes: two repeats show lower tokens
and time with thinking disabled but do not justify a general recommendation.
Keep defaults unchanged. The issue explicitly allows an inconclusive result,
so the controlled pilot may satisfy its bounded evaluation acceptance without
a quality improvement. A Faros repair is justified remaining product work,
not an invented prerequisite for closing #61. Final verification, a durable
acceptance comment and user authority still govern publication and closure.
Any subsequent model trial needs separate authority. For #67, retain the acquisition and refusal
evidence, fix or select a demonstrably capable route within explicit future
authority, and then qualify late caveat survival through actual repository
comparison. Neither issue is closed by these receipts. The broader 0.20.9
baseline remains queued. Rollback is removal of the opt-in implementation
patch; there is no changed default, published corpus or deployment to undo.
The trial itself performed no remote writes. After the trial, the operator
authorized finishing the wave, updating GitHub and publishing an updated
release after CI passes. The implementation handoff records the final commit,
actual remote actions and any remaining release limitations separately.
