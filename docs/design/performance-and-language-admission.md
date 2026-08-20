# Performance and language admission

> Status: 1.0 decision charter. This document defines how Distill improves
> latency, throughput, memory use, installation quality, and operational
> reliability without turning language choice into architecture theater. It
> operates inside the stable-contract promise in [`../../ROADMAP.md`](../../ROADMAP.md)
> and the source-of-truth rules in [`../invariants.md`](../invariants.md).

## Decision

Distill is **Python-first, not Python-only**.

Python remains the reference product and control layer through 1.0: CLI and MCP
contracts, provider routing, corpus writes, verification gates, and semantic
policy. Compiled dependencies and external runtimes are already legitimate
parts of the system. A new first-party language is neither a goal nor a taboo.
It enters only when a measured, bounded capability earns the permanent release
and maintenance cost.

The optimization order is fixed:

1. Attribute the time and resources.
2. Remove repeated work and unnecessary data movement.
3. Improve the algorithm.
4. Add bounded concurrency where the trust boundary permits it.
5. Extract one narrow native capability only if the whole workflow still
   misses a published budget.

Exceptional means faster and more reliable accepted artifacts for users. It
does not mean maximizing a language-level microbenchmark or collecting
runtimes.

## What the current evidence says

The 2026-07-11 agentic-harness validation recorded 162,299 local-model tokens
over 864.5 cumulative inference seconds. The full evidence is in
[`agentic-development-harnesses-validation.md`](../research/agentic-development-harnesses-validation.md).
That is the dominant cost in the validated workflow.

A read-only diagnostic pass on the same 12-source topic found the following warm
local medians. These numbers explain the current decision, but they are not the
published 1.0 baseline because the runner, corpus digest, and benchmark harness
were not yet frozen.

| Operation | Median |
|---|---:|
| Corpus search | 20.95 ms |
| Near-duplicate audit | 14.22 ms |
| Whole-library link check | 20.49 ms |
| Numeric verification | 1.93 ms |

Profiling showed that corpus walking, file reads, and frontmatter handling
dominate present search and duplicate passes. A zero-cost native scoring kernel
could save only single-digit milliseconds at the current corpus size.

Near-duplicate detection was the first credible scaling seam because the exact
implementation compared every document pair. The pre-change diagnostic showed
the shape clearly:

| Insights | Pairwise comparison |
|---:|---:|
| 100 | 47.8 ms |
| 250 | 310 ms |
| 500 | 1.50 s |
| 1,000 | 9.26 s |

Version 0.19.34 addressed the algorithm before considering Rust. An ephemeral
rare-first prefix index now proposes a conservative candidate superset, and
exact Jaccard remains the final authority. Differential property tests compare
the complete clustering result with the former exhaustive implementation,
including arbitrary thresholds and floating-point edges.

| Insights | Exhaustive pairs | Indexed candidates | Candidate reduction |
|---:|---:|---:|---:|
| 100 | 4,950 | 15 | 99.6970% |
| 500 | 124,750 | 75 | 99.9399% |
| 1,000 | 499,500 | 150 | 99.9700% |

On the fixed corpus, the scale-100 result digest stayed
`47ab80898c755c30742167edff78b93ffd5b850985c290faf85c3bd474abec9a`.
Twenty fresh-process samples recorded an 81.5 ms p50 and 95.3 ms p95. Five
scale-500 samples recorded a 434.4 ms p50 and deliberately omitted p95 because
the evidence count was below 20. A same-machine scale-1,000 diagnostic fell
from 9.31 seconds to 1.11 seconds. These are directional development results,
not the published 1.0 baseline. They show that the first bottleneck was the
algorithm, while the remaining time is dominated by corpus loading and
shingling. No native extraction is justified yet.

## The 1.0 performance baseline

The baseline has four complementary layers.

### 1. Deterministic corpus scale fixtures

Generate corpora from a fixed seed rather than checking thousands of artifacts
into git. Cover at least 100, 500, 1,000, and 10,000 insight artifacts with
controlled document sizes, duplicate density, near-threshold duplicate pairs,
frontmatter failures, broken links, long lines, and path edge cases.

Measure inventory, insight discovery, search, link checking, audit rollups,
near-duplicate detection, export, and dashboard-data loading. Record:

