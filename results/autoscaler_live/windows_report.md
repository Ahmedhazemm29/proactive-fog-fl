# Live runs on four windows (step 4B)

The step 4B setup, unchanged, on four 3-hour windows instead of one. Each window is replayed with every scaler, one run after the other. The cluster is rebuilt before each run.

- **Same as step 4B:** 180 steps of 10 s plus 3 warm-up steps, workers of 0.5 CPU, HAProxy, cooldowns of 3 and 5 steps, at most 20 workers, a failed request is one without an answer within 2 s.
- **Scale:** each window is scaled so that its busiest minute needs 18 workers at 1,650 requests per step. No autoscaling keeps the rounded mean demand.
- **Requested workers:** from real CPU, ceil(CPU of all workers / 0.35), at least 1. This is the main table of step 4B. εn compares each scaler with no autoscaling in the same window. Above 1 is better.
- **Windows:** all four lie in the test split, inside the minutes with forecasts. The three new ones come from `scripts/live_windows.py`. Every window's mean is at least the median of its node's test minutes, so no window is a quiet stretch where a jump is only noise.

## The windows

Trace rows count from 0 in `data/synthetic/node_<node>.csv`. The jump is in requests per minute of the trace, before scaling, with its share of the window mean. A plus is a rise.

| Window | Rule | Node | Time (1998) | Trace rows | Mean demand (workers) | Peak/mean | Biggest 1-minute jump | Fixed workers |
|---|---|---|---|---|---|---|---|---|
| original | busiest half hour of node 0, centred on it | 0 | 23 Jul 07:30 to 10:29 | 119,970 to 120,149 | 8.11 | 2.22 | -44,145 (51%) | 8 |
| calm | lowest peak/mean | 1 | 20 Jul 08:38 to 11:37 | 115,718 to 115,897 | 17.26 | 1.04 | +869 (5%) | 17 |
| rise | biggest 1-minute rise relative to the mean, centred on it | 7 | 12 Jul 00:01 to 03:00 | 103,681 to 103,860 | 5.72 | 3.15 | +71,627 (110%) | 6 |
| spiky | biggest 1-minute jump relative to the mean, centred on it | 2 | 20 Jul 22:45 to 21 Jul 01:44 | 116,565 to 116,744 | 4.49 | 4.01 | -64,410 (114%) | 4 |

## Results per window

**original**, node 0, 23 Jul 07:30 to 10:29:

| Scaler | θU | θO | TU | TO | εn | Failed requests | p95 (ms) | Mean workers | #Up / #Down |
|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 7.63 | 28.80 | 26.67 | 66.11 | 1.00 | 124,471 (5.17%) | 1092.7 | 8.00 | 0 / 0 |
| KHPA | 4.93 | 2.97 | 31.11 | 17.22 | 2.65 | 1 (0.00%) | 4.8 | 7.43 | 15 / 19 |
| Planner (FedAvg-BiGRU) | 0.27 | 24.62 | 2.78 | 87.78 | 3.93 | 0 (0.00%) | 4.6 | 9.25 | 11 / 12 |

**calm**, node 1, 20 Jul 08:38 to 11:37:

| Scaler | θU | θO | TU | TO | εn | Failed requests | p95 (ms) | Mean workers | #Up / #Down |
|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 5.14 | 0.24 | 72.22 | 3.89 | 1.00 | 0 (0.00%) | 5.0 | 17.00 | 0 / 0 |
| KHPA | 2.58 | 0.68 | 42.22 | 11.11 | 0.81 | 0 (0.00%) | 4.9 | 17.35 | 17 / 17 |
| Planner (FedAvg-BiGRU) | 0.62 | 1.74 | 11.67 | 28.33 | 1.00 | 0 (0.00%) | 4.9 | 17.99 | 1 / 0 |

**rise**, node 7, 12 Jul 00:01 to 03:00:

| Scaler | θU | θO | TU | TO | εn | Failed requests | p95 (ms) | Mean workers | #Up / #Down |
|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 7.66 | 49.50 | 26.67 | 68.89 | 1.00 | 144,148 (8.49%) | 1092.5 | 6.00 | 0 / 0 |
| KHPA | 3.05 | 3.66 | 15.56 | 17.22 | 3.91 | 3,050 (0.18%) | 5.0 | 5.48 | 12 / 12 |
| Planner (FedAvg-BiGRU) | 0.38 | 41.71 | 1.67 | 92.78 | 4.10 | 0 (0.00%) | 4.9 | 7.16 | 9 / 8 |

**spiky**, node 2, 20 Jul 22:45 to 21 Jul 01:44:

| Scaler | θU | θO | TU | TO | εn | Failed requests | p95 (ms) | Mean workers | #Up / #Down |
|---|---|---|---|---|---|---|---|---|---|
| No autoscaling | 8.89 | 27.22 | 28.89 | 58.33 | 1.00 | 163,881 (12.28%) | 1093.9 | 4.00 | 0 / 0 |
| KHPA | 3.42 | 5.22 | 15.00 | 19.44 | 2.97 | 3,483 (0.26%) | 5.1 | 4.35 | 12 / 13 |
| Planner (FedAvg-BiGRU) | 0.21 | 48.28 | 1.11 | 87.78 | 4.53 | 2 (0.00%) | 4.7 | 5.94 | 9 / 6 |

## All four windows

Mean over the windows, with the lowest and highest window in brackets.

