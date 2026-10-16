# Chapter 3: Autoscaling

Tags: `D x.y` = docs/decisions.md entry; `L` = results/autoscaler_live/report.md; `C` = results/autoscaler_live/calibration.json; `W` = results/autoscaler_live/window.json.

## 3.1 Step 4A: simulation (autoscaler/scalers.py, scripts/simulate_autoscaler.py)
- Python simulation, one step per minute, on each node's test period (25,022 min, 9 July 14:54 to 26 July 23:55). Dogani uses a Kubernetes cluster (Sec. 7.5, p. 17). [D 4A.1]
- At the start of minute t a scaler may change pods; it knows real traffic up to t-1; planner also gets forecasts for t to t+4; new pods ready at once; all scalers start at 15 pods. [D 4A.1]
- Traffic scaled per node so the mean demand is 15 pods (`--mean-pods`); factors 0.4157 to 2.4404 (decisions.md text says 0.42 to 2.44). [D 4A.2; results/autoscaler/table11.md]
- Unscaled, a node would need 6 to 36 pods on average. [D 4A.2]
- Requested pods = ceil(traffic / (500 x 0.7)) = ceil(traffic / 350), at least 1; Delta t = 1 min. [D 4A.3, D 4A.9]
- Table 3 values: workload_pod 500, Pods_min 5, cooldown 3 min (scale-up) and 5 min (scale-down), SDR 0.3. [D 4A.5; table11.md]
- Threshold 0.7 default (`--threshold`); first run used 1.0, reproducible with `--threshold 1.0 --khpa-pods-min 5`. [D 4A.9]
- Algorithm 3 line 6 uses W_max_ScaleUp (paper prints W_max_ScaleDown). [D 4A.4]
- Scale-down: Pods_next = Pods_current - floor((Pods_current - Pods_estimate) x (1 - SDR)), at least Pods_min. [D 4A.5]
- Added rules: (1) if the max of the next 5 predictions needs more pods than now, keep current pods; (2) a decision that leaves pods unchanged starts no cooldown and is not counted. [D 4A.5]
- KHPA: ceil(traffic of t-1 / 350) pods, same cooldowns, no 10% tolerance band; Pods_min 1 in main run, 1 or 5 in fair runs. [D 4A.6, D 4A.10]
- Oracle predictor (real future traffic) added as 5th predictor; Dogani shows an optimal mode only in Fig. 9 (p. 17-18). [D 4A.7]
- Metrics per node, mean over 16 nodes; counts per node over its test period; epsilon_n computed per node vs that node's no-autoscaling run; infinite where divisor is 0. [D 4A.8]
- Main run (`results/autoscaler/`): mean pods 15, threshold 0.7, KHPA Pods_min 1, planner Pods_min 5. Fair runs (`results/autoscaler_fair/pods_min_1`, `pods_min_5`): same Pods_min for both. [D 4A.10]
- Mean pods main run: none 15.00; KHPA 21.85; FedAvg-BiGRU 22.99; FedAvg-LSTM 22.94; CentralBiGRU 23.27; CentralLSTM 22.94; Oracle 23.86. [results/autoscaler/table11.md]
- Mean pods fair Pods_min 1: KHPA 21.85; BiGRU 22.67; LSTM 22.63; CentralBiGRU 22.95; CentralLSTM 22.64; Oracle 23.57. [results/autoscaler_fair/pods_min_1/table11.md]
- Mean pods fair Pods_min 5: KHPA 22.33; others as main run. [results/autoscaler_fair/pods_min_5/table11.md]
- Tables: `tables/sim4a_metrics.tex`, `sim4a_fair_podsmin1.tex`, `sim4a_fair_podsmin5.tex`. Per-node values: results/autoscaler/metrics_per_node.csv.
- Figures: `figures/autoscaling_sim/pods_node00_*.png`.

