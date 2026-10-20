# tests

This folder holds the unit tests. Run all of them from the repo root with `.venv/bin/python -m unittest discover -s tests`. They need no Docker and no trained model, and take about 10 s.

- `test_synthetic_traces.py`: step 2, the trace method.
- `test_predictors.py`: step 3, the data, the models, FedAvg and the metrics.
- `test_predictor_seeds.py`: step 3, the Table 8 seed check.
- `test_mape.py`: step 3, every way to compute MAPE of decision 3.12, on minutes with a known answer.
- `test_autoscaler.py`: step 4A, the scalers and the metrics.
- `test_live.py`: step 4B, the load generator timing, the scaler steps, the fresh CPU read and the cluster safety.
- `test_live_windows.py`: step 4B, the window rule and the windows report.
- `test_mqtt_worker.py`: the fog-node MQTT worker, its message handler and training batches.
- `test_workload.py`, `test_proactive.py`, `test_run_experiments.py`, `test_set_load.py`: earlier part.
