# Workflow replay (0.19.63, partial)

Status: **published offline Windows evidence** for frozen paper, video, site,
synthesis, numeric-verify, profile preview, profile run, and report synthesis.
Live provider journeys and multi-host history remain open. Prior slice:
[`workflow-replay-0.19.62.md`](workflow-replay-0.19.62.md). Policy:
[`../design/performance-and-language-admission.md`](../design/performance-and-language-admission.md).

## Environment

| Field | Value |
|-------|-------|
| Project version | 0.19.63 |
| OS | Windows 11, AMD64 (16 logical CPUs) |
| Processor | AMD64 Family 25 Model 116 Stepping 1 |
| Python | CPython 3.12.10 |
| Harness | `python -m benchmarks.workflow_replay` |
| Samples | 20 per operation, fresh child process each |
| Network | fail-closed |
| Provider | deterministic stub (`replay-stub`) |
| Simulated provider wait | 0 ns |
| Integrity | source fingerprint unchanged |

Raw result:
[`workflow-replay-windows-0.19.63.json`](workflow-replay-windows-0.19.63.json)

Reproduce:

```console
uv run --no-sync python -m benchmarks.workflow_replay --iterations 20 --timeout-seconds 30
```

## Offline workflow operations

Nearest-rank quantiles. p95 is reported only because n=20. Provider wait is
zero, so Distill-owned wall equals total wall.

| Operation | p50 Distill-owned | p95 wall | Peak RSS | Result digest (prefix) |
|-----------|------------------:|---------:|---------:|------------------------|
| paper_analyze | 661 ms | 691 ms | 68 MiB | `3a5dc9851d77` |
| paper_synthesize | 38.8 ms | 47.9 ms | 54 MiB | `a1c312be6f90` |
| profile_run | 48.9 ms | 54.4 ms | 61 MiB | `06ce0239fb60` |
| report_synthesize | 14.3 ms | 15.8 ms | 52 MiB | `c9ad4a54886f` |
| site_analyze | 7.0 ms | 8.3 ms | 52 MiB | `4786f2d22d59` |
| video_analyze | 4.1 ms | 5.1 ms | 52 MiB | `a8e9ab1c466f` |
| verify_numeric | 3.0 ms | 4.0 ms | 51 MiB | `59f70f82cde2` |
| profile_preview | 1.0 ms | 1.3 ms | 51 MiB | `cb3f0761a683` |

Paper, video, site, paper-synthesis, and verify result digests match the
0.19.62 receipt. Profile preview expands a frozen YouTube handle, HTTPS feed,
domain, repository, and query into candidates without opening a public socket.
Profile run executes that plan through Distill's lock and state machine with a
no-op child executor, so ingest is not launched. Report synthesis gathers the
frozen paper insight from a temp library and writes under that library, not
the repository `output/` directory.

## What this receipt is not

- Not live model or network evidence
- Not a 20-paper / 50-video / site-batch journey
- Not a PR-blocking latency gate
- Not a claim that native code is required

## Next slices

1. Linux and macOS repeats of the corpus-scale seed and these replay fixtures
2. Live reference journeys as release evidence only
