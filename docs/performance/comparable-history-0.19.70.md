# Comparable performance history (0.19.70)

Distill now has five paired, semantically comparable performance runs for each
canonical GitHub-hosted runner class: Linux X64 and macOS ARM64. Each run covers
the fixed-seed corpus matrix at 100, 500, 1,000, and 10,000 insights plus the
frozen workflow replay, with 20 measured fresh-process samples per operation.

All ten host bundles passed the repository's fail-closed evidence validator.
The history builder then rechecked every raw receipt hash, runner identity,
canonical profile, source fingerprint, operation result count, and deterministic
result digest before aggregating run-level medians. The shared semantic
compatibility signature is
`f78c71f84cad35d1cbd363d6a0ecb8c78c48e74154b0356282044313d44b422a`.

## Provenance

| Workflow run | Commit | Host bundles |
|---|---|---|
| [32431022291](https://github.com/blisspixel/distillr/actions/runs/32431022291) | `1c72d1125fad079253b441f3595ad587f5aa4686` | Linux X64, macOS ARM64 |
| [32489877708](https://github.com/blisspixel/distillr/actions/runs/32489877708) | `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166` | Linux X64, macOS ARM64 |
| [32489888386](https://github.com/blisspixel/distillr/actions/runs/32489888386) | `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166` | Linux X64, macOS ARM64 |
| [32494705846](https://github.com/blisspixel/distillr/actions/runs/32494705846) | `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166` | Linux X64, macOS ARM64 |
| [32501350792](https://github.com/blisspixel/distillr/actions/runs/32501350792) | `373ee7ac541c0c40d1fcbedad3991b91b13554a1` | Linux X64, macOS ARM64 |

GitHub artifacts expire. The complete validated inputs are retained under
[`comparable-history-0.19.70/inputs/`](comparable-history-0.19.70/inputs/).
The generated evidence bundle contains the
[`manifest`](comparable-history-0.19.70/MANIFEST.json),
[`machine-readable history`](comparable-history-0.19.70/HISTORY.json), and
[`complete operation table`](comparable-history-0.19.70/SUMMARY.md).

## Result

The five-run gate is complete. Hosted-runner variance is material: most corpus
operations show moderate noise, and a few short replay operations show high
relative noise because millisecond-scale scheduling effects dominate them. A
single relative threshold would therefore create false alarms.

The active policy remains advisory:

- Use the rolling median of at least five comparable run-level p50 values.
- Flag timing only after two consecutive comparable runs exceed both 20 percent
  and the operation-specific absolute noise floor.
- Derive the absolute floor as the greater of 1 ms or three times the historical
  median absolute deviation.
- Track a candidate peak-RSS ceiling at 125 percent of the observed maximum,
  rounded to 4 MiB.
- Keep timing and resource signals non-blocking. Correctness, receipt integrity,
  deterministic result identity, and source integrity remain blocking.

This policy characterizes public-runner noise. It does not establish a service
level objective or compare Linux with macOS hardware.

## Remaining 1.0 performance evidence

1. Publish clean-install time, wheel and source-distribution sizes, CLI cold
   start, help, doctor, update, uninstall, and export measurements across Linux,
   macOS, and Windows.
2. Publish the 20-paper, 50-video, and site-batch live reference journeys with
   hardware, provider, model, tokens, cost, verification, retry, resume, no-op,
   and corpus-digest metadata.
3. Continue collecting comparable runs so the advisory baseline evolves without
   turning public-runner timing into a pull-request gate.

The benchmark contract and native-language admission rules remain in
[`../design/performance-and-language-admission.md`](../design/performance-and-language-admission.md).
