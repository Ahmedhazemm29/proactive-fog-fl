"""
Workload predictors for the synthetic FIFA node traces (Dogani & Khunjush 2024).

    data.py       features, per-node min-max scaling, split, sliding windows
    models.py     BiGRU and LSTM
    training.py   one training pass over batches, validation loss
    federated.py  FedAvg: Client and Server (shaped like Flower's NumPyClient)
    evaluate.py   MAPE / MAE / RMSE per horizon, Diebold-Mariano test

scripts/train_predictors.py ties them together.
"""
