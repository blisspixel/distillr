# Comparable performance history

- Workflow runs: `5`
- Minimum runs per host: `5`
- Semantic compatibility: `f78c71f84cad35d1cbd363d6a0ecb8c78c48e74154b0356282044313d44b422a`
- Timing policy: `active-advisory`
- Blocking timing gate: `false`

The history uses run-level medians, not pooled samples. A timing regression requires two consecutive comparable runs that exceed both 20 percent and the measured absolute noise floor. Correctness and integrity remain blocking.

## Linux / X64

Comparable runs: `5`

| Operation | Median p50 | p50 range | CV | Noise | Advisory absolute floor |
| --- | ---: | ---: | ---: | --- | ---: |
| corpus/100/check_links | 15.1 ms | 9.8 ms to 16.9 ms | 0.193 | moderate | 5.3 ms |
| corpus/100/dashboard_snapshot | 295.4 ms | 224.2 ms to 370.7 ms | 0.177 | moderate | 147.7 ms |
| corpus/100/discover_insights | 173.3 ms | 132.9 ms to 214.7 ms | 0.173 | moderate | 93.2 ms |
| corpus/100/near_duplicates | 287.1 ms | 220.0 ms to 358.2 ms | 0.170 | moderate | 115.2 ms |
| corpus/100/search_hit | 328.4 ms | 270.1 ms to 394.4 ms | 0.141 | moderate | 146.1 ms |
| corpus/100/search_miss | 327.3 ms | 245.3 ms to 402.8 ms | 0.172 | moderate | 158.7 ms |
| corpus/1000/check_links | 126.8 ms | 84.7 ms to 140.5 ms | 0.181 | moderate | 40.9 ms |
| corpus/1000/dashboard_snapshot | 3.05 s | 2.31 s to 3.66 s | 0.168 | moderate | 1.83 s |
| corpus/1000/discover_insights | 1.82 s | 1.38 s to 2.20 s | 0.153 | moderate | 596.7 ms |
| corpus/1000/near_duplicates | 3.02 s | 2.29 s to 3.62 s | 0.161 | moderate | 1.59 s |
| corpus/1000/search_hit | 3.42 s | 2.60 s to 4.23 s | 0.171 | moderate | 1.71 s |
| corpus/1000/search_miss | 3.35 s | 2.52 s to 4.04 s | 0.158 | moderate | 1.35 s |
| corpus/10000/check_links | 1.27 s | 880.4 ms to 1.43 s | 0.172 | moderate | 473.0 ms |
| corpus/10000/dashboard_snapshot | 30.99 s | 24.04 s to 38.83 s | 0.157 | moderate | 8.07 s |
| corpus/10000/discover_insights | 18.73 s | 14.17 s to 22.74 s | 0.171 | moderate | 10.93 s |
| corpus/10000/near_duplicates | 31.96 s | 25.07 s to 38.01 s | 0.141 | moderate | 11.96 s |
| corpus/10000/search_hit | 34.55 s | 26.25 s to 41.80 s | 0.164 | moderate | 17.70 s |
| corpus/10000/search_miss | 34.25 s | 25.99 s to 42.04 s | 0.164 | moderate | 15.14 s |
| corpus/500/check_links | 64.8 ms | 42.5 ms to 72.0 ms | 0.187 | moderate | 21.7 ms |
| corpus/500/dashboard_snapshot | 1.51 s | 1.15 s to 1.91 s | 0.176 | moderate | 685.9 ms |
| corpus/500/discover_insights | 883.3 ms | 695.2 ms to 1.09 s | 0.160 | moderate | 421.1 ms |
| corpus/500/near_duplicates | 1.43 s | 1.10 s to 1.76 s | 0.158 | moderate | 512.2 ms |
| corpus/500/search_hit | 1.71 s | 1.27 s to 2.18 s | 0.192 | moderate | 958.4 ms |
| corpus/500/search_miss | 1.64 s | 1.28 s to 2.10 s | 0.175 | moderate | 741.1 ms |
| replay/paper_analyze | 731.1 ms | 594.2 ms to 781.6 ms | 0.096 | low | 151.6 ms |
| replay/paper_synthesize | 18.2 ms | 15.8 ms to 78.8 ms | 0.803 | high | 6.3 ms |
| replay/profile_preview | 1.0 ms | 0.9 ms to 1.1 ms | 0.078 | low | 1.0 ms |
| replay/profile_run | 11.4 ms | 10.5 ms to 91.4 ms | 1.168 | high | 2.7 ms |
| replay/report_synthesize | 26.9 ms | 23.1 ms to 28.7 ms | 0.083 | low | 5.5 ms |
| replay/site_analyze | 33.8 ms | 28.6 ms to 36.0 ms | 0.096 | low | 6.5 ms |
| replay/verify_numeric | 1.5 ms | 1.5 ms to 2.0 ms | 0.104 | moderate | 1.0 ms |
| replay/video_analyze | 2.9 ms | 2.4 ms to 3.2 ms | 0.097 | low | 1.0 ms |

