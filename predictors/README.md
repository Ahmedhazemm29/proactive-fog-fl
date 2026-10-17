# predictors

This folder holds the code of step 3: the workload predictors of Dogani & Khunjush (2024). `scripts/train_predictors.py` trains them and `scripts/simulate_autoscaler.py` uses their forecasts. The decisions behind them are entries 3.x of `docs/decisions.md`.

- `data.py`: from a node's per-minute trace to model inputs. It makes the 5 features, the 60/20/20 split in time and the input windows.
- `models.py`: the BiGRU and the LSTM, each with 1 recurrent layer of 64 units.
- `federated.py`: FedAvg, Dogani's Algorithm 2, run in one process.
- `training.py`: the training and validation passes that the federated clients and the central models share.
- `evaluate.py`: MAPE, MAE and RMSE per horizon, and the Diebold-Mariano test.
- `__init__.py`: makes the folder a Python package.