- End-to-end and phase wall time
- p50 and p95 over repeated deterministic operations
- CPU seconds and peak resident memory
- Files, bytes, source artifacts, and derived artifacts processed
- Cold-process and warm-process results
- Python, operating system, architecture, package version, corpus seed, and
  cache state

The repository-only v2 harness lives in `benchmarks/corpus_scale/`.
It generates a fixed-seed corpus under a fresh temporary directory, measures
insight discovery, search hits and misses, link checking, near-duplicate
detection, and the shared dashboard snapshot, then verifies the corpus digest
did not change. Every recorded sample executes one allowlisted operation in a
fresh child process with a timeout. Results use the versioned
`corpus-scale-result.v2` JSON shape and retain raw wall-time, CPU-time,
peak-RSS, result-digest, and worker-PID samples. The harness records a normalized
source-tree fingerprint, fails closed on corpus or source mutation, labels the
filesystem state `warm-generated`, strips parent pytest and coverage
instrumentation from each worker, and suppresses p95 below 20 successful
samples. There is deliberately no installed command and no user-selected
library path. Source `project_version` and installed distribution version are
reported separately with an explicit match flag, so a deliberate `--no-sync`
run cannot label current editable source with stale package metadata. Windows
receipts at scale 100, 500, 1_000, and 10_000 with n=20 are published under
[`../performance/baseline-0.19.60.md`](../performance/baseline-0.19.60.md).
Linux and macOS repeats, cold-filesystem experiments, malformed and
threshold-edge fixture expansion, and scheduled history remain follow-on work.

### 2. Offline workflow replay

Use frozen receipts and deterministic provider responses to replay paper,
video, site, synthesis, verification, profile, and report paths without network
or model spend. Report Distill-owned overhead separately from simulated
provider latency. This is the layer suitable for repeatable CI checks. The
repository-only harness lives in `benchmarks/workflow_replay/`. A Windows n=20
receipt for paper, video, site, paper synthesis, numeric verify, profile
preview/run, and report synthesis is published under
[`../performance/workflow-replay-0.19.63.md`](../performance/workflow-replay-0.19.63.md).

### 3. Live reference journeys

Keep the roadmap's reference 20-paper run, 50-video catch-up, and site-batch.
Add time to first useful artifact, time to final verified artifact, verification
coverage, provider wait, Distill-owned time, peak memory, bytes written, token
volume, actual or estimated cost, failure rate, retry rate, resume rate, and
no-op rate.

Live provider, network, and hardware results are release evidence, not ordinary
PR gates. They must name the hardware, provider, model identifier, model digest
when available, route class, concurrency limit, cache state, and corpus digest.

### 4. Installation and quality of life

Track clean-install time, wheel and source-distribution size, CLI cold start,
`--help`, `doctor`, update, and uninstall behavior on Linux, macOS, and Windows.
The current single universal wheel and compiler-free installation are product
advantages, not incidental build details.

Status 2026-07-25 (0.19.45): the first measured cold-start fix followed this
document's optimization order, staying in Python and removing work rather than
reaching for a native path. `-X importtime` attributed most of a 2.4-second
`import distill.cli` to third-party libraries imported at module scope, led by
the google-genai SDK and its transitive `mcp` dependency at roughly 1.1
seconds, then python-docx, yt-dlp, requests, and httpx. Each now loads at
first real use. On the development machine (Windows, Python 3.12) the import
fell to about 0.8 seconds and `distill --version` from roughly 3.0-3.3 seconds
to about 0.95 seconds at the median, with `--help` about 1.0 second. A
subprocess regression test keeps those libraries off the import path. The
numbers above are single-machine evidence, not the cross-platform published
baseline this section still owes.

## Telemetry contract

A non-empty `run_id` must join command, phase, provider-call, and cost rows.
Phase telemetry records wall time, CPU time, peak memory, artifact counts, byte
counts, and a wait classification: acquisition, provider, queue, subprocess,
filesystem, deterministic CPU, write, or mixed for an aggregate phase.

