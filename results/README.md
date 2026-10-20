# results

This folder holds the reports, tables, plots and CSVs of every step. Each report names the script and the settings that made it. The raw data behind them is in `data/`, which git ignores.

- `predictors/`: step 3, the predictors compared like Dogani's Table 8 (`table8.md`).
- `predictors_patience5/`: step 3 with early-stopping patience 5, kept for decision 3.8.
- `predictor_gap/`: step 3, checks and small experiments on the gap to Dogani's MAPE (decisions 3.11 and 3.12, findings 4.19 to 4.26). `mape_readings.md` compares every way to compute MAPE.
- `autoscaler/`: step 4A, the main simulation, like Dogani's Table 11 (`table11.md`).
- `autoscaler_fair/`: step 4A with the same Pods_min for KHPA and the planner, 1 or 5.
- `autoscaler_sensitivity/`: step 4A, the grid of traffic level, threshold and KHPA's Pods_min (`sensitivity.md`).
- `autoscaler_live/`: step 4B, the live demo. `windows_report.md` covers all four windows. The first window's files are at the top, and `calm/`, `rise/` and `spiky/` hold the other three. `khpa_old_cpu_read/` in each window keeps the KHPA runs from before decision 4B.14.
- `profiles_summary.md`, `comparison.md`, `sine/`, `sine_ablation/`, `noisy_sine/` and `bursts/`: earlier part, the reactive and proactive CPU controllers under each load profile.
- `random_windows/`: earlier part, the same comparison on 10 random windows per profile, with the seeds and offsets (`summary.md`).
