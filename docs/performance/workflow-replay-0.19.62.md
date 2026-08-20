# Workflow replay (0.19.62, partial)

Status: **published offline Windows evidence** for frozen paper, video, site,
synthesis, and numeric-verify paths. Live provider journeys and multi-host
history remain open. Policy:
[`../design/performance-and-language-admission.md`](../design/performance-and-language-admission.md).
Plan: [`../design/path-to-1.0.md`](../design/path-to-1.0.md).

This layer complements the corpus-scale matrix. Corpus-scale measures read
paths over a generated library. Workflow replay measures Distill-owned write
and analysis paths with frozen receipts and a deterministic model stub, and
splits wall time into Distill-owned overhead versus simulated provider wait.

## Environment

| Field | Value |
|-------|-------|
| Project version | 0.19.62 |
| OS | Windows 11, AMD64 (16 logical CPUs) |
| Processor | AMD64 Family 25 Model 116 Stepping 1 |
| Python | CPython 3.12.10 |
| Harness | `python -m benchmarks.workflow_replay` |
| Samples | 20 per operation, fresh child process each |
| Network | fail-closed (public sockets refused) |
| Provider | deterministic stub (`replay-stub`) |
| Simulated provider wait | 0 ns |
| Integrity | source fingerprint unchanged; fixture digest stable |

Raw result:
[`workflow-replay-windows-0.19.62.json`](workflow-replay-windows-0.19.62.json)

Reproduce:

```console
uv run --no-sync python -m benchmarks.workflow_replay --iterations 20 --timeout-seconds 30
```

## Offline workflow operations

Nearest-rank quantiles. p95 is reported only because n=20. Provider wait is
zero in this receipt, so Distill-owned wall equals total wall. `--wait-ns`
injects a known sleep into each stubbed model call when you need to prove the
split.

| Operation | p50 Distill-owned | p95 wall | Peak RSS | Result digest (prefix) |
|-----------|------------------:|---------:|---------:|------------------------|
| paper_analyze | 720 ms | 794 ms | 65 MiB | `3a5dc9851d77` |
| video_analyze | 4.3 ms | 4.8 ms | 49 MiB | `a8e9ab1c466f` |
| site_analyze | 8.3 ms | 8.7 ms | 50 MiB | `4786f2d22d59` |
| paper_synthesize | 47.5 ms | 57.9 ms | 53 MiB | `a1c312be6f90` |
| verify_numeric | 3.5 ms | 4.1 ms | 49 MiB | `59f70f82cde2` |

Paper analysis is the slow path because it builds the full PDF-backed receipt
document and constructs routing metadata before the stubbed model call.
Numeric verify is the always-on Distill-owned kernel; optional entailment is
held out so this receipt does not depend on `distillr[entailment]`.

Fixture digest `b350b34377d80be0…` is the hash of the frozen receipts. Result
digests were identical to a 1-iteration probe on the same host.

## What this receipt is not

- Not live model or network evidence
- Not a 20-paper / 50-video / site-batch journey
- Not profile or report replay (those remain follow-on)
- Not a PR-blocking latency gate
- Not a claim that native code is required

## Next slices

1. Linux and macOS repeats of this seed-free fixture set
2. Frozen profile and report replays
3. Live reference journeys as release evidence only
