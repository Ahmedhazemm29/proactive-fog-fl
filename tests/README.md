# tests

This folder holds the unit tests. Run all of them from the repo root with `.venv/bin/python -m unittest discover -s tests`. They need no Docker and no trained model, and take about 10 s.

- `test_synthetic_traces.py`: step 2, the trace method.
- `test_predictors.py`: step 3, the data, the models, FedAvg and the metrics.
- `test_autoscaler.py`: step 4A, the scalers and the metrics.
- `test_live.py`: step 4B, the load generator timing, the scaler steps, the fresh CPU read and the cluster safety.
- `test_live_windows.py`: step 4B, the window rule and the windows report.
- `test_workload.py`, `test_proactive.py`, `test_run_experiments.py`, `test_set_load.py`: earlier part.
