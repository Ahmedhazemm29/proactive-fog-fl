# Inconsistencies in Dogani & Khunjush (2024)

Dogani, J., Khunjush, F. (2024). Proactive auto-scaling technique for web applications in container-based edge computing using federated learning model. JPDC 187, 104837.

Source for every item: docs/decisions.md (entry given). The paper itself is not in the repository, so page and table numbers are as recorded there. Check them against the PDF before quoting.

## A. Contradictions inside the paper

| # | Where | What conflicts | Our handling | Source |
|---|---|---|---|---|
| 1 | Table 2 (p. 10) vs Sec. 7.1 (p. 11) | Table 2: 64 units in the hidden layers. Sec. 7.1: one BiGRU layer with 32 hidden units. | 64 units (Table 2 is the full parameter table). | D 3.3 |
| 2 | Eq. 8, Sec. 5.2 (p. 8) vs Sec. 6.2 (p. 10) | Eq. 8 scales to [0, 1]. Sec. 6.2 says [-1, 1]. | [0, 1]. | D 3.4 |
| 3 | Table 2 (p. 10) vs Sec. 5.2 (p. 7-8) | Table 2 lists encoder and decoder hidden layers and an attention activation. The text describes a plain BiGRU with a linear output layer. | Plain BiGRU/LSTM. | D 3.5 |
| 4 | Table 8 (p. 13) vs Table 4 (p. 11) | FedAvg-BiGRU MAE at t+5: 221.9 in Table 8, 261.9 in Table 4, same model and data. | Not resolved; Table 8 value used in our comparison table. | D 4.5 |
| 5 | Table 11 (p. 17) vs Eq. 18 | Printed eps_n: KHPA 1.30, FedAvg-BiGRU 1.59 (also LSTM 1.39, CentralBiGRU 1.63, CentralLSTM 1.42). Eq. 18 applied to the paper's own rows gives 2.89, 6.55, 3.82, 7.16, 4.19, i.e. 2.2 to 4.4 times larger. Order of models stays. | Reported both; cannot tell how printed values were computed. | D 4.6 |
| 6 | Table 11 (p. 17) vs Eq. 17 (p. 11) | T_O = 235.34 for no autoscaling. T_O is a share of time, so it cannot exceed 100. | Dogani's 235.34 left out of the sensitivity distance. | D 4.6, D 4.9 |
| 7 | Algorithm 3 line 6 (p. 9) vs text (p. 17) | Line 5 computes W_max_ScaleUp, line 6 divides W_max_ScaleDown by workload_pod. W_max_ScaleDown is computed only later (line 10). Text says scale-up uses three prediction steps. | Treated as a typo: line 6 uses W_max_ScaleUp. | D 4A.4 |
| 8 | Sec. 7.5 (p. 17) vs Table 11 | "15 pods = pods needed for the typical payload", yet no-autoscaling theta_O = 152.07 and T_O = 235.34, i.e. the fixed pods are far above mean demand. | Noted as reason live no-autoscaling cannot be compared. | D 4.10 |
| 9 | Sec. 6.1 (p. 10) vs data | Paper: FIFA datasets are stationary. Weekly mean goes 882 -> 28,842 -> 982 req/min (factor 33). | We did not run a formal stationarity test. | D 4.1 |

## B. Claims not supported by our reproduction

| # | Where | Claim | What we found | Source |
|---|---|---|---|---|
| 10 | Table 9 (p. 15) | FedAvg-BiGRU clearly better than FedAvg-LSTM at t+3, t+4, t+5 (p 2.85e-12, 2.43e-07, 4.45e-06). | Patience 10: only t+5 significant (p 1.3e-10); t+3 p 0.158, t+4 p 0.137. Patience 5: all three significant. | D 4.2 |
| 11 | Table 9 (p. 15) | FedAvg-BiGRU vs CentralBiGRU not significant (p 0.062, 0.195, 0.185). | Significant at every step, with MAE within 3.5% (about 400,000 windows). | D 4.3 |
| 12 | p. 14 | Remarkable reduction in data transmission, not measured. | One FedAvg round 3,531,392 B (BiGRU); raw data once 32,071,680 B; break-even after 9.1 rounds (BiGRU), 13.5 (LSTM); our runs 19 and 39 rounds. | D 4.4 |
| 13 | Table 8 (p. 13) | MAE 166.8, RMSE 316.9 (FedAvg-BiGRU t+3). | 506.4 and 2064.9 on traffic averaging ~10,800 req/min. Scale of the paper's traffic unknown; only MAPE (ours 12.8 to 14.4% vs 9.0 to 11.2%) comparable. | D 4.5 |
| 14 | Table 11 (p. 17) | KHPA over-provisions far less than the planner (theta_O 3.05 vs 13.04). | Mostly an effect of Pods_min: with both at 1, planner theta_O 11.18 vs KHPA 2.43; with both at 5, KHPA 23.82. | D 4.7 |
| 15 | Table 11 (p. 17) | Planner has higher eps_n than KHPA. | Depends on Pods_min: main 5.48 vs 6.84 (KHPA higher); both 1: 6.69 vs 6.84; both 5: 5.48 vs 3.83. | D 4.8 |
| 16 | Table 11 (p. 17) | No autoscaling theta_U 2.01, T_U 10.76. | Ours at least 12.65 and 28.4 in all 12 sensitivity combinations (19.05, 37.98 in main run). | D 4.9 |

## C. Missing details (not contradictions, but affect reproduction)

| # | Item | Source |
|---|---|---|
| 17 | Time zone of minutes and time features (Sec. 6.1) | D 1.2 |
| 18 | Minutes with zero requests | D 1.4 |
| 19 | Settings of the Koltuk method, fitted distribution, ACF error measure, stop rule | D 2.1 to 2.4 |
| 20 | Input window length W | D 3.2 |
| 21 | Holidays used; how windows meet split borders | D 3.1 |
| 22 | Learning rate | D 3.6 |
| 23 | FedAvg subset size, local epochs E, number of rounds (Algorithm 2, p. 8) | D 3.7 |
| 24 | Early-stopping rule (only 64 epochs given) | D 3.8 |
| 25 | MAPE for zero real values (Eq. 13, p. 10) | D 3.9 |
| 26 | Loss and correction of the Diebold-Mariano test (ref. [72]) | D 3.10 |
| 27 | Size/scale of the synthetic traffic (needed for "15 pods", and for MAE/RMSE) | D 4A.2, D 4.5 |
| 28 | Whether KHPA has a Pods_min (Table 3 gives 5 for the planner only) | D 4A.10 |
| 29 | How the 16 nodes are combined in Table 11; what the scaling counts cover | D 4A.8 |
| 30 | Description of the load generator | D 4B.6 |
| 31 | Traffic is used in place of CPU in 4A; real Kubernetes ignores changes below 10%, Algorithm 1 has no such band (this is a note on the algorithm, not an error) | D 4A.6 |
