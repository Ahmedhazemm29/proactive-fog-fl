# results

This folder holds the reports, tables, plots and CSVs of every step. Each report names the script and the settings that made it. The raw data behind them is in `data/`, which git ignores.

- `predictors/`: step 3, the predictors compared like Dogani's Table 8 (`table8.md`). `predictors/seeds/` retrains its 4 models with seeds 1, 2 and 3 and compares them with seed 0, the Table 8 run (`summary.md`).
- `predictors_patience5/`: step 3 with early-stopping patience 5, kept for decision 3.8.
- `predictor_gap/`: step 3, checks and small experiments on the gap to Dogani's MAPE (decisions 3.11 and 3.12, findings 4.19 to 4.26). `mape_readings.md` compares every way to compute MAPE.
- `autoscaler/`: step 4A, the main simulation, like Dogani's Table 11 (`table11.md`).
- `autoscaler_fair/`: step 4A with the same Pods_min for KHPA and the planner, 1 or 5.
- `autoscaler_sensitivity/`: step 4A, the grid of traffic level, threshold and KHPA's Pods_min (`sensitivity.md`).
- `secagg_benchmark/`: phase 2, decision support: the cost per round of FedAvg, pairwise masking and Paillier, measured on the Pi 5 (aggregator, 4 to 50 clients, `pi5/`) and on one ESP32 (client time, free heap and real message sizes, `esp32/`). See `report.md`.
- `autoscaler_live/`: step 4B, the live demo. `windows_report.md` covers all four windows. The first window's files are at the top, and `calm/`, `rise/` and `spiky/` hold the other three. `khpa_old_cpu_read/` in each window keeps the KHPA runs from before decision 4B.14.
- `autoscaler/live_4_windows.md`: step 4B, planner vs KHPA on the four live windows in one table (εn, failed requests, p95, scale actions).
- `profiles_summary.md`, `comparison.md`, `sine/`, `sine_ablation/`, `noisy_sine/` and `bursts/`: earlier part, the reactive and proactive CPU controllers under each load profile.
