# Reactive vs proactive run

| Run | Start | End | Length |
|---|---|---|---:|
| reactive | 20:44:23 | 20:56:49 | 746 s |
| proactive | 20:56:52 | 21:07:02 | 610 s |

Unmet demand = average throttled CPU (time per second a worker waited because
its limit was used up). Demand = CPU used + unmet demand. Totals add up both
workers. CPU values are Prometheus 30 s rates sampled every 5 s; training
speed is the average of the workers' 10 s log reports.

## Whole runs

| Run | Worker | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---|---:|---:|---:|---:|
| reactive | Worker 1 | 0.614 | 0.279 | 0.335 | 154.1 |
| reactive | Worker 2 | 0.607 | 0.311 | 0.295 | 172.7 |
| reactive | **Total** | 1.221 | 0.591 | 0.630 | 326.7 |
| proactive | Worker 1 | 0.586 | 0.278 | 0.308 | 159.2 |
| proactive | Worker 2 | 0.579 | 0.343 | 0.236 | 197.6 |
| proactive | **Total** | 1.165 | 0.621 | 0.544 | 356.8 |

## First 10 minutes of each run

Same length for both runs (5 full 120 s load cycles), as a fairness check.

| Run | Worker | Demand (CPU) | CPU used (CPU) | Unmet demand (CPU) | Training speed (steps/s) |
|---|---|---:|---:|---:|---:|
| reactive | Worker 1 | 0.602 | 0.281 | 0.321 | 154.4 |
| reactive | Worker 2 | 0.599 | 0.299 | 0.300 | 167.4 |
| reactive | **Total** | 1.201 | 0.580 | 0.621 | 321.8 |
| proactive | Worker 1 | 0.581 | 0.275 | 0.307 | 158.3 |
| proactive | Worker 2 | 0.582 | 0.345 | 0.237 | 199.7 |
| proactive | **Total** | 1.164 | 0.620 | 0.544 | 358.0 |
