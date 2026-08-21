# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `1c72d1125fad079253b441f3595ad587f5aa4686`
- Project version: `0.19.66`
- Runner: `Linux` / `X64` / `GitHub Actions 1000098516`
- Workflow run: `32431022291` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 178.3 ms | 200.0 ms | 45.3 MiB |
| search_hit | 346.9 ms | 379.7 ms | 45.4 MiB |
| search_miss | 338.9 ms | 395.7 ms | 49.1 MiB |
| check_links | 15.4 ms | 16.0 ms | 45.1 MiB |
| near_duplicates | 315.4 ms | 335.0 ms | 50.0 MiB |
| dashboard_snapshot | 305.6 ms | 342.8 ms | 45.4 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 890.4 ms | 958.0 ms | 46.2 MiB |
| search_hit | 1.71 s | 1.86 s | 46.7 MiB |
| search_miss | 1.65 s | 1.88 s | 50.3 MiB |
| check_links | 64.8 ms | 69.1 ms | 45.3 MiB |
| near_duplicates | 1.50 s | 1.70 s | 69.2 MiB |
| dashboard_snapshot | 1.51 s | 1.65 s | 48.2 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.82 s | 1.95 s | 48.8 MiB |
| search_hit | 3.42 s | 3.55 s | 51.5 MiB |
| search_miss | 3.35 s | 3.53 s | 51.5 MiB |
| check_links | 126.9 ms | 128.1 ms | 45.5 MiB |
| near_duplicates | 3.02 s | 3.38 s | 92.7 MiB |
| dashboard_snapshot | 3.05 s | 3.27 s | 49.6 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 18.77 s | 19.53 s | 70.2 MiB |
| search_hit | 34.55 s | 35.95 s | 79.1 MiB |
| search_miss | 34.25 s | 35.72 s | 74.7 MiB |
| check_links | 1.28 s | 1.31 s | 48.2 MiB |
| near_duplicates | 31.96 s | 32.78 s | 482.1 MiB |
| dashboard_snapshot | 30.99 s | 32.76 s | 72.9 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 731.9 ms | 753.7 ms | 67.7 MiB |
| video_analyze | 2.9 ms | 3.0 ms | 49.6 MiB |
| site_analyze | 35.6 ms | 35.9 ms | 59.1 MiB |
| paper_synthesize | 18.2 ms | 18.7 ms | 50.8 MiB |
| verify_numeric | 1.5 ms | 1.6 ms | 49.6 MiB |
| profile_preview | 1.0 ms | 1.0 ms | 49.6 MiB |
| profile_run | 11.3 ms | 13.0 ms | 51.9 MiB |
| report_synthesize | 26.9 ms | 27.6 ms | 54.4 MiB |