Implemented v1 uses a context-local run id established by CLI and MCP entry
points and appends phases to `.distill/phase_telemetry.jsonl`. Provider calls,
cost rows, and run artifacts carry the same id. `RunSummary` execution and
accordion report work provide the first coarse spans. The current
`peak_rss_bytes` is the process high-water mark observed when a phase ends, not
an isolated per-phase allocation peak. Stable coverage across the remaining
workflow phases is still pending. `distill costs` now exposes the recent
command anchors and joins their provider, phase, and cost rows by exact
`run_id`. Its JSON coverage counts distinguish joined, legacy-without-ID,
unanchored, schema-invalid, unreadable, and excluded observer rows. The command
envelope owns invocation wall time, process CPU, process peak RSS, and terminal
command outcome. A matching workflow summary, when present, separately owns
recorded artifact and byte counts plus workflow outcome; absent workflow data
stays unknown rather than becoming zero. Provider time is cumulative call
time, not critical-path time. Process CPU includes overlapping in-process work
and excludes child-process CPU. Legacy history is never backfilled from
timestamps, and repeated `distill costs` observer runs do not crowd actual
workflows out of the recent evidence list. Per-run phase, provider, and cost
completeness flags prevent a valid subset from understating a run: if an
attributable row is schema-invalid or its log is unreadable, affected counts
and rollups stay unknown rather than presenting partial evidence as complete.

The headline product metrics are:

- Time to first accepted artifact
- Time to final accepted artifact
- Accepted verified artifacts per hour
- Cost per accepted verified artifact
- p95 latency for interactive read operations
- Peak memory at the documented scale points
- Failure, refusal, retry, resume, and clean no-op rates

This is lightweight local measurement, not a distributed tracing platform.
Distill does not need an observability backend to understand its own phases.

## Regression policy

- Correctness, schema compatibility, stable ordering, and resource ceilings are
  always blocking.
- Shared PR runners do not enforce tight microbenchmark thresholds until runner
  variance has been characterized.
- Begin with advisory history. After at least five comparable runs, a
  deterministic regression may block only when it is reproduced and exceeds
  both 20 percent and a meaningful absolute budget.
- The controlled scale suite runs on a scheduled runner and before a release.
- Live model and network journeys remain diagnostic release evidence.
- Faster output that reduces verification coverage or acceptance rate is a
  regression, even when wall time improves.

## Optimization work before native code

1. **One corpus inventory per command.** Build a read-only manifest once and
   reuse paths, identities, sizes, mtimes, hashes, links, and optional lexical
   data across search, audit, links, and dashboard reads.
2. **Disposable derived indexes.** Markdown and JSONL remain authoritative. An
   index may live only under `.distill/`, must be git-ignored and rebuildable,
   and must have a direct-file fallback.
3. **Indexed duplicate candidates (shipped 0.19.34).** The ephemeral rare-first
   prefix index removes impossible pairs while exact Jaccard verification,
   deterministic grouping, ordering, and legacy threshold behavior remain
   unchanged.
4. **Bounded concurrency.** Parallelize independent acquisition or model work
   only after URL pinning, cancellation, contention, cost, write-scope, and
   provider-limit behavior are explicit. Unbounded fan-out is never an
   optimization.
5. **Connection and process reuse.** Reuse HTTP clients where safe and reduce
   repeated subprocess startup before replacing orchestration code.

## General language-admission gate

A disposable spike may begin only when every condition below is true:

1. A production-shaped profile shows the component is at least 10 percent of
   affected workflow time and at least 250 ms p95, or it violates an explicit
   memory, latency, safety, or reliability budget.
2. Algorithmic, batching, caching, and data-movement improvements have been
   attempted first.
3. The capability has a narrow deterministic contract. Semantic policy and
   canonical corpus state do not cross the boundary.
4. The spike targets at least a 3x component improvement and either a 10 percent
   whole-workflow improvement or a 30 percent peak-memory reduction.
5. Differential, property, and adversarial tests preserve output, ordering,
   errors, cancellation, malformed-input limits, and deterministic behavior.
6. Installation time, artifact size, cold start, debugging, dependency audit,
   contributor cost, and release complexity are measured with the speedup.

A concrete security boundary may bypass the timing threshold only when the
threat model identifies the vulnerability class the extraction removes.

## Language-specific decisions

### Rust

Rust is the only plausible in-process accelerator today, but it is conditional.
Candidates are indexed near-duplicate generation, a batched read-only corpus
scanner, or a future hostile binary parser whose safety case justifies ownership.

