# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166`
- Project version: `0.19.67`
- Runner: `Linux` / `X64` / `GitHub Actions 1000099506`
- Workflow run: `32489888386` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 142.3 ms | 165.7 ms | 45.3 MiB |
| search_hit | 279.7 ms | 324.3 ms | 45.4 MiB |
| search_miss | 274.4 ms | 326.6 ms | 49.1 MiB |
| check_links | 9.8 ms | 10.2 ms | 45.1 MiB |
| near_duplicates | 248.7 ms | 279.9 ms | 50.0 MiB |
| dashboard_snapshot | 246.2 ms | 279.0 ms | 47.1 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 742.9 ms | 845.6 ms | 47.7 MiB |
| search_hit | 1.39 s | 1.50 s | 46.7 MiB |
| search_miss | 1.39 s | 1.48 s | 46.5 MiB |
| check_links | 42.5 ms | 44.2 ms | 45.3 MiB |
| near_duplicates | 1.26 s | 1.31 s | 69.1 MiB |
| dashboard_snapshot | 1.29 s | 1.40 s | 48.3 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.62 s | 1.70 s | 49.3 MiB |
| search_hit | 2.85 s | 3.23 s | 51.9 MiB |
| search_miss | 2.90 s | 3.20 s | 51.5 MiB |
| check_links | 84.7 ms | 87.9 ms | 45.5 MiB |
| near_duplicates | 2.49 s | 2.61 s | 92.7 MiB |
| dashboard_snapshot | 2.44 s | 2.62 s | 49.6 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 15.09 s | 15.62 s | 70.2 MiB |
| search_hit | 28.65 s | 30.17 s | 79.1 MiB |
| search_miss | 29.20 s | 31.10 s | 74.6 MiB |
| check_links | 880.4 ms | 899.5 ms | 48.1 MiB |
| near_duplicates | 27.98 s | 28.52 s | 482.3 MiB |
| dashboard_snapshot | 28.30 s | 29.45 s | 73.0 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 648.8 ms | 684.9 ms | 67.7 MiB |
| video_analyze | 2.6 ms | 2.9 ms | 49.7 MiB |
| site_analyze | 28.6 ms | 29.6 ms | 60.8 MiB |
| paper_synthesize | 78.8 ms | 207.5 ms | 50.8 MiB |
| verify_numeric | 2.0 ms | 34.8 ms | 49.6 MiB |
| profile_preview | 1.0 ms | 1.1 ms | 49.6 MiB |
| profile_run | 91.4 ms | 227.9 ms | 51.8 MiB |
| report_synthesize | 23.7 ms | 24.1 ms | 54.4 MiB |
