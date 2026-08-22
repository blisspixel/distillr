# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166`
- Project version: `0.19.67`
- Runner: `macOS` / `ARM64` / `GitHub Actions 1000099305`
- Workflow run: `32489877708` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 155.6 ms | 184.4 ms | 49.9 MiB |
| search_hit | 300.9 ms | 421.3 ms | 49.9 MiB |
| search_miss | 282.6 ms | 353.8 ms | 49.9 MiB |
| check_links | 17.8 ms | 21.9 ms | 50.0 MiB |
| near_duplicates | 237.8 ms | 319.0 ms | 54.2 MiB |
| dashboard_snapshot | 299.8 ms | 405.7 ms | 49.9 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.18 s | 1.49 s | 50.7 MiB |
| search_hit | 1.47 s | 1.77 s | 50.9 MiB |
| search_miss | 1.47 s | 2.02 s | 50.7 MiB |
| check_links | 83.3 ms | 113.9 ms | 49.6 MiB |
| near_duplicates | 1.35 s | 1.98 s | 75.9 MiB |
| dashboard_snapshot | 1.30 s | 1.62 s | 50.9 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.58 s | 2.03 s | 51.8 MiB |
| search_hit | 2.54 s | 3.36 s | 52.3 MiB |
| search_miss | 2.28 s | 3.32 s | 51.7 MiB |
| check_links | 126.4 ms | 138.8 ms | 49.7 MiB |
| near_duplicates | 2.00 s | 2.45 s | 102.9 MiB |
| dashboard_snapshot | 2.15 s | 2.44 s | 53.8 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 12.83 s | 17.18 s | 74.3 MiB |
| search_hit | 20.90 s | 26.00 s | 83.6 MiB |
| search_miss | 24.26 s | 27.24 s | 79.2 MiB |
| check_links | 1.46 s | 1.56 s | 52.5 MiB |
| near_duplicates | 22.84 s | 26.24 s | 538.0 MiB |
| dashboard_snapshot | 20.21 s | 24.48 s | 78.6 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 391.5 ms | 537.4 ms | 80.8 MiB |
| video_analyze | 1.5 ms | 2.0 ms | 54.2 MiB |
| site_analyze | 16.2 ms | 19.6 ms | 71.5 MiB |
| paper_synthesize | 11.7 ms | 13.6 ms | 54.7 MiB |
| verify_numeric | 1.2 ms | 1.6 ms | 53.8 MiB |
| profile_preview | 0.7 ms | 0.9 ms | 54.1 MiB |
| profile_run | 7.9 ms | 10.2 ms | 54.0 MiB |
| report_synthesize | 13.1 ms | 13.6 ms | 63.4 MiB |