| Metric | No autoscaling | KHPA | Planner (FedAvg-BiGRU) |
|---|---|---|---|
| θU | 7.33 (5.14 to 8.89) | 3.49 (2.58 to 4.93) | 0.37 (0.21 to 0.62) |
| θO | 26.44 (0.24 to 49.50) | 3.13 (0.68 to 5.22) | 29.09 (1.74 to 48.28) |
| TU | 38.61 (26.67 to 72.22) | 25.97 (15.00 to 42.22) | 4.31 (1.11 to 11.67) |
| TO | 49.31 (3.89 to 68.89) | 16.25 (11.11 to 19.44) | 74.17 (28.33 to 92.78) |
| εn | 1.00 (1.00 to 1.00) | 2.59 (0.81 to 3.91) | 3.39 (1.00 to 4.53) |
| Failed requests (%) | 6.49 (0.00 to 12.28) | 0.11 (0.00 to 0.26) | 0.00 (0.00 to 0.00) |
| p95 (ms) | 821.0 (5.0 to 1,093.9) | 5.0 (4.8 to 5.1) | 4.8 (4.6 to 4.9) |
| Mean workers | 8.75 (4.00 to 17.00) | 8.65 (4.35 to 17.35) | 10.08 (5.94 to 17.99) |
| Scaling actions (up + down) | 0 (0 to 0) | 29 (24 to 34) | 14 (1 to 23) |

## Answers

| Window | θU planner / KHPA | TU planner / KHPA | εn planner / KHPA | εn winner | εn winner, requested from traffic |
|---|---|---|---|---|---|
| original | 0.27 / 4.93 | 2.78 / 31.11 | 3.926 / 2.651 | planner | KHPA |
| calm | 0.62 / 2.58 | 11.67 / 42.22 | 0.998 / 0.808 | planner | not defined |
| rise | 0.38 / 3.05 | 1.67 / 15.56 | 4.102 / 3.907 | planner | KHPA |
| spiky | 0.21 / 3.42 | 1.11 / 15.00 | 4.527 / 2.975 | planner | KHPA |

1. **Fewer shortages: yes.** The planner has a lower θU and a lower TU than KHPA in all 4 windows.
2. **εn winner: it does not change.** The planner has the higher εn in all 4 windows.
   With requested workers from the traffic (finding 4.11): KHPA wins in original, rise and spiky. In calm εn is not defined, because no autoscaling has a θ or T of 0 there.
3. **Dogani's claims:** each claim of Table 11 (p. 17), checked per window with requested workers from real CPU.

   | Claim | Holds in | Fails in |
   |---|---|---|
   | The planner has fewer shortages than KHPA: lower θU and lower TU. | 4 of 4 | none |
   | The planner has a higher εn than KHPA. | 4 of 4 | none |
   | The planner scales less often than KHPA. | 4 of 4 | none |
   | KHPA over-provisions less than the planner: lower θO. | 4 of 4 | none |
   | Both scalers beat no autoscaling: εn above 1. | 3 of 4 | calm |

   So yes, some windows break a claim: "Both scalers beat no autoscaling: εn above 1" fails in calm.

Not in Table 11, but what users notice: over the 4 windows the planner lost 2 requests, KHPA 6,534 and no autoscaling 432,500. The reasons behind these answers are in `docs/decisions.md`, findings 4.14 to 4.18.

## Plot

![Traffic and workers per window](windows_workers.png)

Grey: the traffic of each step divided by the calibrated 1,650 requests per worker. Lines: the workers each scaler ran. Each window folder also has `report.md` and one `plot_<scaler>.png` per run, with the requested workers and the p95 response time.

## KHPA before and after the CPU read fix

KHPA first read the CPU right at each step start, often before Prometheus had stored the newest scrape, so it could see too little CPU. The fixed read waits for that scrape (decision 4B.14). KHPA was then run again on all four windows. The tables above use the new runs. The old runs are in each window's `khpa_old_cpu_read` folder. εn of both compares with the same no-autoscaling run.

| Window | θU old / new | TU old / new | Failed requests old / new | εn old / new | CPU seen old / new |
|---|---|---|---|---|---|
| original | 4.79 / 4.93 | 31.11 / 31.11 | 0 / 1 | 2.59 / 2.65 | 98.0% / 98.6% |
| calm | 1.38 / 2.58 | 23.89 / 42.22 | 0 / 0 | 0.80 / 0.81 | 99.8% / 99.1% |
| rise | 14.78 / 3.05 | 59.44 / 15.56 | 13,755 / 3,050 | 6.91 / 3.91 | 81.7% / 98.8% |
| spiky | 2.77 / 3.42 | 13.33 / 15.00 | 1,336 / 3,483 | 3.35 / 2.97 | 99.3% / 98.6% |

## Checks

- **KHPA's input:** KHPA reads the 15 s CPU rate from Prometheus at each step start. The table divides its sum over the run by the real CPU from the cgroup files, for the step that had just ended. 1.00 means KHPA saw the real CPU. The target is 0.98 to 1.00.
- **Planner:** it only reads the forecasts, so it must run the same workers as the step 4A simulation.
- **Generator and laptop:** the worst p99 delay of the load generator against the planned send times, and the highest 1-minute load average of the window's runs, on 16 threads.

| Window | KHPA's CPU from Prometheus / real CPU | Planner steps unlike step 4A | Generator, p99 delay (ms) | Highest load average |
|---|---|---|---|---|
| original | 0.99 | 0 of 180 | 1.1 | 7.9 |
| calm | 0.99 | 0 of 180 | 1.0 | 9.2 |
| rise | 0.99 | 0 of 180 | 1.1 | 7.6 |
| spiky | 0.99 | 0 of 180 | 1.1 | 4.7 |
