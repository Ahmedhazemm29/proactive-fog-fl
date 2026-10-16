# Live autoscaler demo (step 4B)

Node 2, 1998-07-20 22:45 to 1998-07-21 01:44 (steps 0 to 179), replayed with real worker containers behind HAProxy.
One step = one trace minute = 10 s. Cooldowns 3 steps after a scale-up (30 s) and 5 after a scale-down (50 s), SDR 0.3.

- **Worker:** one container, 0.5 CPU, 256 MB. Each request sorts 3000 numbers, finds the eigenvalues of a 100 x 100 matrix or compresses 64 KB, with equal chance.
- **Calibration:** one worker handles 1,650 requests per step (165 per second, 9,902 per real minute) at 70% CPU, measured while 18 workers run. This is workload_pod x threshold, so the planner and the traffic-based demand use it.
- **Traffic:** scale factor 0.1315, so the busiest minute needs 18 workers. Mean demand 4.49 workers.
- **Scalers:** no autoscaling has 4 workers, the mean demand. KHPA: ceil(CPU from Prometheus / 0.35), at least 1. Planner: Algorithm 3 with FedAvg-BiGRU, at least 5. All start at the fixed count, at most 20.
- **Failed request:** no 200 answer within 2 s of its planned send time. p95: of the requests that succeeded.

## Table 11, live, requested workers from real CPU

Requested workers of a step = ceil(CPU used by all workers / 0.35), at least 1.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 8.89 | 27.22 | 28.89 | 58.33 | 1.00 | 0 | 0 | 4.00 | 163,881 (12.28%) | 1093.9 |
| KHPA | 2.77 | 5.25 | 13.33 | 16.67 | 3.35 | 13 | 10 | 4.42 | 1,336 (0.10%) | 4.8 |
| Planner (FedAvg-BiGRU) | 0.21 | 48.28 | 1.11 | 87.78 | 4.53 | 9 | 6 | 5.94 | 2 (0.00%) | 4.7 |

## Live, requested workers from the traffic

Requested workers of a step = ceil(requests / 1,650), the same in every run.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 15.13 | 15.74 | 33.33 | 39.44 | 1.00 | 0 | 0 | 4.00 | 163,881 (12.28%) | 1093.9 |
| KHPA | 12.50 | 1.64 | 51.11 | 6.11 | 2.64 | 13 | 10 | 4.42 | 1,336 (0.10%) | 4.8 |
| Planner (FedAvg-BiGRU) | 1.61 | 30.58 | 11.11 | 74.44 | 1.66 | 9 | 6 | 5.94 | 2 (0.00%) | 4.7 |

## Step 4A simulation of the same steps

scalers.py with the same settings and requested workers from the traffic. KHPA reads the traffic of the last step here.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers |
|---|---|---|---|---|---|---|---|---|
| No autoscaling | 15.13 | 15.74 | 33.33 | 39.44 | 1.00 | 0 | 0 | 4.00 |
| KHPA | 4.54 | 5.97 | 22.78 | 20.56 | 2.23 | 16 | 15 | 4.96 |
| Planner (FedAvg-BiGRU) | 1.61 | 30.58 | 11.11 | 74.44 | 1.66 | 9 | 6 | 5.94 |

## Checks

- **Planner, live against simulated:** the worker counts differ in 0 of 180 steps. The planner only reads the forecasts, so they should be equal.
- **KHPA, live against simulated:** the worker counts differ in 102 of 180 steps. Live KHPA reads CPU from Prometheus, the simulated one reads the traffic.
- **No autoscaling, requested from CPU minus from traffic:** mean -1.14 workers, from -12 to +0.
- **KHPA, requested from CPU minus from traffic:** mean -0.63 workers, from -2 to +1.
- **Planner (FedAvg-BiGRU), requested from CPU minus from traffic:** mean -0.62 workers, from -2 to +1.
- **No autoscaling, run:** 1,334,035 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 45 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 4.7 (16 threads).
- **KHPA, run:** 1,334,035 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 42 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 5.1 (16 threads).
- **Planner (FedAvg-BiGRU), run:** 1,334,035 requests, 30.6 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 38 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 4.3 (16 threads).

## Dogani, Table 11 (p. 17)

Simulated over 16 nodes and 17 days, not one 3-hour window, so only the direction compares.

| Scaler | θU | θO | TU | TO | εn |
|---|---|---|---|---|---|
| No autoscaling | 2.01 | 152.07 | 10.76 | 235.34 | 1.00 |
| KHPA | 6.23 | 3.05 | 32.05 | 18.23 | 1.30 |
| Planner (FedAvg-BiGRU) | 0.26 | 13.04 | 1.65 | 75.12 | 1.59 |

Plots: [plot_none.png](plot_none.png), [plot_khpa.png](plot_khpa.png), [plot_planner.png](plot_planner.png).
