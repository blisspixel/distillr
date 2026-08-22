# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166`
- Project version: `0.19.67`
- Runner: `Linux` / `X64` / `GitHub Actions 1000099699`
- Workflow run: `32494705846` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 214.7 ms | 253.3 ms | 47.0 MiB |
| search_hit | 394.4 ms | 473.9 ms | 49.2 MiB |
| search_miss | 402.8 ms | 463.2 ms | 49.1 MiB |
| check_links | 16.9 ms | 18.3 ms | 45.1 MiB |
| near_duplicates | 358.2 ms | 410.8 ms | 50.0 MiB |
| dashboard_snapshot | 370.7 ms | 454.9 ms | 47.1 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.09 s | 1.26 s | 48.0 MiB |
| search_hit | 2.18 s | 2.33 s | 50.5 MiB |
| search_miss | 2.10 s | 2.43 s | 50.3 MiB |
| check_links | 72.0 ms | 74.6 ms | 45.3 MiB |
| near_duplicates | 1.76 s | 2.00 s | 69.3 MiB |
| dashboard_snapshot | 1.91 s | 2.19 s | 48.2 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 2.20 s | 2.74 s | 49.0 MiB |
| search_hit | 4.23 s | 4.80 s | 51.9 MiB |
| search_miss | 4.04 s | 4.40 s | 51.5 MiB |
| check_links | 140.5 ms | 152.1 ms | 45.5 MiB |
| near_duplicates | 3.62 s | 4.02 s | 92.7 MiB |
| dashboard_snapshot | 3.66 s | 3.94 s | 49.7 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 22.74 s | 23.56 s | 70.2 MiB |
| search_hit | 41.80 s | 42.99 s | 79.2 MiB |
| search_miss | 42.04 s | 43.72 s | 74.6 MiB |
| check_links | 1.43 s | 1.49 s | 48.2 MiB |
| near_duplicates | 38.01 s | 39.13 s | 482.1 MiB |
| dashboard_snapshot | 38.83 s | 39.69 s | 72.8 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 781.6 ms | 799.4 ms | 67.6 MiB |
| video_analyze | 3.2 ms | 3.3 ms | 49.7 MiB |
| site_analyze | 33.8 ms | 34.7 ms | 59.1 MiB |
| paper_synthesize | 20.4 ms | 23.3 ms | 50.9 MiB |
| verify_numeric | 1.7 ms | 1.8 ms | 49.5 MiB |
| profile_preview | 1.1 ms | 1.2 ms | 49.6 MiB |
| profile_run | 12.5 ms | 15.2 ms | 51.7 MiB |
| report_synthesize | 28.7 ms | 29.9 ms | 54.4 MiB |
