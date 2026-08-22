# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166`
- Project version: `0.19.67`
- Runner: `macOS` / `ARM64` / `GitHub Actions 1000099698`
- Workflow run: `32494705846` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 153.2 ms | 288.1 ms | 49.8 MiB |
| search_hit | 267.4 ms | 317.0 ms | 50.0 MiB |
| search_miss | 233.7 ms | 279.9 ms | 50.0 MiB |
| check_links | 16.8 ms | 21.5 ms | 50.0 MiB |
| near_duplicates | 247.1 ms | 393.3 ms | 54.0 MiB |
| dashboard_snapshot | 289.0 ms | 376.7 ms | 49.9 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 906.5 ms | 1.23 s | 50.5 MiB |
| search_hit | 1.52 s | 1.81 s | 50.9 MiB |
| search_miss | 1.48 s | 1.81 s | 50.6 MiB |
| check_links | 79.6 ms | 126.7 ms | 50.0 MiB |
| near_duplicates | 1.33 s | 1.71 s | 76.1 MiB |
| dashboard_snapshot | 1.50 s | 1.80 s | 50.9 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.74 s | 1.90 s | 51.9 MiB |
| search_hit | 3.18 s | 3.45 s | 52.3 MiB |
| search_miss | 2.46 s | 3.38 s | 51.7 MiB |
| check_links | 141.6 ms | 176.7 ms | 49.8 MiB |
| near_duplicates | 2.08 s | 2.43 s | 102.6 MiB |
| dashboard_snapshot | 2.11 s | 2.63 s | 53.8 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 11.46 s | 14.89 s | 74.1 MiB |
| search_hit | 20.60 s | 26.09 s | 83.8 MiB |
| search_miss | 27.92 s | 40.75 s | 79.2 MiB |
| check_links | 1.59 s | 1.82 s | 52.2 MiB |
| near_duplicates | 20.26 s | 21.00 s | 541.7 MiB |
| dashboard_snapshot | 20.19 s | 24.14 s | 78.4 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 456.1 ms | 573.8 ms | 80.5 MiB |
| video_analyze | 1.7 ms | 1.9 ms | 54.0 MiB |
| site_analyze | 18.9 ms | 22.2 ms | 71.3 MiB |
| paper_synthesize | 15.0 ms | 21.4 ms | 54.7 MiB |
| verify_numeric | 1.3 ms | 1.7 ms | 53.9 MiB |
| profile_preview | 0.9 ms | 1.1 ms | 54.0 MiB |
| profile_run | 7.7 ms | 12.1 ms | 54.3 MiB |
| report_synthesize | 17.0 ms | 21.2 ms | 63.4 MiB |
