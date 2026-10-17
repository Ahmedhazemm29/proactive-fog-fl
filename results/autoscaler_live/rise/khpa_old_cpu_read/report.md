# Live autoscaler demo (step 4B)

Node 7, 1998-07-12 00:01 to 1998-07-12 03:00 (steps 0 to 179), replayed with real worker containers behind HAProxy.
One step = one trace minute = 10 s. Cooldowns 3 steps after a scale-up (30 s) and 5 after a scale-down (50 s), SDR 0.3.

- **Worker:** one container, 0.5 CPU, 256 MB. Each request sorts 3000 numbers, finds the eigenvalues of a 100 x 100 matrix or compresses 64 KB, with equal chance.
- **Calibration:** one worker handles 1,650 requests per step (165 per second, 9,902 per real minute) at 70% CPU, measured while 18 workers run. This is workload_pod x threshold, so the planner and the traffic-based demand use it.
- **Traffic:** scale factor 0.1452, so the busiest minute needs 18 workers. Mean demand 5.72 workers.
- **Scalers:** no autoscaling has 6 workers, the mean demand. KHPA: ceil(CPU from Prometheus / 0.35), at least 1. Planner: Algorithm 3 with FedAvg-BiGRU, at least 5. All start at the fixed count, at most 20.
- **Failed request:** no 200 answer within 2 s of its planned send time. p95: of the requests that succeeded.

## Table 11, live, requested workers from real CPU

Requested workers of a step = ceil(CPU used by all workers / 0.35), at least 1.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 7.66 | 49.50 | 26.67 | 68.89 | 1.00 | 0 | 0 | 6.00 | 144,148 (8.49%) | 1092.5 |
| KHPA | 14.78 | 0.21 | 59.44 | 1.67 | 6.91 | 16 | 17 | 4.63 | 13,755 (0.81%) | 494.1 |
| Planner (FedAvg-BiGRU) | 0.38 | 41.71 | 1.67 | 92.78 | 4.10 | 9 | 8 | 7.16 | 0 (0.00%) | 4.9 |

## Live, requested workers from the traffic

Requested workers of a step = ceil(requests / 1,650), the same in every run.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 12.23 | 37.39 | 30.56 | 58.89 | 1.00 | 0 | 0 | 6.00 | 144,148 (8.49%) | 1092.5 |
| KHPA | 24.96 | 0.00 | 90.56 | 0.00 | ∞ (theta_o, t_o = 0) | 16 | 17 | 4.63 | 13,755 (0.81%) | 494.1 |
| Planner (FedAvg-BiGRU) | 0.95 | 26.07 | 7.22 | 65.56 | 2.90 | 9 | 8 | 7.16 | 0 (0.00%) | 4.9 |

## Step 4A simulation of the same steps

scalers.py with the same settings and requested workers from the traffic. KHPA reads the traffic of the last step here.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers |
|---|---|---|---|---|---|---|---|---|
| No autoscaling | 12.23 | 37.39 | 30.56 | 58.89 | 1.00 | 0 | 0 | 6.00 |
| KHPA | 3.50 | 4.79 | 18.33 | 25.56 | 3.20 | 15 | 15 | 6.28 |
| Planner (FedAvg-BiGRU) | 0.95 | 26.07 | 7.22 | 65.56 | 2.90 | 9 | 8 | 7.16 |

## Checks

- **Planner, live against simulated:** the worker counts differ in 0 of 180 steps. The planner only reads the forecasts, so they should be equal.
- **KHPA, live against simulated:** the worker counts differ in 154 of 180 steps. Live KHPA reads CPU from Prometheus, the simulated one reads the traffic.
- **No autoscaling, requested from CPU minus from traffic:** mean -1.12 workers, from -9 to +0.
- **KHPA, requested from CPU minus from traffic:** mean -0.73 workers, from -6 to +2.
- **Planner (FedAvg-BiGRU), requested from CPU minus from traffic:** mean -0.66 workers, from -2 to +1.
- **No autoscaling, run:** 1,697,962 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 56 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 7.1 (16 threads).
- **KHPA, run:** 1,697,962 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 43 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 6.8 (16 threads).
- **Planner (FedAvg-BiGRU), run:** 1,697,962 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 48 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 5.9 (16 threads).

## Dogani, Table 11 (p. 17)

Simulated over 16 nodes and 17 days, not one 3-hour window, so only the direction compares.

| Scaler | θU | θO | TU | TO | εn |
|---|---|---|---|---|---|
| No autoscaling | 2.01 | 152.07 | 10.76 | 235.34 | 1.00 |
| KHPA | 6.23 | 3.05 | 32.05 | 18.23 | 1.30 |
| Planner (FedAvg-BiGRU) | 0.26 | 13.04 | 1.65 | 75.12 | 1.59 |

Plots: [plot_none.png](plot_none.png), [plot_khpa.png](plot_khpa.png), [plot_planner.png](plot_planner.png).