## 3.2 Sensitivity (scripts/autoscaler_sensitivity.py, results/autoscaler_sensitivity/sensitivity.md)
- Grid: mean traffic 15, 25, 40 pods (at 100% use) x threshold 1.0, 0.7 x KHPA Pods_min 5, 1 = 12 combinations; planner Pods_min 5; no autoscaling 15 pods. [D 4.9]
- Distance to Dogani = sum |ours - Dogani| over theta_U, theta_O, T_U, T_O for none, KHPA, FedAvg-BiGRU; Dogani's TO 235.34 (none) left out. [D 4.9]
- Ranking top: mean 15 / threshold 0.7 / KHPA Pods_min 1 distance 92.3; mean 25 / 1.0 / 1: 121.3; 15 / 0.7 / 5: 137.2; first run (15 / 1.0 / 5): 226.6 (rank 10). [sensitivity.md]
- Closest per scaler: none: 15 / 0.7 (distance 47.0); KHPA: 40 / 1.0 / 1 (13.4); FedAvg-BiGRU: 25 / 0.7 (25.6). [sensitivity.md]
- 15 / 0.7: no autoscaling theta_O 149.3 vs Dogani 152.07. [D 4.9]
- No combination matches Dogani's no-autoscaling under-provisioning: ours theta_U >= 12.65 vs 2.01; T_U >= 28.4 vs 10.76. [D 4.9]
- FedAvg-BiGRU stays at theta_O 9 to 44 and T_U 6.5 to 16.4 vs Dogani 13.04 and 1.65. [D 4.9]

