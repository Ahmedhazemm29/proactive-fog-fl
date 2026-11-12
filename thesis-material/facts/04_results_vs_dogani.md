# Chapter 4: Results vs Dogani

Tags: `D x.y` = docs/decisions.md entry (4.x are numbered findings). Numbers: "ours / Dogani".

## 4.1 Prediction vs Dogani
- BiGRU vs LSTM: Dogani clearly better at t+3, t+4, t+5 (p 2.85e-12, 2.43e-07, 4.45e-06; Table 9 p. 15). Ours (patience 10): significant only at t+5 (p 1.3e-10); t+3 p 0.158, t+4 p 0.137. With patience 5, all three significant. [D 4.2]
- Federated vs central BiGRU: Dogani not significantly different (p 0.062, 0.195, 0.185). Ours: MAE within 3.5%, DM significant at every step. [D 4.3]
- MAPE FedAvg-BiGRU: 12.8 to 14.4% ours vs 9.0 to 11.2%. [D 4.5]
- MAE t+3 FedAvg-BiGRU: 506.4 / 166.8; RMSE 2064.9 / 316.9. Not comparable (traffic scale unknown). [D 4.5]
- Data transmission: one FedAvg round 3,531,392 B (BiGRU), 2,368,128 B (LSTM) vs 32,071,680 B once for raw data; break-even 9.1 and 13.5 rounds; ours ran 19 and 39 rounds (67.1 MB, 92.4 MB). [D 4.4]

## 4.2 Simulation (4A) vs Dogani Table 11 (main run; `tables/sim4a_metrics.tex`)
- No autoscaling: theta_U 19.05 / 2.01; theta_O 149.34 / 152.07; T_U 37.98 / 10.76; T_O 60.29 / 235.34.
- KHPA: theta_U 2.47 / 6.23; theta_O 2.43 / 3.05; T_U 24.11 / 32.05; T_O 20.20 / 18.23; eps_n 6.84 / 1.30; up 1,962.6 / 1,841; down 1,958.4 / 1,892.
- FedAvg-BiGRU: theta_U 0.51 / 0.26; theta_O 26.83 / 13.04; T_U 8.72 / 1.65; T_O 65.23 / 75.12; eps_n 5.48 / 1.59; up 878.6 / 1,008; down 855.4 / 1,049.
- FedAvg-LSTM: 0.54 / 0.61; 26.75 / 16.46; 9.34 / 3.81; 64.17 / 94.53; eps_n 5.34 / 1.39; up 887.1 / 1,156; down 861.2 / 1,194.
- CentralBiGRU: 0.47 / 0.23; 27.03 / 12.50; 7.57 / 1.42; 66.87 / 72.20; eps_n 5.69 / 1.63; up 682.6 / 976; down 823.6 / 1,009.
- CentralLSTM: 0.62 / 0.53; 26.69 / 16.12; 10.42 / 3.37; 62.28 / 87.43; eps_n 5.02 / 1.42; up 820.2 / 1,144; down 833.5 / 1,171.
- Oracle: theta_U 0, theta_O 28.31, T_U 0, T_O 79.89, eps_n infinite on 16 of 16 nodes. [all: results/autoscaler/table11.md]
- Qualitative agreement: planner has lowest theta_U and T_U, fewer scaling actions than KHPA in every run. [D 4.8]
- Order of predictors by eps_n: CentralBiGRU 5.69, FedAvg-BiGRU 5.48, FedAvg-LSTM 5.34, CentralLSTM 5.02: same top two as Dogani. [D 4.8]
- Whether the planner has the higher eps_n depends on Pods_min (FedAvg-BiGRU, planner / KHPA): main 5.48 / 6.84; fair both 1: 6.69 / 6.84; fair both 5: 5.48 / 3.83. [D 4.8]
- theta_U planner / KHPA: 0.51 / 2.47 (main); 0.57 / 2.47 (both 1); 0.51 / 1.60 (both 5). T_U: 8.72 / 24.11; 8.93 / 24.11; 8.72 / 21.26. Scale-ups: 879 / 1,963; 906 / 1,963; 879 / 1,710. [D 4.8]
- Over-provisioning is mostly Pods_min: first run (threshold 1.0, both Pods_min 5) theta_O 40.6 KHPA, 43.3 to 43.5 predictors; Pods_min 5 alone gives theta_O 39.3; a third of minutes need < 5 pods. [D 4.7]
- Main run KHPA theta_O 2.43 (Dogani 3.05); planner 26.83 (Pods_min 5). Fair both 1: planner 11.18 to 11.48 (Dogani 12.50 to 16.46). [D 4.7]
- Oracle over-provisions most (theta_O 13.68, T_O 74.2 in fair Pods_min 1), because max of next 3/5 minutes and removing only 70% of extra pods keep spare pods. [D 4.7]
- No autoscaling 15 fixed pods too few in 38% of minutes (theta_U 19.05 vs 2.01). [D 4.8]
- 4A fair runs mean over 16 nodes: planner BiGRU fair Pods_min 1: theta_U 0.57, theta_O 11.18, T_U 8.93, T_O 57.20, eps_n 6.69. [results/autoscaler_fair/pods_min_1/table11.md]
- Sensitivity: closest combination mean 15 / threshold 0.7 / KHPA Pods_min 1, distance 92.3; first run distance 226.6. [D 4.9; sensitivity.md]
- Eq. 18 check: Dogani printed eps_n KHPA 1.30, FedAvg-BiGRU 1.59, LSTM 1.39, CentralBiGRU 1.63, CentralLSTM 1.42; Eq. 18 on his rows gives 2.89, 6.55, 3.82, 7.16, 4.19. Ours: node mean vs Eq. 18 on mean rows: KHPA 6.84 / 6.87; BiGRU 5.48 / 5.37. [results/autoscaler/table11.md; D 4.6]