## macOS / ARM64

Comparable runs: `5`

| Operation | Median p50 | p50 range | CV | Noise | Advisory absolute floor |
| --- | ---: | ---: | ---: | --- | ---: |
| corpus/100/check_links | 17.1 ms | 13.6 ms to 18.1 ms | 0.097 | low | 2.0 ms |
| corpus/100/dashboard_snapshot | 205.8 ms | 173.7 ms to 299.8 ms | 0.236 | moderate | 96.2 ms |
| corpus/100/discover_insights | 155.6 ms | 129.5 ms to 186.3 ms | 0.123 | moderate | 60.1 ms |
| corpus/100/near_duplicates | 223.6 ms | 171.4 ms to 247.1 ms | 0.146 | moderate | 70.5 ms |
| corpus/100/search_hit | 300.9 ms | 236.9 ms to 358.6 ms | 0.140 | moderate | 100.4 ms |
| corpus/100/search_miss | 282.6 ms | 232.8 ms to 315.7 ms | 0.127 | moderate | 99.4 ms |
| corpus/1000/check_links | 136.9 ms | 115.6 ms to 166.8 ms | 0.125 | moderate | 31.5 ms |
| corpus/1000/dashboard_snapshot | 2.11 s | 1.70 s to 2.49 s | 0.120 | moderate | 252.4 ms |
| corpus/1000/discover_insights | 1.43 s | 1.03 s to 1.74 s | 0.178 | moderate | 591.7 ms |
| corpus/1000/near_duplicates | 2.08 s | 1.69 s to 2.38 s | 0.109 | moderate | 227.4 ms |
| corpus/1000/search_hit | 2.54 s | 1.95 s to 3.18 s | 0.158 | moderate | 592.4 ms |
| corpus/1000/search_miss | 2.46 s | 1.94 s to 2.91 s | 0.131 | moderate | 553.5 ms |
| corpus/10000/check_links | 1.58 s | 1.46 s to 1.62 s | 0.041 | low | 101.0 ms |
| corpus/10000/dashboard_snapshot | 20.19 s | 17.81 s to 22.70 s | 0.087 | low | 5.75 s |
| corpus/10000/discover_insights | 12.83 s | 11.05 s to 15.34 s | 0.120 | moderate | 4.13 s |
| corpus/10000/near_duplicates | 21.63 s | 18.71 s to 23.49 s | 0.081 | low | 4.13 s |
| corpus/10000/search_hit | 22.91 s | 20.60 s to 28.80 s | 0.127 | moderate | 6.03 s |
| corpus/10000/search_miss | 24.37 s | 24.26 s to 27.92 s | 0.056 | low | 328.5 ms |
| corpus/500/check_links | 60.6 ms | 58.9 ms to 83.3 ms | 0.155 | moderate | 5.1 ms |
| corpus/500/dashboard_snapshot | 1.10 s | 859.4 ms to 1.50 s | 0.198 | moderate | 617.9 ms |
| corpus/500/discover_insights | 631.5 ms | 516.2 ms to 1.18 s | 0.338 | high | 345.7 ms |
| corpus/500/near_duplicates | 945.2 ms | 836.2 ms to 1.35 s | 0.211 | moderate | 326.9 ms |
| corpus/500/search_hit | 1.45 s | 975.5 ms to 1.52 s | 0.182 | moderate | 216.1 ms |
| corpus/500/search_miss | 1.17 s | 964.4 ms to 1.48 s | 0.180 | moderate | 614.2 ms |
| replay/paper_analyze | 456.1 ms | 371.2 ms to 478.0 ms | 0.101 | moderate | 65.6 ms |
| replay/paper_synthesize | 15.0 ms | 11.4 ms to 15.5 ms | 0.131 | moderate | 1.7 ms |
| replay/profile_preview | 0.9 ms | 0.7 ms to 1.0 ms | 0.113 | moderate | 1.0 ms |
| replay/profile_run | 7.9 ms | 6.8 ms to 11.2 ms | 0.177 | moderate | 3.2 ms |
| replay/report_synthesize | 14.7 ms | 13.1 ms to 17.0 ms | 0.116 | moderate | 4.6 ms |
| replay/site_analyze | 18.9 ms | 16.2 ms to 21.4 ms | 0.108 | moderate | 7.6 ms |
| replay/verify_numeric | 1.3 ms | 1.2 ms to 1.6 ms | 0.124 | moderate | 1.0 ms |
| replay/video_analyze | 1.7 ms | 1.5 ms to 1.8 ms | 0.069 | low | 1.0 ms |
