# Corpus-scale benchmark

This repository-only harness measures deterministic Distill read paths against
a generated mixed-source corpus. It is advisory evidence, not a public product
command or a blocking performance threshold.

Run a small local sample from the repository root:

```console
uv run --no-sync python -m benchmarks.corpus_scale --scale 100 --iterations 5
```

For a focused run with a tighter failure bound:

```console
uv run --no-sync python -m benchmarks.corpus_scale --scale 500 --operation near_duplicates --iterations 20 --timeout-seconds 30
```

The commands assume the locked development environment has already been
synced. `--no-sync` also lets the read-only harness run while a local
`distill serve` process has the Windows console executable open.

The harness always creates its library under a fresh operating-system temporary
directory and removes it when the run finishes. It has no library-path option,
does not load artifacts from a configured user library, makes no model calls,
and performs no network access. The private worker accepts a workspace only
when its random token matches the disposable marker written by the parent.
Results are printed as one `corpus-scale-result.v2` JSON object.

Every recorded sample runs one operation in a fresh child process. This keeps
Python allocator state and process RSS from leaking between operations. Parent
pytest and coverage instrumentation is removed from the worker environment so
it neither contaminates measurements nor competes for coverage data files.
Each operation retains raw wall-time, process-CPU, sampled peak-RSS, result
digest, and worker PID measurements. The summary always reports nearest-rank
p50 and suppresses p95 until at least 20 successful samples exist. The
generated corpus and integrity reads warm the operating-system page cache, so
results explicitly report `warm-generated` and must not be described as
cold-filesystem evidence. The result also hashes normalized source files,
including working-tree changes, so development runs with the same package
version remain distinguishable. It records the source `project_version`
separately from the
`installed_distill_version` and reports whether they match, so `--no-sync`
cannot silently label changed source with stale distribution metadata.

The near-duplicate operation exercises exact Jaccard verification behind the
ephemeral rare-first prefix candidate index. Start with the documented
scale-100 sample. Published Windows n=20 receipts at 100, 500, 1,000, and
10,000 live in `docs/performance/baseline-0.19.60.md`. Safe sample timeouts
on that host were 60s at 100 and 500, 120s at 1,000, and 300s at 10,000.

The corpus is hashed before and after every operation and for the whole suite.
Any corpus or measured-source digest change is an integrity failure. Timings
stay advisory until enough comparable history exists to characterize noise,
as defined in `docs/design/performance-and-language-admission.md`.

Timing values never affect the exit code. An operation error or corpus-integrity
failure returns nonzero so automation can distinguish invalid evidence from a
valid advisory result.

## Cross-platform canonical evidence

The manual `Performance evidence` GitHub Actions workflow runs the complete
100, 500, 1,000, and 10,000 matrix at n=20 on Linux and macOS, followed by the
frozen workflow replay. It is deliberately absent from pull-request and push
triggers. The workflow has read-only repository permission, uses immutable
current action-release commits, and does not persist checkout credentials.
Timings remain advisory and cannot block a change.

`benchmarks.evidence_bundle` validates every raw receipt before upload. It
requires the canonical seed, sample count, warmup count, operation order,
successful operations, stable result digests, unchanged source and corpus
digests, matching checked-out package versions, and the actual runner platform.
It then writes a concise summary plus a provenance manifest that binds every
receipt digest to the repository, commit, workflow run, and runner identity.
Missing or invalid evidence fails the workflow.

The first validated same-commit Linux/macOS n=20 matrix, complete raw bundles,
and cross-host correctness comparison are published in
`docs/performance/cross-platform-0.19.66.md`.
