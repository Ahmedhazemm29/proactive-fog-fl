# Reactive vs proactive, repeated runs

Repeats: reactive: 3 runs, proactive: 3 runs. Values are mean ± standard deviation across the repeats.

Unmet demand = average throttled CPU (time per second a worker waited because
its limit was used up). Demand = CPU used + unmet demand. Totals add up both
workers. CPU values are Prometheus 30 s rates sampled every 5 s; training
speed is the average of the workers' 10 s log reports.

## Mean ± standard deviation

| Controller | Worker | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---|---:|---:|---:|---:|
| reactive | Worker 1 | 0.400 ± 0.006 | 0.087 ± 0.036 | 0.313 ± 0.042 | 48.1 ± 19.3 |
| reactive | Worker 2 | 0.316 ± 0.001 | 0.086 ± 0.029 | 0.231 ± 0.030 | 45.5 ± 15.7 |
| reactive | **Total** | 0.716 ± 0.007 | 0.172 ± 0.065 | 0.544 ± 0.071 | 93.6 ± 34.9 |
| proactive | Worker 1 | 0.384 ± 0.010 | 0.216 ± 0.006 | 0.168 ± 0.004 | 127.0 ± 1.0 |
| proactive | Worker 2 | 0.305 ± 0.007 | 0.170 ± 0.007 | 0.136 ± 0.001 | 93.4 ± 1.3 |
| proactive | **Total** | 0.689 ± 0.016 | 0.386 ± 0.012 | 0.303 ± 0.005 | 220.4 ± 0.5 |

## Proactive compared with reactive

| Metric (total) | Reactive | Proactive | Difference |
|---|---:|---:|---:|
| Demand (CPU) | 0.716 | 0.689 | -0.027 (-4%) |
| CPU used (CPU) | 0.172 | 0.386 | +0.213 (+124%) |
| Unmet demand (CPU) | 0.544 | 0.303 | -0.241 (-44%) |
| Training speed (steps/s) | 93.6 | 220.4 | +126.8 (+136%) |

## Every run (totals)

| Controller | Repeat | Start | Length | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---:|---|---:|---:|---:|---:|---:|
| reactive | 1 | 2026-10-04 18:42 | 600 s | 0.709 | 0.244 | 0.465 | 132.0 |
| proactive | 1 | 2026-10-04 18:53 | 601 s | 0.702 | 0.396 | 0.307 | 220.8 |
| reactive | 2 | 2026-10-04 19:04 | 601 s | 0.721 | 0.156 | 0.565 | 84.8 |
| proactive | 2 | 2026-10-04 19:15 | 601 s | 0.694 | 0.389 | 0.305 | 220.4 |
| reactive | 3 | 2026-10-04 19:26 | 600 s | 0.719 | 0.117 | 0.602 | 63.8 |
| proactive | 3 | 2026-10-04 19:37 | 601 s | 0.671 | 0.373 | 0.298 | 219.8 |
