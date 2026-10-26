# Repair trial: source faithfulness, pixels and captionless speech

This second trial made the failure more specific and demonstrated local speech
acquisition. It did not complete source-faithful extraction or qualified video
understanding. Publication is stopped at the user's direction: neither a stable
release nor a prerelease is justified by packaging a failed outcome.

## Scope and accounting

The renewed authority allowed 24 inference attempts in 20 minutes, using
installed local models and cached ASR assets, no installs, downloads or cloud,
and zero API spending. The shared window started 2026-10-26 00:58:59.681916 UTC
(October 25 locally); the last inference update was 01:15:05.840553 UTC,
966.159 seconds later. The budget is exhausted: 22 LLM attempts and two actual
ASR attempts. Setup failures before inference remain retained separately.

The ledger records 33,252 input tokens and 20,099 output tokens, including
truncated and semantically failed answers. Repository API spending was $0;
host-agent review usage and cost remain unknown. A third trial with a proposed
$3 API ceiling is awaiting separate authority. No further model calls are
authorized by this report.

The base implementation checkpoint is `fa6aa7efb57cb64191a032b957a4935cebfb517c`
with dirty repair work. The remote remains
`51d0c187fd71b03a387f8ecdee3d61ea2d09ed46`. No issue comments, closures, push,
tag, release or publication resulted from this repair trial. Defaults remain
unchanged. These working-tree receipts are not released-build acceptance.

The actual LLM route remained local Ollama, with fresh locality proof and
model digest checks. The [trial receipt](../research/evidence/2026-10-25/issues-61-67-repair-trial/trial.json)
records exact model digests for `gemma4:e2b`, `ministral-3:8b` and the later
installed candidate `qwen3.6:27b`. Requested context was uniformly 16,384;
temperature zero and retries disabled. Text comparisons retained a 1,536-token
limit. The visual-only limit was raised to 4,096 after actual truncation, within
the original attempt/time/spend bounds; the amendment and failed attempt remain
visible. Requested context is not independent runtime capacity measurement.

Earlier scratch wrappers printed peak RSS bytes under an exit label because
`wait_for_process_budget` returns peak RSS, not a process exit code. Those
numbers do not establish abnormal process termination. Updated wrappers record
the actual return code separately. The receipt retains this correction.

## Source extraction: partial diagnosis, no accepted repair

The original Faros input already contained the ratio, denominator and decisive
qualification. The v2 failure was not source omission: answers copied the
headline as a finding and placed its contradiction elsewhere. Prompt v3
therefore requires reconciling headline claims with body measurements and
keeping qualifications beside every affected claim, including summary and
business implications. It does not rewrite metric keywords or suppress genuine
probabilities. Source strings and actual calls remain inspectable.

| Attempted extraction | Blinded agent outcome | Remaining mistake |
| --- | --- | --- |
| Gemma v3, ten outputs | Two pass, eight fail | Original, concise and reordered Faros cases still overstate or lose measurement/qualification fidelity; one completion reaches its length limit. Genuine probability controls provide contrast. |
| Ministral v3, two outputs | Both fail | Added unsupported control, vendor or denominator details despite reading slide text successfully in a separate task. |
| Qwen 27B v3, one output | Fail | Core ratio and scope improve, but the answer invents absence of confounder controls and attributes the collector's capture gap to the source page. |

The Qwen answer says, "Confounding variables ... are not controlled for."
The supplied excerpt supports causal uncertainty from an observational
comparison, not knowledge that controls were absent. It also says the page
explicitly states that the full report was not captured, although that limit
was authored collection context. A correct core metric does not excuse either
added claim. The exact outputs and per-criterion rationales are retained.

These are blinded agent semantic reviews, not human expert review. Original
Faros has two repeats per thinking setting; concise, reordered and genuine
probability variants each have one per setting. Old v2 outputs are historical
matched-source controls, not a fresh counterbalanced v2/v3 experiment. No
aggregate or speed comparison establishes a generally reliable route. No new
human or general judge calibration is claimed; the earlier narrow 16/16
authored-control agreement remains its own evidence.

Prompt v4 adds two general rules: absent excerpt details remain unknown rather
than proof of absent controls or full-study limitations; collector/authored
context must retain its origin. Follow-up suggestions cannot assert unseen
features or findings. Actual production-call tests preserve late/reordered
qualification, genuine probability and an adversarial collector instruction
without source rewriting. The 143 related tests, focused Ruff/format, Pyright
and public-contract checks passed. This is mechanical evidence only: v4 has
not yet been inference-validated. All v3 failures remain unchanged.

## Pixels: distinguish model capability from adapter transport

The official REST reference and canonical Ollama adapter give Gemma the same
decisive PNG. Both produce counting sequences instead of its text. Ministral
reads the actual correction words from those pixels. This isolates a model
capability failure from a blanket claim that image transport cannot work.
Successful pixel reading alone does not establish faithful downstream analysis.

The first connected visual attempt truncates pass 1 at 1,024 tokens (attempt
5); no successful final artifact is claimed from it. After the visual allowance
increases, all later visual passes stop normally. Yet the final review judges
the source slide's completeness instead of the generated consumer insight's
faithfulness and disclosed sampling limits. Its failed source-fidelity and
coverage verdicts leave the route `incomplete`. The original transcript in
this pipeline was authored fixture text, not the later ASR result.

Subsequent opt-in extraction and review-instruction repairs target that wrong
review object, but have not yet been inference-validated. The result cannot be
upgraded because the JSON schema is now valid or because a frame was readable.
Repository applicability and a justified consumer judgment remain unproved.

## Actual captionless local ASR, including a shared source

The earlier project-only ASR block was overcome by inspecting an existing
Scribe environment and already cached faster-whisper tiny model. Nothing was
installed or downloaded. This is an explicit qualification backend, not a new
default or silently selected provider.

