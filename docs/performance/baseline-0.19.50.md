# Performance baseline (0.19.50, partial)

Status: **published offline scale-100 evidence**, not the complete 1.0 baseline.
Live reference journeys and multi-host history remain open. Policy:
[`../design/performance-and-language-admission.md`](../design/performance-and-language-admission.md).
Plan: [`../design/path-to-1.0.md`](../design/path-to-1.0.md).

## Environment

| Field | Value |
|-------|-------|
| Project version | 0.19.50 |
| OS | Windows 11, AMD64 (32 logical CPUs) |
| Python | CPython 3.12.13 |
| Filesystem state | warm-generated (OS page cache) |
| Harness | `python -m benchmarks.corpus_scale` |
| Scale | 100 insights, fixed seed `20260711` |
| Samples | 20 per operation, fresh child process each |
| Integrity | corpus digest unchanged across suite |

Raw result:
[`corpus-scale-100-windows-0.19.50.json`](corpus-scale-100-windows-0.19.50.json)

Reproduce:

```console
uv run --no-sync python -m benchmarks.corpus_scale --scale 100 --iterations 20 --timeout-seconds 60
```

## Offline deterministic operations (scale 100)

Nearest-rank quantiles on wall time. p95 is reported only because n=20.

| Operation | p50 wall | p95 wall | Result digest (prefix) |
|-----------|---------:|---------:|------------------------|
| discover_insights | 722 ms | 761 ms | `27efce676f42` |
| search_hit | 1485 ms | 1693 ms | `0cfe42b183d5` |
| search_miss | 1527 ms | 1569 ms | `4f53cda18c2b` |
| check_links | 66 ms | 72 ms | `5b3a35fe53c8` |
| near_duplicates | 1263 ms | 1347 ms | `47ab80898c75` |
| dashboard_snapshot | 1381 ms | 1419 ms | `63ef606995fd` |

Peak RSS across samples stayed under ~61 MiB for these operations. Timings are
**advisory** until at least five comparable historical runs exist on more than
one machine class.

Near-duplicate digest `47ab80898c75…` matches the algorithm-index work noted
in the performance admission design doc for scale-100 clustering identity.

## CLI cold-ish start

Seven warmed `python -m distill --version` process launches on the same machine
(first launch discarded):

| Metric | Value |
|--------|------:|
| Median | 955 ms |
| Max observed | 1027 ms |

This is process spawn + import path, not interactive TTY help. The lazy-import
work in 0.19.45 remains the relevant prior art for reducing this.

## What this baseline is not

- Not cold-filesystem evidence
- Not multi-host comparable history
- Not live provider journeys (20-paper / 50-video / site-batch)
- Not a PR-blocking regression gate
- Not a claim that native code is required

## Next baseline slices (still required for 1.0)

1. Scale 500 / 1_000 / 10_000 with operation-specific timeouts and n>=20
2. Linux and macOS repeats of the same seed for runner-variance history
3. Frozen offline workflow replays with provider stubs
4. Scheduled live reference journeys as release evidence only
