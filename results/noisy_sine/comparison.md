# Reactive vs proactive, repeated runs

Repeats: reactive: 3 runs, proactive: 3 runs. Values are mean ± standard deviation across the repeats.

Unmet demand = average throttled CPU (time per second a worker waited because
its limit was used up). Demand = CPU used + unmet demand. Totals add up both
workers. CPU values are Prometheus 30 s rates sampled every 5 s; training
speed is the average of the workers' 10 s log reports.

## Mean ± standard deviation

| Controller | Worker | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---|---:|---:|---:|---:|
| reactive | Worker 1 | 0.576 ± 0.003 | 0.223 ± 0.009 | 0.353 ± 0.010 | 121.6 ± 4.7 |
| reactive | Worker 2 | 0.585 ± 0.002 | 0.323 ± 0.003 | 0.262 ± 0.003 | 178.6 ± 1.9 |
| reactive | **Total** | 1.161 ± 0.005 | 0.546 ± 0.006 | 0.615 ± 0.007 | 300.3 ± 2.9 |
| proactive | Worker 1 | 0.574 ± 0.009 | 0.343 ± 0.003 | 0.231 ± 0.006 | 194.5 ± 1.1 |
| proactive | Worker 2 | 0.586 ± 0.011 | 0.356 ± 0.008 | 0.231 ± 0.003 | 197.3 ± 1.9 |
| proactive | **Total** | 1.161 ± 0.020 | 0.699 ± 0.012 | 0.462 ± 0.009 | 391.8 ± 1.2 |

## Proactive compared with reactive

| Metric (total) | Reactive | Proactive | Difference |
|---|---:|---:|---:|
| Demand (CPU) | 1.161 | 1.161 | -0.000 (-0%) |
| CPU used (CPU) | 0.546 | 0.699 | +0.153 (+28%) |
| Unmet demand (CPU) | 0.615 | 0.462 | -0.153 (-25%) |
| Training speed (steps/s) | 300.3 | 391.8 | +91.5 (+30%) |

## Every run (totals)

| Controller | Repeat | Start | Length | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---:|---|---:|---:|---:|---:|---:|
| reactive | 1 | 2026-10-04 19:48 | 601 s | 1.163 | 0.553 | 0.610 | 302.6 |
| proactive | 1 | 2026-10-04 19:59 | 601 s | 1.174 | 0.706 | 0.468 | 391.2 |
| reactive | 2 | 2026-10-04 20:10 | 600 s | 1.165 | 0.542 | 0.623 | 297.1 |
| proactive | 2 | 2026-10-04 20:21 | 600 s | 1.170 | 0.705 | 0.465 | 393.1 |
| reactive | 3 | 2026-10-04 20:32 | 601 s | 1.155 | 0.544 | 0.611 | 301.2 |
| proactive | 3 | 2026-10-04 20:43 | 601 s | 1.137 | 0.686 | 0.452 | 391.0 |
