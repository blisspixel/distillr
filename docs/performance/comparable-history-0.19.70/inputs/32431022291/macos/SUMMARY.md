# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `1c72d1125fad079253b441f3595ad587f5aa4686`
- Project version: `0.19.66`
- Runner: `macOS` / `ARM64` / `GitHub Actions 1000098515`
- Workflow run: `32431022291` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 129.5 ms | 175.0 ms | 49.8 MiB |
| search_hit | 236.9 ms | 302.8 ms | 49.8 MiB |
| search_miss | 232.8 ms | 267.6 ms | 50.0 MiB |
| check_links | 13.6 ms | 15.5 ms | 49.8 MiB |
| near_duplicates | 171.4 ms | 195.9 ms | 54.4 MiB |
| dashboard_snapshot | 173.7 ms | 183.6 ms | 49.9 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 516.2 ms | 558.7 ms | 50.7 MiB |
| search_hit | 975.5 ms | 1.13 s | 50.8 MiB |
| search_miss | 964.4 ms | 1.04 s | 50.6 MiB |
| check_links | 58.9 ms | 65.3 ms | 49.9 MiB |
| near_duplicates | 836.2 ms | 908.5 ms | 75.6 MiB |
| dashboard_snapshot | 859.4 ms | 969.2 ms | 50.7 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.03 s | 1.09 s | 51.6 MiB |
| search_hit | 1.95 s | 2.00 s | 52.3 MiB |
| search_miss | 1.94 s | 2.00 s | 52.0 MiB |
| check_links | 115.6 ms | 118.0 ms | 49.5 MiB |
| near_duplicates | 1.69 s | 1.74 s | 102.7 MiB |
| dashboard_snapshot | 1.70 s | 1.78 s | 53.6 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 11.05 s | 17.26 s | 74.1 MiB |
| search_hit | 24.56 s | 33.49 s | 83.8 MiB |
| search_miss | 24.29 s | 30.10 s | 79.3 MiB |
| check_links | 1.48 s | 1.78 s | 52.2 MiB |
| near_duplicates | 18.71 s | 21.43 s | 537.8 MiB |
| dashboard_snapshot | 17.81 s | 18.15 s | 78.4 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 371.2 ms | 423.8 ms | 80.5 MiB |
| video_analyze | 1.5 ms | 1.8 ms | 54.0 MiB |
| site_analyze | 16.2 ms | 17.4 ms | 71.5 MiB |
| paper_synthesize | 11.4 ms | 13.7 ms | 54.7 MiB |
| verify_numeric | 1.2 ms | 1.5 ms | 53.8 MiB |
| profile_preview | 0.7 ms | 0.9 ms | 54.0 MiB |
| profile_run | 6.8 ms | 9.9 ms | 54.0 MiB |
| report_synthesize | 13.2 ms | 15.1 ms | 63.0 MiB |
