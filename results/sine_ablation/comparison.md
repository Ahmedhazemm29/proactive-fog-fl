# Reactive vs proactive_nopred vs proactive, repeated runs

Repeats: reactive: 1 runs, proactive_nopred: 3 runs, proactive: 1 runs. Values are mean ± standard deviation across the repeats.

Unmet demand = average throttled CPU (time per second a worker waited because
its limit was used up). Demand = CPU used + unmet demand. Totals add up both
workers. CPU values are Prometheus 30 s rates sampled every 5 s; training
speed is the average of the workers' 10 s log reports.

## Mean ± standard deviation

| Controller | Worker | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---|---:|---:|---:|---:|
| reactive | Worker 1 | 0.599 ± – | 0.324 ± – | 0.274 ± – | 180.2 ± – |
| reactive | Worker 2 | 0.596 ± – | 0.275 ± – | 0.320 ± – | 152.2 ± – |
| reactive | **Total** | 1.194 ± – | 0.600 ± – | 0.595 ± – | 332.3 ± – |
| proactive_nopred | Worker 1 | 0.600 ± 0.007 | 0.338 ± 0.004 | 0.262 ± 0.004 | 191.2 ± 2.5 |
| proactive_nopred | Worker 2 | 0.596 ± 0.005 | 0.351 ± 0.004 | 0.245 ± 0.003 | 194.1 ± 2.5 |
| proactive_nopred | **Total** | 1.196 ± 0.011 | 0.690 ± 0.006 | 0.507 ± 0.005 | 385.3 ± 3.6 |
| proactive | Worker 1 | 0.607 ± – | 0.367 ± – | 0.240 ± – | 207.6 ± – |
| proactive | Worker 2 | 0.602 ± – | 0.374 ± – | 0.228 ± – | 207.8 ± – |
| proactive | **Total** | 1.209 ± – | 0.741 ± – | 0.468 ± – | 415.4 ± – |

## Proactive compared with reactive

| Metric (total) | Reactive | Proactive | Difference |
|---|---:|---:|---:|
| Demand (CPU) | 1.194 | 1.209 | +0.015 (+1%) |
| CPU used (CPU) | 0.600 | 0.741 | +0.141 (+24%) |
| Unmet demand (CPU) | 0.595 | 0.468 | -0.127 (-21%) |
| Training speed (steps/s) | 332.3 | 415.4 | +83.0 (+25%) |

## Proactive_nopred compared with reactive

| Metric (total) | Reactive | Proactive_nopred | Difference |
|---|---:|---:|---:|
| Demand (CPU) | 1.194 | 1.196 | +0.002 (+0%) |
| CPU used (CPU) | 0.600 | 0.690 | +0.090 (+15%) |
| Unmet demand (CPU) | 0.595 | 0.507 | -0.088 (-15%) |
| Training speed (steps/s) | 332.3 | 385.3 | +52.9 (+16%) |

## Proactive compared with proactive_nopred

| Metric (total) | Proactive_nopred | Proactive | Difference |
|---|---:|---:|---:|
| Demand (CPU) | 1.196 | 1.209 | +0.012 (+1%) |
| CPU used (CPU) | 0.690 | 0.741 | +0.051 (+7%) |
| Unmet demand (CPU) | 0.507 | 0.468 | -0.039 (-8%) |
| Training speed (steps/s) | 385.3 | 415.4 | +30.1 (+8%) |

## Every run (totals)

| Controller | Repeat | Start | Length | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---:|---|---:|---:|---:|---:|---:|
| proactive_nopred | 1 | 2026-10-05 06:46 | 600 s | 1.204 | 0.693 | 0.511 | 381.1 |
| reactive | 1 | 2026-10-05 06:57 | 601 s | 1.194 | 0.600 | 0.595 | 332.3 |
| proactive_nopred | 2 | 2026-10-05 07:08 | 601 s | 1.202 | 0.693 | 0.508 | 386.8 |
| proactive | 1 | 2026-10-05 07:19 | 601 s | 1.209 | 0.741 | 0.468 | 415.4 |
| proactive_nopred | 3 | 2026-10-05 07:30 | 600 s | 1.184 | 0.682 | 0.501 | 387.9 |
