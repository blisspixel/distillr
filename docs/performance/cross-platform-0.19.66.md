# Cross-platform performance baseline (0.19.66)

This is the first published Linux and macOS baseline from Distill's canonical
performance workflow. It covers the fixed-seed corpus-scale matrix at 100,
500, 1,000, and 10,000 insights plus the frozen workflow replay. Every
operation ran 20 measured samples after one warmup in a fresh child process.
Network access failed closed, the deterministic provider stub recorded zero
provider wait, and no metered API was used.

Timing is advisory. Correctness, input integrity, operation completion, sample
count, and deterministic output equality are the validated claims.

## Provenance

- Release: `distillr==0.19.66`
- Commit: [`1c72d1125fad079253b441f3595ad587f5aa4686`](https://github.com/blisspixel/distillr/commit/1c72d1125fad079253b441f3595ad587f5aa4686)
- Workflow: [`Performance evidence` run 32431022291](https://github.com/blisspixel/distillr/actions/runs/32431022291), attempt 1
- Profile: seed `20260711`, 20 measured samples, 1 warmup, scales 100 / 500 / 1,000 / 10,000
- Route: `deterministic-stub`, `fail-closed` network, zero simulated provider wait
- Linux: X64, runner `GitHub Actions 1000098516`, job 96622413954, 1h 7m 40s
- macOS: ARM64, runner `GitHub Actions 1000098515`, job 96622413806, 45m 41s
- Linux artifact: 9430520677, retained by GitHub through 2026-09-20T01:08:57Z
- macOS artifact: 9430058590, retained by GitHub through 2026-09-20T00:46:53Z

The complete artifacts are retained in this repository after the workflow
artifact expires:

| Host | Manifest | Full summary | Raw receipts |
|---|---|---|---|
| Linux | [`MANIFEST.json`](cross-platform-0.19.66/linux/MANIFEST.json) | [`SUMMARY.md`](cross-platform-0.19.66/linux/SUMMARY.md) | [`linux/`](cross-platform-0.19.66/linux/) |
| macOS | [`MANIFEST.json`](cross-platform-0.19.66/macos/MANIFEST.json) | [`SUMMARY.md`](cross-platform-0.19.66/macos/SUMMARY.md) | [`macos/`](cross-platform-0.19.66/macos/) |

The archived Linux manifest SHA-256 is
`ddb7e2b33c2582f77f69ac82d0f1b16cf99f273104be77ce4d9a045ae43ce2ba`.
The archived macOS manifest SHA-256 is
`9575d75d740f92d025e8e60c8bfffa89b201a59c5608b715fe06bbb416c73654`.
Each manifest binds the five raw receipt hashes plus its generated summary to
the repository, commit, release version, run, attempt, and runner identity.

## Correctness result

Both bundles passed the repository's fail-closed validator in GitHub Actions.
After download, their declared file sizes and SHA-256 hashes were recomputed
independently and every receipt was validated again from the raw JSON.

The cross-host comparison covered 32 deterministic operation results:

- 24 corpus operations: six operations at each of four scales
- 8 frozen workflow-replay operations
- 20 stable samples per operation per host, or 1,280 compared measured samples
- Identical normalized source fingerprints and corpus or fixture digests
- Identical result counts and result digests for every operation
- Unchanged source and generated-corpus integrity before and after measurement

The first 0.19.65 run exposed a real cross-platform defect: equal-score search
results inherited filesystem traversal order before applying the result limit.
Version 0.19.66 added a portable relative path and lexical path tie-break. The
fixed run produced these identical Linux and macOS `search_hit` digests:

| Scale | Result count | Result digest |
|---:|---:|---|
| 100 | 25 | `0cfe42b183d5280daad01ea4e765573e58a1e6509bf70dc9b123c56db869b0ab` |
| 500 | 25 | `c32c261617e79981fe68e372f8da60eca5416fd7ee307ae93d296ec3cd2c4e73` |
| 1,000 | 25 | `c32c261617e79981fe68e372f8da60eca5416fd7ee307ae93d296ec3cd2c4e73` |
| 10,000 | 25 | `c32c261617e79981fe68e372f8da60eca5416fd7ee307ae93d296ec3cd2c4e73` |

## Advisory timing

Hosted-runner timing is useful for scale shape, not for ranking operating
systems or setting a release threshold from one run. The tables below show the
largest corpus and the complete frozen replay. The archived summaries contain
all four corpus scales.

### Corpus scale 10,000

| Operation | Linux p50 | Linux p95 | Linux peak RSS | macOS p50 | macOS p95 | macOS peak RSS |
|---|---:|---:|---:|---:|---:|---:|
| Insight discovery | 18.77 s | 19.53 s | 70.2 MiB | 11.05 s | 17.26 s | 74.1 MiB |
| Search hit | 34.55 s | 35.95 s | 79.1 MiB | 24.56 s | 33.49 s | 83.8 MiB |
| Search miss | 34.25 s | 35.72 s | 74.7 MiB | 24.29 s | 30.10 s | 79.3 MiB |
| Link check | 1.28 s | 1.31 s | 48.2 MiB | 1.48 s | 1.78 s | 52.2 MiB |
| Near duplicates | 31.96 s | 32.78 s | 482.1 MiB | 18.71 s | 21.43 s | 537.8 MiB |
| Dashboard snapshot | 30.99 s | 32.76 s | 72.9 MiB | 17.81 s | 18.15 s | 78.4 MiB |

### Frozen workflow replay

| Operation | Linux p50 | Linux p95 | Linux peak RSS | macOS p50 | macOS p95 | macOS peak RSS |
|---|---:|---:|---:|---:|---:|---:|
| Paper analyze | 731.9 ms | 753.7 ms | 67.7 MiB | 371.2 ms | 423.8 ms | 80.5 MiB |
| Video analyze | 2.9 ms | 3.0 ms | 49.6 MiB | 1.5 ms | 1.8 ms | 54.0 MiB |
| Site analyze | 35.6 ms | 35.9 ms | 59.1 MiB | 16.2 ms | 17.4 ms | 71.5 MiB |
| Paper synthesize | 18.2 ms | 18.7 ms | 50.8 MiB | 11.4 ms | 13.7 ms | 54.7 MiB |
| Numeric verify | 1.5 ms | 1.6 ms | 49.6 MiB | 1.2 ms | 1.5 ms | 53.8 MiB |
| Profile preview | 1.0 ms | 1.0 ms | 49.6 MiB | 0.7 ms | 0.9 ms | 54.0 MiB |
| Profile run | 11.3 ms | 13.0 ms | 51.9 MiB | 6.8 ms | 9.9 ms | 54.0 MiB |
| Report synthesize | 26.9 ms | 27.6 ms | 54.4 MiB | 13.2 ms | 15.1 ms | 63.0 MiB |

## Limits and next gate

This is one hosted runner from each host class. It does not characterize
runner variance, cold filesystem behavior, clean installation, CLI cold start,
export cost, Windows behavior at this exact commit, or a live provider journey.
It therefore establishes reproducible correctness and a first timing point,
not a performance service-level objective.

The next dependency-ordered work is:

1. Accumulate at least five comparable runs per Linux and macOS host class.
   This is required before an honest relative plus absolute regression policy
   can distinguish product change from public-runner noise.
2. Add clean-install time, wheel and source-distribution size, CLI cold start,
   `--help`, `doctor`, update, uninstall, and export measurements across Linux,
   macOS, and Windows. These are direct user-experience costs not covered by
   warm generated-corpus evidence.
3. Run the 20-paper, 50-video, and site-batch live reference journeys as
   release evidence with hardware, provider, model, token, cost, verification,
   retry, resume, no-op, and corpus-digest metadata. Live network and model
   results stay outside ordinary pull-request CI.

No native-language work is admitted by this result. The measured workflow and
memory history must identify a bounded seam that clears the published
admission thresholds first.
