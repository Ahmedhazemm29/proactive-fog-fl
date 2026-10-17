# Live autoscaler demo (step 4B)

Node 1, 1998-07-20 08:38 to 1998-07-20 11:37 (steps 0 to 179), replayed with real worker containers behind HAProxy.
One step = one trace minute = 10 s. Cooldowns 3 steps after a scale-up (30 s) and 5 after a scale-down (50 s), SDR 0.3.

- **Worker:** one container, 0.5 CPU, 256 MB. Each request sorts 3000 numbers, finds the eigenvalues of a 100 x 100 matrix or compresses 64 KB, with equal chance.
- **Calibration:** one worker handles 1,650 requests per step (165 per second, 9,902 per real minute) at 70% CPU, measured while 18 workers run. This is workload_pod x threshold, so the planner and the traffic-based demand use it.
- **Traffic:** scale factor 1.7301, so the busiest minute needs 18 workers. Mean demand 17.26 workers.
- **Scalers:** no autoscaling has 17 workers, the mean demand. KHPA: ceil(CPU from Prometheus / 0.35), at least 1. Planner: Algorithm 3 with FedAvg-BiGRU, at least 5. All start at the fixed count, at most 20.
- **Failed request:** no 200 answer within 2 s of its planned send time. p95: of the requests that succeeded.

## Table 11, live, requested workers from real CPU

Requested workers of a step = ceil(CPU used by all workers / 0.35), at least 1.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 5.14 | 0.24 | 72.22 | 3.89 | 1.00 | 0 | 0 | 17.00 | 0 (0.00%) | 5.0 |
| KHPA | 2.58 | 0.68 | 42.22 | 11.11 | 0.81 | 17 | 17 | 17.35 | 0 (0.00%) | 4.9 |
| Planner (FedAvg-BiGRU) | 0.62 | 1.74 | 11.67 | 28.33 | 1.00 | 1 | 0 | 17.99 | 0 (0.00%) | 4.9 |

## Live, requested workers from the traffic

Requested workers of a step = ceil(requests / 1,650), the same in every run.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 4.14 | 0.00 | 74.44 | 0.00 | undefined (theta_o, t_o = 0) | 0 | 0 | 17.00 | 0 (0.00%) | 5.0 |
| KHPA | 2.75 | 0.55 | 43.89 | 8.89 | 0.00 | 17 | 17 | 17.35 | 0 (0.00%) | 4.9 |
| Planner (FedAvg-BiGRU) | 0.06 | 1.50 | 1.11 | 25.56 | 0.00 | 1 | 0 | 17.99 | 0 (0.00%) | 4.9 |

## Step 4A simulation of the same steps

scalers.py with the same settings and requested workers from the traffic. KHPA reads the traffic of the last step here.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers |
|---|---|---|---|---|---|---|---|---|
| No autoscaling | 4.14 | 0.00 | 74.44 | 0.00 | undefined (theta_o, t_o = 0) | 0 | 0 | 17.00 |
| KHPA | 1.14 | 0.49 | 20.56 | 8.33 | 0.00 | 10 | 10 | 17.62 |
| Planner (FedAvg-BiGRU) | 0.06 | 1.50 | 1.11 | 25.56 | 0.00 | 1 | 0 | 17.99 |

## Checks

- **Planner, live against simulated:** the worker counts differ in 0 of 180 steps. The planner only reads the forecasts, so they should be equal.
- **KHPA, live against simulated:** the worker counts differ in 82 of 180 steps. Live KHPA reads CPU from Prometheus, the simulated one reads the traffic.
- **No autoscaling, requested from CPU minus from traffic:** mean +0.17 workers, from -2 to +2.
- **KHPA, requested from CPU minus from traffic:** mean -0.05 workers, from -2 to +1.
- **Planner (FedAvg-BiGRU), requested from CPU minus from traffic:** mean +0.07 workers, from -1 to +1.
- **No autoscaling, run:** 5,125,953 requests, 30.6 min. The generator queued 99% of the requests within 1.0 ms of their planned time (max 19 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 9.2 (16 threads).
- **KHPA, run:** 5,125,953 requests, 30.7 min. The generator queued 99% of the requests within 1.0 ms of their planned time (max 18 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 9.0 (16 threads).
- **Planner (FedAvg-BiGRU), run:** 5,125,953 requests, 30.6 min. The generator queued 99% of the requests within 1.0 ms of their planned time (max 22 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 9.1 (16 threads).
- **KHPA, CPU seen:** at its decisions KHPA saw 99.1% of the real CPU from the cgroup files, inside the target of 98% to 100%.
- **No autoscaling, CPU seen by Prometheus:** 98.9% of the real CPU. Logged only, this scaler does not use it.
- **Planner (FedAvg-BiGRU), CPU seen by Prometheus:** 83.6% of the real CPU. Logged only, this scaler does not use it.

## Dogani, Table 11 (p. 17)

Simulated over 16 nodes and 17 days, not one 3-hour window, so only the direction compares.

| Scaler | θU | θO | TU | TO | εn |
|---|---|---|---|---|---|
| No autoscaling | 2.01 | 152.07 | 10.76 | 235.34 | 1.00 |
| KHPA | 6.23 | 3.05 | 32.05 | 18.23 | 1.30 |
| Planner (FedAvg-BiGRU) | 0.26 | 13.04 | 1.65 | 75.12 | 1.59 |

Plots: [plot_none.png](plot_none.png), [plot_khpa.png](plot_khpa.png), [plot_planner.png](plot_planner.png).
