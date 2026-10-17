# Live autoscaler demo (step 4B)

Node 0, 1998-07-23 07:30 to 1998-07-23 10:29 (steps 0 to 179), replayed with real worker containers behind HAProxy.
One step = one trace minute = 10 s. Cooldowns 3 steps after a scale-up (30 s) and 5 after a scale-down (50 s), SDR 0.3.

- **Worker:** one container, 0.5 CPU, 256 MB. Each request sorts 3000 numbers, finds the eigenvalues of a 100 x 100 matrix or compresses 64 KB, with equal chance.
- **Calibration:** one worker handles 1,650 requests per step (165 per second, 9,902 per real minute) at 70% CPU, measured while 18 workers run. This is workload_pod x threshold, so the planner and the traffic-based demand use it.
- **Traffic:** scale factor 0.1554, so the busiest minute needs 18 workers. Mean demand 8.11 workers.
- **Scalers:** no autoscaling has 8 workers, the mean demand. KHPA: ceil(CPU from Prometheus / 0.35), at least 1. Planner: Algorithm 3 with FedAvg-BiGRU, at least 5. All start at the fixed count, at most 20.
- **Failed request:** no 200 answer within 2 s of its planned send time. p95: of the requests that succeeded.

## Table 11, live, requested workers from real CPU

Requested workers of a step = ceil(CPU used by all workers / 0.35), at least 1.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 7.63 | 28.80 | 26.67 | 66.11 | 1.00 | 0 | 0 | 8.00 | 124,471 (5.17%) | 1092.7 |
| KHPA | 4.93 | 2.97 | 31.11 | 17.22 | 2.65 | 15 | 19 | 7.43 | 1 (0.00%) | 4.8 |
| Planner (FedAvg-BiGRU) | 0.27 | 24.62 | 2.78 | 87.78 | 3.93 | 11 | 12 | 9.25 | 0 (0.00%) | 4.6 |

## Live, requested workers from the traffic

Requested workers of a step = ceil(requests / 1,650), the same in every run.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 11.28 | 17.14 | 34.44 | 51.11 | 1.00 | 0 | 0 | 8.00 | 124,471 (5.17%) | 1092.7 |
| KHPA | 14.01 | 0.52 | 78.33 | 4.44 | 3.40 | 15 | 19 | 7.43 | 1 (0.00%) | 4.8 |
| Planner (FedAvg-BiGRU) | 1.28 | 11.50 | 12.22 | 62.78 | 2.34 | 11 | 12 | 9.25 | 0 (0.00%) | 4.6 |

## Step 4A simulation of the same steps

scalers.py with the same settings and requested workers from the traffic. KHPA reads the traffic of the last step here.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers |
|---|---|---|---|---|---|---|---|---|
| No autoscaling | 11.28 | 17.14 | 34.44 | 51.11 | 1.00 | 0 | 0 | 8.00 |
| KHPA | 4.65 | 3.51 | 35.00 | 18.89 | 2.37 | 20 | 15 | 8.42 |
| Planner (FedAvg-BiGRU) | 1.28 | 11.50 | 12.22 | 62.78 | 2.34 | 11 | 12 | 9.25 |

## Checks

- **Planner, live against simulated:** the worker counts differ in 0 of 180 steps. The planner only reads the forecasts, so they should be equal.
- **KHPA, live against simulated:** the worker counts differ in 144 of 180 steps. Live KHPA reads CPU from Prometheus, the simulated one reads the traffic.
- **No autoscaling, requested from CPU minus from traffic:** mean -1.17 workers, from -6 to +1.
- **KHPA, requested from CPU minus from traffic:** mean -0.92 workers, from -2 to +1.
- **Planner (FedAvg-BiGRU), requested from CPU minus from traffic:** mean -0.88 workers, from -2 to +1.
- **No autoscaling, run:** 2,409,162 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 62 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 7.9 (16 threads).
- **KHPA, run:** 2,409,162 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 40 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 6.9 (16 threads).
- **Planner (FedAvg-BiGRU), run:** 2,409,162 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 21 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 7.2 (16 threads).
- **KHPA, CPU seen:** at its decisions KHPA saw 98.6% of the real CPU from the cgroup files, inside the target of 98% to 100%.
- **No autoscaling, CPU seen by Prometheus:** 95.3% of the real CPU. Logged only, this scaler does not use it.
- **Planner (FedAvg-BiGRU), CPU seen by Prometheus:** 99.7% of the real CPU. Logged only, this scaler does not use it.

## Dogani, Table 11 (p. 17)

Simulated over 16 nodes and 17 days, not one 3-hour window, so only the direction compares.

| Scaler | θU | θO | TU | TO | εn |
|---|---|---|---|---|---|
| No autoscaling | 2.01 | 152.07 | 10.76 | 235.34 | 1.00 |
| KHPA | 6.23 | 3.05 | 32.05 | 18.23 | 1.30 |
| Planner (FedAvg-BiGRU) | 0.26 | 13.04 | 1.65 | 75.12 | 1.59 |

Plots: [plot_none.png](plot_none.png), [plot_khpa.png](plot_khpa.png), [plot_planner.png](plot_planner.png).