## 3.3 Step 4B: live demo (autoscaler/cluster.py, loadgen.py, live.py, scripts/live_*.py; guide docs/demo_live.md)
- Real worker containers with Docker on one laptop (Intel i7-13620H, 6 fast cores x 2 threads + 4 slow cores = 16 threads); HAProxy 2.8 in front; own Python loop plays Kubernetes. [D 4B.1, D 4B.3, D 4B.7]
- 3 scalers replay the same 3-hour window one after another: no autoscaling, KHPA, planner (FedAvg-BiGRU). [D 4B.1]
- Worker: small Python HTTP server, numpy, 0.5 CPU, 256 MB, one BLAS thread, Nagle off. [D 4B.2]
- Each request picks with equal chance: sort 3000 random numbers; eigenvalues of a 100 x 100 random matrix; zlib-compress a 64 KB text file. Dogani: sort array, eigenvalues of matrix, compress file (Sec. 7.5). [D 4B.2]
- Nagle off: p95 dropped from 45 ms to ~5 ms. [D 4B.2]
- Calibration: one worker handles 1,650 requests per step = 165/s = 9,902 per real minute at 70% CPU (rate70 = 165.03/s), measured with 18 workers. [C; D 4B.3]
- Why 18 workers: per-request cost rises with load; at 1,650 req/step one worker used 55% of its limit, 8 workers 59%, 18 workers 72%. At 8 workers calibrated, the peak would need ~22 workers (> cap 20). [D 4B.3]
- Pinning to fast cores tried: cost per request grew 30% from 1 to 18 workers vs 12% unpinned; not used. [D 4B.3]
- Window: node 0 test traffic 23 July 1998 07:30 to 10:29, 180 minutes, centred on the busiest half hour; demand ~4 to 18 to ~5 workers; 3 warm-up minutes replayed but not measured. [D 4B.4; W]
- Scale factor 0.1554 (peak needs 18 workers); mean demand 8.11 workers; raw mean 86,134 and raw max 191,134 requests per minute. [W]
- Time compression: one trace minute = 10 s; cooldowns 3 and 5 steps = 30 s and 50 s; run ~31 min each (30.6 min measured). [D 4B.5; L]
- Load generator: open loop, requests spread evenly over each 10 s step; failed = no 200 within 2 s of planned time; response time measured from planned time; p95 over successes; asyncio, 6,000 keep-alive connections. [D 4B.6]
- First full run with 256 connections: generator became the bottleneck, workers idle at 0.13 CPU, all requests failed; run thrown away. [D 4B.6]
- With 6,000 connections 8 workers at 2,700 req/s run at 0.49 CPU and serve ~1,930/s; rest 503. Peak ~3,000 req/s. [D 4B.6]
- Check: 99% of requests queued within 1.1 ms of planned time in every full run (max 62 ms none, 21 ms KHPA/planner). [D 4B.6, D 4.13; L]
- HAProxy: round-robin, 20 workers listed in maintenance mode; max 16 requests per worker at once; queue up to 1 s then 503; `option abortonclose`. [D 4B.7]
- Scale-up: start pre-created container (~0.4 s), wait /health, enable via runtime API. Scale-down: maintenance, wait 0.2 s, stop. [D 4B.7]
- Earlier 2 s queue without abortonclose: HAProxy kept requests whose clients gave up, workers wasted CPU, nothing succeeded. [D 4B.7]
- CPU check after the change: 70.1% (18 workers), 61.1% (8 workers) at 1,650 req/step. [D 4B.7]
- Cap of 20 workers (`MAX_WORKERS = 20`, autoscaler/cluster.py); addresses 172.30.0.11 to .30; 20 x 0.5 = at most 10 of 16 threads; peak needs 18, 2 spare. All containers labelled thesis.live=1. [D 4B.7, D 4B.11]
- Cap never mattered: KHPA and planner peaked at 17 workers; CPU-requested reached 19 in one step. [D 4B.11]
- No autoscaling: 8 workers (rounded mean demand 8.11). KHPA: ceil(CPU / 0.35), at least 1, CPU = sum(rate(container_cpu_usage_seconds_total[15s])) from Prometheus/cAdvisor; cooldowns 3 and 5 steps; no tolerance band. Planner: Algorithm 3, FedAvg-BiGRU forecasts, 1,650 requests per worker, at least 5. All start at 8. [D 4B.8]
- Prometheus scrape 5 s, hence 15 s rate window; cgroup fallback never needed. [D 4B.8]
- CPU measured from each worker's cgroup cpu.stat at step boundaries; Prometheus value trails by ~half a step; CSV keeps `cpu_total` and `prom_cpu`. [D 4B.10]
- Requested workers two ways: from CPU = ceil(CPU / 0.35), at least 1; from traffic = ceil(requests / 1,650). [D 4B.9]
- CPU measure weak spots: saturated worker hides demand; per-request cost lower with fewer workers. [D 4B.9]
- Tables: `tables/live4b_vs_dogani_table11.tex`. Figures: `figures/autoscaling_live/live_*.png` (workers above, p95 below). [scripts/live_report.py]
- Demo run (26 min, steps 60 to 86, planner only): theta_U 1.57, theta_O 9.92, T_U 18.52, T_O 62.96, 6 up, 0 down, mean workers 11.26, p95 4.7 ms. [results/autoscaler_live/report_demo.md]

## 3.4 Earlier part: CPU controllers (reactive vs proactive), for context
- Setup: 2 worker containers share a 1.0 CPU budget; cAdvisor, Prometheus (5 s scrape), Grafana. Runs of 10 min, 3 per controller per profile, alternating. [results/profiles_summary.md; README.md]
- Reactive: every 5 s, >80% of limit -> +0.1, <20% -> -0.1, min 0.1. Proactive: line fit over the last 6 readings, 10 s ahead, split proportional to predicted demand. Demand = usage rate + throttled-seconds rate (30 s window). [project CLAUDE.md, untracked; controller/]
- Training speed (steps/s), reactive vs proactive: sine(20 s apart) 315.3 vs 354.0 (+12%); bursts 93.6 vs 220.4 (+136%); noisy_sine 300.3 vs 391.8 (+30%). [results/profiles_summary.md]
- Sine 60 s apart: +26% (reactive 323 vs proactive 407 steps/s); prediction off: 385 steps/s, about two thirds of proactive's gain. [project CLAUDE.md; results/sine_ablation/comparison.md]
- Figures: `figures/cpu_controller/` (PDF, demand vs usage and limits per run).
- This part is not one of the four requested chapters; use only if the thesis needs the motivation.
