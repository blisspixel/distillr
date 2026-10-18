# Research trust and runtime review, October 17, 2026

## Decision

Admit issues #40 through #57 to 0.20.7 in the recorded
[execution plan](../design/open-issue-execution-2026-10-17.md). Correct the
evidence claims first: discovery failures, revisions, freshness uncertainty,
verification scope, and derived citations. Then validate the interface and
installed package. These checks do not complete the separate 1.0 semantic,
platform, performance, or freeze-time security gates.

## Current external facts

| Boundary | Evidence and decision |
| --- | --- |
| arXiv discovery | The [API manual](https://info.arxiv.org/help/api/user-manual.html#34-errors) defines errors as Atom entries. Recognize them before paper construction. Malformed feeds fail; valid empty feeds succeed with zero results. Preserve per-query receipts and the existing three-second request gate. |
| arXiv revisions | [Explicit versions](https://info.arxiv.org/help/api/user-manual.html#511-a-note-on-article-versions) identify the reviewed receipt; unversioned requests select latest. Surface newer or ambiguous revisions, retain exact shortlist IDs, and refuse automatic revision publication. An update is the same work, not another corroborating source. |
| Gemini default | Google's [models](https://ai.google.dev/gemini-api/docs/models) and [deprecations](https://ai.google.dev/gemini-api/docs/deprecations) identify 3.7 Flash as an alias for 3.8 Flash. Select `gemini-3.8-flash` directly. This removes alias drift; it is not a quality-based migration to another model family. |
| Argon | The [Argon reference](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon) specifies a unified 1,048,576-token context and 65,536-token ordinary synchronous output. Offer it as an explicit candidate, without adding another execution adapter or enabling long decode. |
| Scheduled prices | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) gives Argon $2/$10 per million input/output tokens through November 30, then $4/$20 from December 1. Flash 3.8 is $0.75/$3.75 through December 31, then $1.50/$7.50. Resolve dates in UTC. Preserve historical price identities and stored billed costs. |
| Scheduled shutdown | The [deprecation table](https://ai.google.dev/gemini-api/docs/deprecations) gives the old December 2025 Deep Research preview an earliest shutdown date of October 23. Fail new execution closed from that date with a replacement hint. Retain historical receipts and pricing. |
| Python | The [supported-version table](https://devguide.python.org/versions/) identifies 3.15 as stable. Promote the core default and blocking CI matrix, while retaining the maintained 3.12 floor. Supporting 3.11 would require changing established syntax and confinement primitives without improving these issue outcomes. #48 explicitly permits this alternative. |
| Python dependencies | Windows 3.15 required current wheels for pywin32, lxml, grimp and watchfiles. An old greenlet beta wheel crashed Playwright; the [upstream compatibility notes](https://greenlet.readthedocs.io/en/latest/changes.html) explain the beta ABI boundary. Require greenlet 3.5.5 or later on 3.15 and lock 3.5.6. pip-api 0.0.34 imports removed `sre_constants`; [0.0.35](https://github.com/di/pip-api/releases/tag/0.0.35) restores the audit tool on 3.15. |
| Actions | Resolve [checkout](https://github.com/actions/checkout/releases/latest) v7.0.1 and [setup-uv](https://github.com/astral-sh/setup-uv/releases/latest) v10.3.0 to immutable commits. Use uv 0.13.1 consistently. |

The Gemini menu contains default, budget, and flagship candidates. Older IDs
remain interpretable for existing records; absence from the menu does not
invent a shutdown date. The other providers retain their October 6 audit date.
No cloud model inference was used for this review.

Fresh-install checks also required current Pydantic/core wheels on 3.15.
The locked Linux container exposed uvloop 0.22.1's missing 3.15 wheel;
[uvloop 0.23.0](https://pypi.org/project/uvloop/0.23.0/) supplies that wheel.
These targeted compatibility updates preserve the existing provider SDKs.
PyYAML remains a source build on 3.15, so a compiler-free fresh installation
is not yet proven on every platform.

## CPU entailment findings

The [PyTorch installer](https://pytorch.org/get-started/locally/) provides a
CPU wheel index. A follow-up check found torch 2.14.1+cpu wheels for Windows
and Linux Python 3.15 on that index, although generic PyPI torch wheels still
stop at 3.14. A Windows 3.15 installation and real HHEM scoring passed with
NumPy 2.5.4 and regex 2026.9.29 wheels. Native macOS extra installations still
need Python 3.12 through 3.14. The
[CPU installation recipe](../install.md#cpu-only-prose-verification) selects
that index explicitly rather than pulling Linux CUDA dependencies.

The [HHEM model card](https://huggingface.co/vectara/hallucination_evaluation_model)
distinguishes HHEM 2.1 from the earlier 512-token model. Inspection of the
[pinned implementation](https://huggingface.co/vectara/hallucination_evaluation_model/blob/8e4a2e6e96c708cc76c2344f7e4757df2515292c/modeling_hhem_v2.py)
confirmed that `predict` tokenizes complete pairs without truncation. Its
inherited tokenizer metadata produces a misleading 512-token warning.

A local Python 3.14.7, PyTorch 2.12.0+cpu, transformers 4.57.6 probe used a
1,542-token pair. A supported statement at the end scored 0.9877; a
contradictory statement scored 0.0942. CUDA was absent from the build. This
proves the tested tail was available; it does not calibrate a general semantic
quality threshold. The two exact, verified metadata diagnostics move to debug
logging only while the pinned checker loads or scores. Other warnings and
failures retain their normal treatment.

The follow-up torch 2.14.1+cpu probe on Python 3.15 reproduced both scores
exactly, with no CUDA build. HHEM's approved outer code revision now also binds
the foundation configuration and tokenizer to
`google/flan-t5-base@7bcac572ce56db69c1ea7c8af255c5d7c9672fc2`.
Only its named data files are downloaded; cached complete snapshots avoid a
repeat download. Both revisions participate in the local reuse fingerprint.
Optional fsspec, setuptools and torch dependency floors were raised after
reviewing upstream advisories. The retained Transformers 4.x advisories require
paths such as training, custom generation, LightGlue dispatch or tokenizer
saving that Distill does not expose. They remain visible version alerts rather
than being dismissed or described as a clean optional dependency audit.

## Native evidence boundaries

- Active claim generations replace a complete source/artifact batch, including
  successful zero-claim retirement. Invalid, partial, changed-during-call, and
  interrupted extraction cannot replace the prior generation. History remains
  append-only, and derived-answer origin remains explicit.
- Two-pass synthesis uses present artifacts and active generations, refuses
  incomplete extraction, and checks its source snapshot before publication.
  A dirty marker keeps prior synthesis freshness unknown until publication.
- Ask and query summaries exclude operational and answer artifacts. Citation
  handles retain exact path and origin; colliding legacy basenames receive
  distinct handles. A source changed during generation refuses publication.
- A citation identity is structural evidence. Semantic support remains model
  judgment, with the optional local checker and explicit coverage limitations.
  Numeric-only checks never establish prose support or exhaustive discovery.
- Timestamp freshness detects newer assessed inputs. It cannot prove unchanged
  dependency membership or detect every removed input. Missing, unreadable, or
  malformed scoped timing remains unknown.
  Legacy naive timestamps compare as recorded wall-clock values; mixing them
  with aware timestamps or filesystem instants is unknown because their original
  timezone cannot be recovered. Explicit offsets compare as UTC instants.
- The concept-generation review found a distinct historical projection policy:
  concept notes and mention history can retain earlier material. This release
  does not turn that policy into safe automatic revised-paper publication.
  Revision discovery remains preview-only pending explicit admission of that
  broader history and correction behavior.
- Advisory lock files keep a stable identity for waiting processes. Deleting
  them after each command would split mutual exclusion. Persistent empty locks
  are coordination state; temporary publication files must still be cleaned up.

## Validation records

Offline tests, installed-wheel journeys, CPU semantic probes, browser checks,
and final quality-gate results are tracked separately in the execution plan.
The initial browser run used axe-core 4.14.0 from its official npm package,
verified against the registry's SHA-512 integrity. It reported no WCAG A/AA
violations on Dashboard, Topics, Costs and Watchlist in both house themes,
or on the standalone export. It does not replace a screen-reader review.

Local journeys use an isolated daemon with `OLLAMA_NO_CLOUD=1`, a scrubbed
environment, an installed public model, and no paid credentials. Receipt
bundles identify their candidate wheel hash and distinguish earlier failed
attempts from successful validation. Candidate evidence does not certify a
later changed wheel; the final wheel receives its own smoke and hash checks.

Sanitized [JSON receipts and SHA-256 sums](evidence/2026-10-17/) retain the
earlier candidate's failed answer publication explicitly. Native plugin results
are retained from the hash-matched unchanged skill and eval content, rather than
claiming a new native run or a new semantic quality baseline.

The second bug hunt also covers verification-setting changes invalidating
local reuse and optional checker failure status. Deterministic structure owns
identity, refusal and publication; models still judge prose support and source
faithfulness. Carrying paths and origins adds bounded labels to existing
retrieval context, without adding a model call or increasing its source limit.
Claim generation events add durable batch identity to the bounded history log;
they do not add a separate database or provider fallback.
