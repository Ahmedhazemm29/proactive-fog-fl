# Reactive vs proactive, repeated runs

Repeats: reactive: 3 runs, proactive: 3 runs. Values are mean ± standard deviation across the repeats.

Unmet demand = average throttled CPU (time per second a worker waited because
its limit was used up). Demand = CPU used + unmet demand. Totals add up both
workers. CPU values are Prometheus 30 s rates sampled every 5 s; training
speed is the average of the workers' 10 s log reports.

## Mean ± standard deviation

| Controller | Worker | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---|---:|---:|---:|---:|
| reactive | Worker 1 | 0.597 ± 0.001 | 0.286 ± 0.028 | 0.311 ± 0.029 | 157.4 ± 15.4 |
| reactive | Worker 2 | 0.594 ± 0.001 | 0.303 ± 0.026 | 0.291 ± 0.028 | 165.5 ± 15.0 |
| reactive | **Total** | 1.191 ± 0.000 | 0.590 ± 0.003 | 0.602 ± 0.003 | 322.9 ± 3.8 |
| proactive | Worker 1 | 0.603 ± 0.010 | 0.364 ± 0.004 | 0.239 ± 0.007 | 202.4 ± 3.4 |
| proactive | Worker 2 | 0.596 ± 0.009 | 0.373 ± 0.008 | 0.223 ± 0.001 | 204.6 ± 1.7 |
| proactive | **Total** | 1.199 ± 0.019 | 0.737 ± 0.012 | 0.462 ± 0.007 | 407.0 ± 5.0 |

## Proactive compared with reactive

| Metric (total) | Reactive | Proactive | Difference |
|---|---:|---:|---:|
| Demand (CPU) | 1.191 | 1.199 | +0.008 (+1%) |
| CPU used (CPU) | 0.590 | 0.737 | +0.147 (+25%) |
| Unmet demand (CPU) | 0.602 | 0.462 | -0.139 (-23%) |
| Training speed (steps/s) | 322.9 | 407.0 | +84.1 (+26%) |

## Every run (totals)

| Controller | Repeat | Start | Length | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---:|---|---:|---:|---:|---:|---:|
| reactive | 1 | 2026-10-05 00:06 | 600 s | 1.191 | 0.589 | 0.603 | 319.9 |
| proactive | 1 | 2026-10-05 00:17 | 600 s | 1.210 | 0.744 | 0.466 | 401.3 |
| reactive | 2 | 2026-10-05 00:28 | 601 s | 1.191 | 0.587 | 0.604 | 321.4 |
| proactive | 2 | 2026-10-05 00:39 | 601 s | 1.177 | 0.723 | 0.454 | 409.5 |
| reactive | 3 | 2026-10-05 00:50 | 601 s | 1.192 | 0.593 | 0.598 | 327.2 |
| proactive | 3 | 2026-10-05 01:01 | 601 s | 1.210 | 0.743 | 0.467 | 410.2 |