The first successful actual ASR processes a 79.602125-second synthetic WAV,
SHA256 `86317b502d089f1cea9a7b28fb7e9bdf766f4aa77cf872cd7acd7a150365498d`.
The result preserves a late correction after 65 seconds: ratio rather than
probability, 40 adults, observational rather than causal, and no generalization
to children. The transcript says "incidence to pull requests ratio"; retain
that transcription wording rather than silently improving the receipt.

A second actual ASR processes the combined 125-second primary MP4, SHA256
`d5c98513f7342ab63409a677d3f797aa6dccc686d0f5f9dafee19025bee3e9cc`, and reports
125.01625 seconds of audio. The same MP4 also yields the visual samples at
0, 60, 67 and 120 seconds. Its 67-second qualification PNG has SHA256
`63bc4a5511685351c6c5f1938036d93afaf9061cc8eb00e2b19baca86c5c474d`.
The [combined-source receipt](../research/evidence/2026-10-25/issues-61-67-repair-trial/asr/combined-source.json)
binds actual audio and visual acquisition to one primary source. ASR is not
timestamped word coverage, and neither samples nor duration prove every
meaningful moment was captured. Requested seek times are not measured PTS.

Both ASR passes use the installed Scribe Python environment, cached
`Systran/faster-whisper-tiny` snapshot
`d90ca5fe260221311c53c58e660288d3deb8d356`, CUDA float16 and batch size four.
Actual inference takes 4.951 and 4.483 seconds respectively. Python socket and
DNS access is denied in parent and actual ASR worker. Native libraries and the
local daemon are not OS-sandboxed, so this is not whole-chain privacy proof.
Both successful receipts and the earlier subprocess-bootstrap refusal remain
retained. Zero API spending does not by itself establish privacy.

The real combined-media duration probe also exposed a tail-`moov` bounded-read
failure. The repaired probe and related focused checks passed 100 tests. This
mechanical repair enabled the actual second ASR and combined capture; it does
not establish source semantics. Real external caption failure followed by a
successful alternate acquisition has not been live-qualified here. The source
is synthetic and captionless; native source-video model ingestion was not run.

## Later environment incident and verification limits

The inference trial finished before a later artifact-hook verification caused
or coincided with actual environment setup. The generic managed Python 3.15
junction was replaced with a target at newly materialized Python 3.15.1, and
the pre-commit Python hook environment was recreated. Stopping the hook process
tree did not undo setup already performed. No explicit installer command was
issued by the child agent, but that does not mean no installation occurred.
The exact invocation, observed timestamps, process IDs and attribution limits
are retained in the [forensic envelope](../research/evidence/2026-10-25/issues-61-67-repair-trial/environment-forensics.md.json).
The user was informed. No claim of an installation-free whole work wave is
justified. The earlier ASR trial itself used the already installed Scribe
backend and cached model, with no model download.

The later full run finished with 8,100 passed and one PDF import failure,
measuring 95.43% combined coverage. It is not green. An old process running
Python 3.15.0 encountered standard-library files through the replaced 3.15.1
alias; the mixed environment is consistent with the missing
`xml.dom.minidom._XML_WHITESPACE` import. That evidence does not prove a
repository defect or definitive installer attribution. The isolated PDF test
then passed, which does not substitute for a complete gate. The fresh full suite against stable Python 3.15.1 with downloads disabled
passed: 8,109 tests, four skipped, nine deselected, 95.54% combined coverage
and 91.88% branch-only coverage (14,394 of 15,666 branches). Ruff, formatting,
Pyright with zero warnings, all four import contracts, Bandit at medium/high
severity, dependency audit, public contracts, both generated distributions
and the source/wheel build also passed. This does not establish the 1.0
branch-only target or remote CI. No release or prerelease is proceeding.

Latest captured-text origin and source-hash fields plus their 98 focused tests
are additional mechanical repairs. They bind capture provenance rather than
proving semantic faithfulness, and have not been validated by new inference.
Their outcome acceptance remains pending alongside v4 extraction and consumer
review qualification. A later green mechanical gate alone will not resolve
these semantic failures.

## Retention and next action

The [manifest](../research/evidence/2026-10-25/issues-61-67-repair-trial/manifest.json)
retains full request JSON, exact responses, prompt string envelopes, blinded
inputs/keys/verdicts, acquisition receipts, recipe snapshots and media identities.
No raw private thinking trace is persisted. Request identities are reproduced
by parsing JSON and serializing sorted keys with separators `(',', ':')`, then
SHA256, as in the retained recipe. This differs from the file-byte manifest
hash and must not be confused with it. PNGs reuse the prior retained identical
bytes instead of duplicating them.
Copied JSON uses repository LF and one terminal newline, with original hashes
retained where those formatting bytes differ; its values are unchanged.

Exact text is stored as JSON `utf8_text` envelopes; UTF-8 re-encoding must match
the envelope's original hash and length. The WAV uses deterministic gzip
(`mtime=0`). The combined MP4's gzip is just over the per-file limit, so two
ordered `.gz.partNN` files retain it: concatenate their bytes, verify the
manifest's gzip hash, then decompress and verify the original source hash.
Each retained file is below 1 MB. Recipe snapshots are audit data, not runnable
defaults; any new execution requires new authority. Scratch paths in historical
JSON locate the original run; the retained manifest maps durable copies.

The next justified action is another separately bounded trial of the general
v4 origin/unknown-details rules and repaired consumer review, with per-claim
blind assessment and explicit no-change or rejection outcomes. No further
prompt tuning should be declared successful without those actual outputs.
Keep #61 and #67 open, defaults unchanged and 0.20.9 queued until remaining
acceptance is supported. A prerelease does not resolve the failed outcome.