## 4.3 Live (4B) vs Dogani Table 11 (`tables/live4b_vs_dogani_table11.tex`)
- Requested workers from real CPU, one 30-min run per scaler, node 0, 180 steps. Each cell ours / Dogani. [D 4.10; L]
- No autoscaling (8 workers): theta_U 7.63; theta_O 28.80; T_U 26.67; T_O 66.11 (Dogani 2.01 / 152.07 / 10.76 / 235.34); not comparable because Dogani's fixed pods sit far above mean demand. [D 4.10]
- KHPA: theta_U 4.79 / 6.23; theta_O 3.26 / 3.05; T_U 31.11 / 32.05; T_O 17.78 / 18.23; eps_n 2.59 / 1.30; 17 up, 16 down; mean 7.56 workers. Within 1.5 points of Dogani on all four metrics. [D 4.10; L]
- Planner FedAvg-BiGRU: theta_U 0.27 / 0.26; theta_O 24.62 / 13.04; T_U 2.78 / 1.65; T_O 87.78 / 75.12; eps_n 3.93 / 1.59; 11 up, 12 down; mean 9.25 workers. Over-provisioning ~2x Dogani. [D 4.10; L]
- eps_n order matches Dogani: planner beats KHPA. [D 4.10]
- Caution: one 3-hour window on one node, not 16 nodes over 17 days. [D 4.10]
- Requested from traffic: KHPA theta_U 13.77, theta_O 0.81, T_U 76.11, T_O 3.89, eps_n 3.19; planner 1.28 / 11.50 / 12.22 / 62.78, eps_n 2.34; none 11.28 / 17.14 / 34.44 / 51.11. KHPA wins here although no request failed (p95 4.6 ms). [D 4.11; L]
- Choice flips the winner: with saturation the traffic measure is honest (none: CPU asked at most 12 workers vs traffic 18); without saturation the CPU measure is. Main table uses CPU as Dogani does (p. 17). [D 4.11]
- Users: none: 124,471 failed (5.17%) of 2,409,162 requests, all HAProxy 503 at the peak, p95 1,092.7 ms (1,093 in D 4.12). KHPA and planner: 0 failed, p95 4.6 ms; KHPA one step p95 20 ms at a fast rise. [D 4.12; L]
- Planner uses 22% more workers: 9.25 vs 7.56. Scale-up takes ~0.4 s and a 30% CPU margin absorbs KHPA's one-minute lag. [D 4.12]
- Live vs simulated: planner worker counts identical in 180 of 180 steps (L says 0 differ); KHPA differs in 142 of 180 steps (live reads CPU, simulated reads traffic). Simulated KHPA theta_U 4.65, theta_O 3.51 vs live 4.79, 3.26. [D 4.13; L]
- Load generator: 99% queued within 1.1 ms, no client timeouts, no broken connections, highest load average 8.8 on 16 threads. [D 4.13; L]

## 4.4 Explanations offered by the decisions log
- Gap in 4A scale: our traffic has higher peaks relative to its mean, so 15 fixed pods are too few more often. [D 4.9]
- Dogani's KHPA probably did not keep 5 pods at low load (KHPA theta_O falls 40.6 -> 2.2 with Pods_min 1). [D 4.9]
- Dogani's printed eps_n cannot be reproduced from his own Table 11 rows. [D 4.6]
