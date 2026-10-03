# Reactive vs proactive, repeated runs

Repeats: reactive: 3 runs, proactive: 3 runs. Values are mean ± standard deviation across the repeats.

Unmet demand = average throttled CPU (time per second a worker waited because
its limit was used up). Demand = CPU used + unmet demand. Totals add up both
workers. CPU values are Prometheus 30 s rates sampled every 5 s; training
speed is the average of the workers' 10 s log reports.

## Mean ± standard deviation

| Controller | Worker | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---|---:|---:|---:|---:|
| reactive | Worker 1 | 0.595 ± 0.008 | 0.246 ± 0.029 | 0.350 ± 0.029 | 136.0 ± 14.7 |
| reactive | Worker 2 | 0.592 ± 0.010 | 0.320 ± 0.029 | 0.272 ± 0.032 | 179.3 ± 17.3 |
| reactive | **Total** | 1.187 ± 0.017 | 0.565 ± 0.018 | 0.622 ± 0.003 | 315.3 ± 4.0 |
| proactive | Worker 1 | 0.602 ± 0.001 | 0.287 ± 0.001 | 0.315 ± 0.001 | 157.7 ± 3.8 |
| proactive | Worker 2 | 0.599 ± 0.001 | 0.353 ± 0.001 | 0.246 ± 0.001 | 196.3 ± 5.9 |
| proactive | **Total** | 1.201 ± 0.002 | 0.640 ± 0.001 | 0.561 ± 0.002 | 354.0 ± 9.7 |

## Proactive compared with reactive

| Metric (total) | Reactive | Proactive | Difference |
|---|---:|---:|---:|
| Demand (CPU) | 1.187 | 1.201 | +0.014 (+1%) |
| CPU used (CPU) | 0.565 | 0.640 | +0.075 (+13%) |
| Unmet demand (CPU) | 0.622 | 0.561 | -0.061 (-10%) |
| Training speed (steps/s) | 315.3 | 354.0 | +38.7 (+12%) |

## Every run (totals)

| Controller | Repeat | Start | Length | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---:|---|---:|---:|---:|---:|---:|
| reactive | 1 | 2026-10-02 21:38 | 600 s | 1.196 | 0.572 | 0.624 | 313.2 |
| proactive | 1 | 2026-10-02 21:49 | 601 s | 1.203 | 0.640 | 0.563 | 358.3 |
| reactive | 2 | 2026-10-02 22:00 | 601 s | 1.168 | 0.546 | 0.622 | 312.8 |
| proactive | 2 | 2026-10-02 22:11 | 600 s | 1.200 | 0.641 | 0.560 | 360.9 |
| reactive | 3 | 2026-10-02 22:22 | 600 s | 1.197 | 0.579 | 0.618 | 319.9 |
| proactive | 3 | 2026-10-02 22:33 | 601 s | 1.200 | 0.639 | 0.560 | 343.0 |
