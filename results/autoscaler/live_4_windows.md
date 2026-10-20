# Live autoscaler on four windows: planner vs KHPA

The step 4B live runs on the four 3-hour windows (original, calm, rise, spiky) shown in `results/autoscaler_live/windows_workers.png`. The numbers are copied from `results/autoscaler_live/windows_report.json`, written by `scripts/live_windows_report.py`. The full report, with θU, θO, TU, TO, mean workers and the window choice, is `results/autoscaler_live/windows_report.md`.

- **εn:** each scaler compared with no autoscaling in the same window, with requested workers from real CPU (the main table of step 4B). Above 1 is better.
- **Failed requests:** requests without an answer within 2 s, with their share of all requests sent.
- **p95:** 95th percentile response time.
- **Scale actions:** scale-ups plus scale-downs, with (up / down) in brackets.
- **Planner:** driven by FedAvg-BiGRU forecasts.

| Window | Node | εn Planner | εn KHPA | Failed requests, Planner | Failed requests, KHPA | p95 Planner (ms) | p95 KHPA (ms) | Scale actions, Planner (up / down) | Scale actions, KHPA (up / down) |
|---|---|---|---|---|---|---|---|---|---|
| original | 0 | 3.93 | 2.65 | 0 (0.00%) | 1 (0.00%) | 4.6 | 4.8 | 23 (11 / 12) | 34 (15 / 19) |
| calm | 1 | 1.00 | 0.81 | 0 (0.00%) | 0 (0.00%) | 4.9 | 4.9 | 1 (1 / 0) | 34 (17 / 17) |
| rise | 7 | 4.10 | 3.91 | 0 (0.00%) | 3,050 (0.18%) | 4.9 | 5.0 | 17 (9 / 8) | 24 (12 / 12) |
| spiky | 2 | 4.53 | 2.97 | 2 (0.00%) | 3,483 (0.26%) | 4.7 | 5.1 | 15 (9 / 6) | 25 (12 / 13) |
| **All four** | | 3.39 (mean) | 2.59 (mean) | 2 (total) | 6,534 (total) | 4.8 (mean) | 5.0 (mean) | 14.0 (mean) | 29.2 (mean) |

For reference, no autoscaling lost 432,500 of 10,567,112 requests over the four windows.

The planner has the higher εn in all four windows. With requested workers from the traffic instead of real CPU (finding 4.11), KHPA has the higher εn in original, rise and spiky, and εn is not defined in calm (`windows_report.md`, "Answers").
