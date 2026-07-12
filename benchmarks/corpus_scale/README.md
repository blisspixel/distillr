# Corpus-scale benchmark

This repository-only harness measures deterministic Distill read paths against
a generated mixed-source corpus. It is advisory evidence, not a public product
command or a blocking performance threshold.

Run a small local sample from the repository root:

```console
uv run --frozen python -m benchmarks.corpus_scale --scale 100 --iterations 5
```

The harness always creates its library under a fresh operating-system temporary
directory and removes it when the run finishes. It has no library-path option,
does not load artifacts from a configured user library, makes no model calls,
and performs no network access. Results are printed as one
`corpus-scale-result.v1` JSON object.

Each operation retains its raw wall-time, process-CPU, and sampled peak-RSS
measurements. The summary uses nearest-rank p50 and p95 values. The operating
system page cache is intentionally reported as `uncontrolled`, so a warm
process result must not be described as a cold-filesystem result.

The current near-duplicate operation is still an all-pairs scan. Start with the
documented scale-100 sample; the 1,000 and 10,000 canonical scale runs remain
pending until child-process timeouts are part of the harness.

The corpus is hashed before and after every operation and for the whole suite.
Any digest change is an integrity failure. Shared-runner timings stay advisory
until enough comparable history exists to characterize noise, as defined in
`docs/design/performance-and-language-admission.md`.

Timing values never affect the exit code. An operation error or corpus-integrity
failure returns nonzero so automation can distinguish invalid evidence from a
valid advisory result.
