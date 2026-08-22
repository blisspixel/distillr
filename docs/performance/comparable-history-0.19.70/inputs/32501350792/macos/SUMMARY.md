# Cross-platform performance evidence

- Repository: `blisspixel/distillr`
- Commit: `373ee7ac541c0c40d1fcbedad3991b91b13554a1`
- Project version: `0.19.68`
- Runner: `macOS` / `ARM64` / `GitHub Actions 1000099918`
- Workflow run: `32501350792` attempt `1`
- Samples: 20 measured plus 1 warmup
- Network and live model use: none

Timing is advisory. Receipt integrity, source integrity, operation completion,
sample count, and stable result digests are validated before this summary is written.

## Corpus scale 100

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 175.7 ms | 218.1 ms | 49.8 MiB |
| search_hit | 312.1 ms | 432.2 ms | 50.0 MiB |
| search_miss | 315.7 ms | 384.4 ms | 49.9 MiB |
| check_links | 18.1 ms | 25.8 ms | 49.9 MiB |
| near_duplicates | 223.6 ms | 243.9 ms | 54.3 MiB |
| dashboard_snapshot | 205.8 ms | 310.7 ms | 50.0 MiB |

## Corpus scale 500

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 631.5 ms | 724.7 ms | 50.7 MiB |
| search_hit | 1.45 s | 1.80 s | 50.9 MiB |
| search_miss | 1.17 s | 1.49 s | 50.8 MiB |
| check_links | 60.2 ms | 72.6 ms | 49.9 MiB |
| near_duplicates | 945.2 ms | 1.08 s | 76.1 MiB |
| dashboard_snapshot | 987.4 ms | 1.39 s | 50.9 MiB |

## Corpus scale 1,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 1.23 s | 1.49 s | 52.0 MiB |
| search_hit | 2.39 s | 2.98 s | 52.3 MiB |
| search_miss | 2.54 s | 2.79 s | 51.8 MiB |
| check_links | 136.9 ms | 178.4 ms | 49.9 MiB |
| near_duplicates | 2.12 s | 2.52 s | 101.3 MiB |
| dashboard_snapshot | 2.03 s | 2.58 s | 53.8 MiB |

## Corpus scale 10,000

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| discover_insights | 13.53 s | 16.93 s | 74.2 MiB |
| search_hit | 22.91 s | 27.97 s | 83.6 MiB |
| search_miss | 24.37 s | 28.10 s | 79.1 MiB |
| check_links | 1.58 s | 1.72 s | 52.8 MiB |
| near_duplicates | 21.63 s | 28.39 s | 542.3 MiB |
| dashboard_snapshot | 18.27 s | 23.20 s | 78.2 MiB |

## Frozen workflow replay

| Operation | p50 wall | p95 wall | Peak RSS |
|---|---:|---:|---:|
| paper_analyze | 473.0 ms | 633.0 ms | 80.7 MiB |
| video_analyze | 1.8 ms | 2.1 ms | 54.2 MiB |
| site_analyze | 21.4 ms | 24.9 ms | 71.6 MiB |
| paper_synthesize | 15.0 ms | 20.1 ms | 54.9 MiB |
| verify_numeric | 1.5 ms | 2.0 ms | 54.0 MiB |
| profile_preview | 1.0 ms | 1.2 ms | 53.8 MiB |
| profile_run | 11.2 ms | 19.1 ms | 54.0 MiB |
| report_synthesize | 17.0 ms | 24.4 ms | 63.6 MiB |
