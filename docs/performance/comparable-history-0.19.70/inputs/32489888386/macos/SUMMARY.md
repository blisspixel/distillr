# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166`
- Project version: `0.19.67`
- Runner: `macOS` / `ARM64` / `GitHub Actions 1000099511`
- Workflow run: `32489888386` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 186.3 ms | 220.9 ms | 49.9 MiB |
| search_hit | 358.6 ms | 408.3 ms | 49.9 MiB |
| search_miss | 304.7 ms | 383.4 ms | 49.9 MiB |
| check_links | 17.1 ms | 19.4 ms | 49.9 MiB |
| near_duplicates | 178.5 ms | 254.4 ms | 54.3 MiB |
| dashboard_snapshot | 179.2 ms | 231.5 ms | 49.9 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 535.6 ms | 592.3 ms | 50.7 MiB |
| search_hit | 1.03 s | 1.11 s | 50.9 MiB |
| search_miss | 1.01 s | 1.11 s | 50.4 MiB |
| check_links | 60.6 ms | 69.2 ms | 49.6 MiB |
| near_duplicates | 874.8 ms | 964.7 ms | 75.3 MiB |
| dashboard_snapshot | 1.10 s | 1.30 s | 50.8 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.43 s | 1.67 s | 51.7 MiB |
| search_hit | 2.73 s | 3.66 s | 52.4 MiB |
| search_miss | 2.91 s | 3.29 s | 51.8 MiB |
| check_links | 166.8 ms | 260.5 ms | 49.8 MiB |
| near_duplicates | 2.38 s | 2.75 s | 103.1 MiB |
| dashboard_snapshot | 2.49 s | 2.72 s | 54.0 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 15.34 s | 16.29 s | 74.1 MiB |
| search_hit | 28.80 s | 34.21 s | 83.9 MiB |
| search_miss | 24.87 s | 29.51 s | 79.1 MiB |
| check_links | 1.62 s | 2.28 s | 52.4 MiB |
| near_duplicates | 23.49 s | 26.44 s | 540.8 MiB |
| dashboard_snapshot | 22.70 s | 27.67 s | 78.4 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 478.0 ms | 541.7 ms | 80.6 MiB |
| video_analyze | 1.7 ms | 2.4 ms | 54.1 MiB |
| site_analyze | 19.5 ms | 25.2 ms | 71.3 MiB |
| paper_synthesize | 15.5 ms | 19.4 ms | 54.6 MiB |
| verify_numeric | 1.6 ms | 2.2 ms | 54.1 MiB |
| profile_preview | 0.9 ms | 1.5 ms | 54.0 MiB |
| profile_run | 9.0 ms | 11.7 ms | 53.7 MiB |
| report_synthesize | 14.7 ms | 19.3 ms | 63.3 MiB |
