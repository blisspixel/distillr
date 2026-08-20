# Performance baseline (0.19.60, partial)

Status: **published offline Windows canonical matrix at 100, 500, 1_000, and
10_000** with n=20. Live reference journeys, frozen workflow replays, and
multi-host history remain open. Policy:
[`../design/performance-and-language-admission.md`](../design/performance-and-language-admission.md).
Plan: [`../design/path-to-1.0.md`](../design/path-to-1.0.md). Prior published
slice: [`baseline-0.19.50.md`](baseline-0.19.50.md).

## Environment

| Field | Value |
|-------|-------|
| Project version | 0.19.60 |
| OS | Windows 11, AMD64 (16 logical CPUs) |
| Processor | AMD64 Family 25 Model 116 Stepping 1 |
| Python | CPython 3.12.10 |
| Filesystem state | warm-generated (OS page cache) |
| Harness | `python -m benchmarks.corpus_scale` |
| Seed | `20260711` |
| Samples | 20 per operation, fresh child process each |
| Integrity | corpus digest unchanged across each suite |

This is a different host class from the 0.19.50 Windows baseline (32 logical
CPUs, Family 25 Model 33, CPython 3.12.13). Wall times are not a same-machine
speedup claim. The comparable claim is **result identity** at scale 100: every
operation digest matches the 0.19.50 receipt on a corpus whose digest is also
unchanged.

## Scale 100

Raw result:
[`corpus-scale-100-windows-0.19.60.json`](corpus-scale-100-windows-0.19.60.json)

Reproduce:

```console
uv run --no-sync python -m benchmarks.corpus_scale --scale 100 --iterations 20 --timeout-seconds 60
```

Corpus: 404 files, 758_863 bytes, 100 insights, digest
`1ced3c34c831824d…` (identical to 0.19.50).

Nearest-rank quantiles on wall time. p95 is reported only because n=20.

| Operation | p50 wall | p95 wall | Result digest (prefix) |
|-----------|---------:|---------:|------------------------|
| discover_insights | 445 ms | 555 ms | `27efce676f42` |
| search_hit | 789 ms | 906 ms | `0cfe42b183d5` |
| search_miss | 760 ms | 810 ms | `4f53cda18c2b` |
| check_links | 40 ms | 44 ms | `5b3a35fe53c8` |
| near_duplicates | 625 ms | 701 ms | `47ab80898c75` |
| dashboard_snapshot | 841 ms | 913 ms | `63ef606995fd` |

Peak RSS stayed under ~57 MiB. Every result digest matches the 0.19.50
scale-100 receipt, including near-duplicate clustering identity
`47ab80898c75…`.

## Scale 500

Raw result:
[`corpus-scale-500-windows-0.19.60.json`](corpus-scale-500-windows-0.19.60.json)

Reproduce:

```console
uv run --no-sync python -m benchmarks.corpus_scale --scale 500 --iterations 20 --timeout-seconds 60
```

Corpus: 2_004 files, 3_952_377 bytes, 500 insights, digest
`dd65faf7d1944039…`.

| Operation | p50 wall | p95 wall | Result digest (prefix) |
|-----------|---------:|---------:|------------------------|
| discover_insights | 1915 ms | 2176 ms | `2ccb9c41e89a` |
| search_hit | 4187 ms | 5951 ms | `c32c261617e7` |
| search_miss | 3693 ms | 3981 ms | `4f53cda18c2b` |
| check_links | 173 ms | 196 ms | `67cc8917cafe` |
| near_duplicates | 2903 ms | 3080 ms | `08e200009ea2` |
| dashboard_snapshot | 3766 ms | 4217 ms | `2ca1837aaa09` |

Peak RSS stayed under ~73 MiB (near-duplicates). Search-miss digest
`4f53cda18c2b…` is the empty-result digest also recorded at scale 100.

## Scale 1_000

Raw result:
[`corpus-scale-1000-windows-0.19.60.json`](corpus-scale-1000-windows-0.19.60.json)

Reproduce:

```console
uv run --no-sync python -m benchmarks.corpus_scale --scale 1000 --iterations 20 --timeout-seconds 120
```

Corpus: 4_004 files, 7_941_226 bytes, 1_000 insights, digest
`d36c5be230107941…`. Sample timeout was 120s for headroom; every sample
finished well under 10s.

| Operation | p50 wall | p95 wall | Result digest (prefix) |
|-----------|---------:|---------:|------------------------|
| discover_insights | 3956 ms | 4917 ms | `a36acdd29e7b` |
| search_hit | 6966 ms | 7205 ms | `c32c261617e7` |
| search_miss | 6987 ms | 7242 ms | `4f53cda18c2b` |
| check_links | 340 ms | 378 ms | `e17ad5516eee` |
| near_duplicates | 6302 ms | 7707 ms | `a62dc9a347d2` |
| dashboard_snapshot | 7754 ms | 8385 ms | `da92b66d3ca9` |

Peak RSS stayed under ~96 MiB (near-duplicates). Search-hit digest
`c32c261617e7…` matches scale 500 because the harness ranks a capped 25-hit
window; search-miss remains the empty-result digest.

## Scale 10_000

Raw result:
[`corpus-scale-10000-windows-0.19.60.json`](corpus-scale-10000-windows-0.19.60.json)

Reproduce:

```console
uv run --no-sync python -m benchmarks.corpus_scale --scale 10000 --iterations 20 --timeout-seconds 300
```

Corpus: 40_004 files, 83_006_286 bytes, 10_000 insights, digest
`ad8d8d7bafc438f0…`. Sample timeout was 300s; the slowest sample was
190.7s (dashboard snapshot). Wall times here are in seconds.

| Operation | p50 wall | p95 wall | Result digest (prefix) |
|-----------|---------:|---------:|------------------------|
| discover_insights | 38.4 s | 49.9 s | `104903b87e80` |
| search_hit | 69.3 s | 73.1 s | `c32c261617e7` |
| search_miss | 65.9 s | 83.7 s | `4f53cda18c2b` |
| check_links | 3.1 s | 3.1 s | `c1a8f4f72a55` |
| near_duplicates | 124.1 s | 156.0 s | `2821024befd2` |
| dashboard_snapshot | 122.2 s | 185.9 s | `f17e5f5fe318` |

Peak RSS reached ~550 MiB on near-duplicates. Search-hit digest
`c32c261617e7…` still matches scale 500 and 1_000 (capped 25-hit window).
Search-miss remains the empty-result digest. Near-duplicate and dashboard
p50 values on this long run were higher than a 1-iteration probe on the
same host; report the n=20 receipt, not the probe.

## CLI cold-ish start

Seven warmed `python -m distill --version` process launches on the same machine
(first launch discarded):

| Metric | Value |
|--------|------:|
| Median | 840 ms |
| Max observed | 920 ms |

This is process spawn + import path, not interactive TTY help. The lazy-import
work in 0.19.45 remains the relevant prior art for reducing this.

## What this baseline is not

- Not cold-filesystem evidence
- Not multi-host comparable history
- Not live provider journeys (20-paper / 50-video / site-batch)
- Not a PR-blocking regression gate
- Not a claim that native code is required
- Not a same-machine comparison against 0.19.50 wall times

## Next baseline slices (still required for 1.0)

1. Linux and macOS repeats of the same seed for runner-variance history
2. Frozen profile and report replays shipped in [`workflow-replay-0.19.63.md`](workflow-replay-0.19.63.md)
3. Scheduled live reference journeys as release evidence only
