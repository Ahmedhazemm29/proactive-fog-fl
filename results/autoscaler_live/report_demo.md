# Live autoscaler demo (step 4B)

Node 0, 1998-07-23 08:30 to 1998-07-23 08:56 (steps 60 to 86), replayed with real worker containers behind HAProxy.
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
| Planner (FedAvg-BiGRU) | 1.57 | 9.92 | 18.52 | 62.96 | – | 6 | 0 | 11.26 | 0 (0.00%) | 4.7 |

## Live, requested workers from the traffic

Requested workers of a step = ceil(requests / 1,650), the same in every run.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers | Failed requests | p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| Planner (FedAvg-BiGRU) | 4.69 | 2.44 | 44.44 | 25.93 | – | 6 | 0 | 11.26 | 0 (0.00%) | 4.7 |

## Step 4A simulation of the same steps

scalers.py with the same settings and requested workers from the traffic. KHPA reads the traffic of the last step here.

| Scaler | θU | θO | TU | TO | εn | #Up | #Down | Mean workers |
|---|---|---|---|---|---|---|---|---|
| Planner (FedAvg-BiGRU) | 4.69 | 2.44 | 44.44 | 25.93 | – | 6 | 0 | 11.26 |

## Checks

- **Planner, live against simulated:** the worker counts differ in 0 of 27 steps. The planner only reads the forecasts, so they should be equal.
- **Planner (FedAvg-BiGRU), requested from CPU minus from traffic:** mean -1.00 workers, from -2 to +0.
- **Planner (FedAvg-BiGRU), run:** 493,799 requests, 5.1 min. The generator queued 99% of the requests within 1.1 ms of their planned time (max 22 ms). Prometheus did not answer in 0 steps. Highest 1-minute load average 6.1 (16 threads).

## Dogani, Table 11 (p. 17)

Simulated over 16 nodes and 17 days, not one 3-hour window, so only the direction compares.

| Scaler | θU | θO | TU | TO | εn |
|---|---|---|---|---|---|
| Planner (FedAvg-BiGRU) | 0.26 | 13.04 | 1.65 | 75.12 | 1.59 |

Plots: [plot_planner_demo.png](plot_planner_demo.png).
