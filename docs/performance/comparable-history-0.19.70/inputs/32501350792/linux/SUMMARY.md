# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `373ee7ac541c0c40d1fcbedad3991b91b13554a1`
- Project version: `0.19.68`
- Runner: `Linux` / `X64` / `GitHub Actions 1000099917`
- Workflow run: `32501350792` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 173.3 ms | 197.4 ms | 45.3 MiB |
| search_hit | 328.4 ms | 383.6 ms | 49.2 MiB |
| search_miss | 327.3 ms | 369.8 ms | 45.4 MiB |
| check_links | 15.1 ms | 16.0 ms | 45.2 MiB |
| near_duplicates | 287.1 ms | 346.6 ms | 50.0 MiB |
| dashboard_snapshot | 295.4 ms | 341.2 ms | 45.5 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 883.3 ms | 1.02 s | 48.1 MiB |
| search_hit | 1.72 s | 1.85 s | 50.5 MiB |
| search_miss | 1.64 s | 1.77 s | 50.2 MiB |
| check_links | 64.8 ms | 65.5 ms | 45.3 MiB |
| near_duplicates | 1.43 s | 1.55 s | 69.4 MiB |
| dashboard_snapshot | 1.54 s | 1.66 s | 47.0 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.83 s | 1.99 s | 48.7 MiB |
| search_hit | 3.44 s | 3.61 s | 51.6 MiB |
| search_miss | 3.37 s | 3.52 s | 47.7 MiB |
| check_links | 126.8 ms | 134.1 ms | 45.5 MiB |
| near_duplicates | 3.02 s | 3.26 s | 91.8 MiB |
| dashboard_snapshot | 3.05 s | 3.26 s | 49.6 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 18.73 s | 19.23 s | 70.2 MiB |
| search_hit | 35.04 s | 36.25 s | 79.2 MiB |
| search_miss | 34.28 s | 36.31 s | 74.7 MiB |
| check_links | 1.27 s | 1.33 s | 48.1 MiB |
| near_duplicates | 32.34 s | 33.62 s | 482.1 MiB |
| dashboard_snapshot | 31.28 s | 32.63 s | 72.9 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 731.1 ms | 750.8 ms | 67.6 MiB |
| video_analyze | 2.9 ms | 3.0 ms | 49.7 MiB |
| site_analyze | 36.0 ms | 36.3 ms | 59.1 MiB |
| paper_synthesize | 18.1 ms | 19.0 ms | 50.8 MiB |
| verify_numeric | 1.5 ms | 1.6 ms | 49.6 MiB |
| profile_preview | 1.0 ms | 1.0 ms | 49.6 MiB |
| profile_run | 11.4 ms | 12.9 ms | 51.8 MiB |
| report_synthesize | 27.3 ms | 28.1 ms | 54.3 MiB |
