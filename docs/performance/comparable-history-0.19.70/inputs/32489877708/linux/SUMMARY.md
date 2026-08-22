# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `3f5d583ce3d6b9e1b8e40fcb869b787b6e78b166`
- Project version: `0.19.67`
- Runner: `Linux` / `X64` / `GitHub Actions 1000099304`
- Workflow run: `32489877708` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 132.9 ms | 150.5 ms | 45.3 MiB |
| search_hit | 270.1 ms | 297.3 ms | 49.2 MiB |
| search_miss | 245.3 ms | 264.2 ms | 45.3 MiB |
| check_links | 11.5 ms | 11.6 ms | 45.1 MiB |
| near_duplicates | 220.0 ms | 244.6 ms | 50.0 MiB |
| dashboard_snapshot | 224.2 ms | 273.1 ms | 45.3 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 695.2 ms | 748.7 ms | 46.3 MiB |
| search_hit | 1.27 s | 1.35 s | 46.7 MiB |
| search_miss | 1.28 s | 1.36 s | 50.3 MiB |
| check_links | 49.2 ms | 50.5 ms | 45.3 MiB |
| near_duplicates | 1.10 s | 1.20 s | 69.3 MiB |
| dashboard_snapshot | 1.15 s | 1.24 s | 48.3 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.38 s | 1.47 s | 48.6 MiB |
| search_hit | 2.60 s | 2.74 s | 52.0 MiB |
| search_miss | 2.52 s | 2.80 s | 51.5 MiB |
| check_links | 97.2 ms | 98.7 ms | 45.6 MiB |
| near_duplicates | 2.29 s | 2.51 s | 92.2 MiB |
| dashboard_snapshot | 2.31 s | 2.41 s | 47.8 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 14.17 s | 14.78 s | 69.3 MiB |
| search_hit | 26.25 s | 27.15 s | 79.1 MiB |
| search_miss | 25.99 s | 26.41 s | 74.6 MiB |
| check_links | 997.4 ms | 1.03 s | 48.2 MiB |
| near_duplicates | 25.07 s | 25.56 s | 482.0 MiB |
| dashboard_snapshot | 24.04 s | 25.40 s | 72.9 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 594.2 ms | 606.6 ms | 67.6 MiB |
| video_analyze | 2.4 ms | 2.5 ms | 49.7 MiB |
| site_analyze | 29.4 ms | 29.7 ms | 59.1 MiB |
| paper_synthesize | 15.8 ms | 16.3 ms | 51.5 MiB |
| verify_numeric | 1.5 ms | 1.6 ms | 49.6 MiB |
| profile_preview | 0.9 ms | 0.9 ms | 49.6 MiB |
| profile_run | 10.5 ms | 12.9 ms | 51.9 MiB |
| report_synthesize | 23.1 ms | 23.6 ms | 54.4 MiB |
