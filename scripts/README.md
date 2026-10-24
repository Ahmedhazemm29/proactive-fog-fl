# scripts

This folder holds one command-line script per task. Run them from the repo root with `.venv/bin/python scripts/<name>.py`. Each script explains its options at the top of the file. The main README gives the order and the run times.

- `fifa_workload.py`, `plot_fifa_workload.py`: step 1, the FIFA requests per minute and their plot.
- `synthetic_traces.py`: step 2, the 16 synthetic node traces.
- `train_predictors.py`: step 3, trains and compares the predictors.
- `predictor_seeds.py`: step 3, the Table 8 seed check, from the runs in `results/predictors/seeds/`.
- `predictor_gap.py`, `predictor_experiments.py`, `mape_readings.py`: step 3, checks on the gap to Dogani's MAPE, single training experiments and every way to compute MAPE.
- `simulate_autoscaler.py`: step 4A, the simulation of the three scalers.
- `autoscaler_sensitivity.py`: step 4A, the sensitivity grid.
- `live_calibrate.py`: step 4B, the requests one worker handles at 70% CPU.
- `live_windows.py`: step 4B, picks the extra windows by a fixed rule.
- `live_prepare.py`: step 4B, writes one window and its forecasts.
- `live_run.py`: step 4B, one live run of one scaler.
- `live_report.py`, `live_windows_report.py`: step 4B, the report of one window and of all windows.
- `run_experiments.py`, `set_load.py`, `control_page.py`: earlier part, the controller runs and the load of the two workers.
- `secagg_benchmark.py`, `plot_secagg_benchmark.py`, `secagg_esp32_tools.py`: phase 2, decision support: the cost per FL round of FedAvg, pairwise masking and Paillier. `secagg_benchmark.py` runs on the Pi for the aggregator's cost; `secagg_esp32_tools.py` makes the test keys, measures the message sizes and checks the ciphertexts of the ESP32 benchmark firmware (`esp32/src/secagg_bench/`). Report in `results/secagg_benchmark/`. They run in their own venv with `requirements-secagg.txt`.
- `requirements.txt`: the Python packages of steps 1 to 4A.