The CLI, provider routing, prompts, workflow decisions, frontmatter semantics,
and model judgment remain in Python. A Rust boundary receives a batch, owns
substantial deterministic work, and returns a versioned result. It does not
retain arbitrary Python objects or call repeatedly across a fine-grained FFI
boundary.

PyO3 is appropriate when in-process overhead and buffer transfer matter. A
versioned stdin/stdout worker is preferable for large batch operations where
process isolation matters more than call overhead.

### Go

Go is not admitted inside the current Distill product. The roadmap explicitly
makes Distill the loopable primitive and persistent state layer while external
harnesses own queues, leases, scheduling, backpressure, and cross-machine
execution.

If a real multi-client control plane later needs crash-safe queue recovery or
independent scaling, a separately released Go runner may consume frozen Distill
contracts. It must execute verified Distill commands rather than write corpus
state directly. Go through Python FFI is not a target.

### Mojo

No first-party Mojo code is admitted without a measured numerical or accelerator
kernel that Distill itself owns and that mature PyTorch, NumPy, JAX,
CTranslate2, or provider runtimes do not already solve.

Evaluating Modular MAX as an optional inference endpoint is provider work. It
uses the existing doctor, usage-ledger, cost-policy, and `distill eval` gates and
does not require Mojo source inside Distill.

As of 2026-07-11, Mojo 1.0 is still beta, calling Mojo from Python is documented
as an evolving beta feature, and Windows support requires WSL. Those facts make
it unsuitable for Distill's first-party cross-platform package today. They are
current constraints, not permanent exclusions.

### Free-threaded CPython

Python 3.14t moves from categorically declined to benchmark-gated. Test it only
when profiling identifies GIL-bound in-process CPU work, every required
extension remains compatible without silently restoring the GIL, and a standard
versus free-threaded comparison shows a material whole-workflow gain without
violating latency or memory budgets.

The primary concurrency model remains I/O plus external workers. A future
free-threaded path needs repeated race, cancellation, property, and stress tests;
it is not enabled merely because the interpreter supports it.

## Native release requirements

Before first-party native code can become a default:

- The reference Python path remains installable without a compiler, or the
  accelerator ships as a separate optional distribution.
- Every supported operating system and architecture receives tested prebuilt
  artifacts.
- No executable is downloaded silently at runtime.
- Native dependency locks, licenses, vulnerability auditing, and SBOM content
  join the existing release chain.
- Installed-wheel tests cover supported Python and platform tags.
- Panic, timeout, cancellation, malformed input, unsupported CPU, and resource
  exhaustion fail cleanly at the boundary.
- A documented configuration switch disables the accelerator.
- The Python quality gates remain unchanged and the native package gets its own
  blocking formatting, lint, static-analysis, test, and coverage policy.
- Main ancestry, matching versions, successful CI, provenance, PyPI, and GitHub
  Release gates apply to every shipped artifact.

For Python extensions, free-threaded distribution is an additional matrix:
regular `abi3` does not cover free-threaded builds, and the stable `abi3t` ABI
starts with Python 3.15. Python 3.14t therefore needs a version-specific wheel.

## Non-goals

- No full rewrite in Rust, Go, or Mojo.
- No language quota or polyglot architecture diagram as a success metric.
- No database of record and no required index service.
- No native implementation of semantic judgments.
- No internal scheduler or general-purpose control plane.
- No tight performance gate on noisy public CI runners.
- No claim that a microbenchmark speedup equals lower user-visible latency.

## Current primary sources

- [CPython free-threading guide](https://docs.python.org/3/howto/free-threading-python.html)
- [PyO3 ABI features](https://pyo3.rs/main/features.html)
- [PyO3 building and distribution](https://pyo3.rs/main/building-and-distribution.html)
- [Mojo 1.0 beta announcement](https://www.modular.com/blog/modular-26-3-mojo-1-0-beta-max-video-gen-and-more)
- [Calling Mojo from Python](https://docs.modular.com/mojo/manual/python/mojo-from-python/)
- [Mojo system requirements](https://docs.modular.com/mojo/requirements/)
- [MAX custom operations](https://docs.modular.com/max/develop/custom-ops)
