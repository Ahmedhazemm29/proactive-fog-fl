# Workload prediction, 16 synthetic FIFA nodes (like Dogani's Table 8)

W = 30 minutes, test part = last 20% of every node, errors pooled over all nodes' test windows, in requests per minute. MAPE in %.

| Model | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 | MAE t+4 | MAE t+5 | RMSE t+3 | RMSE t+4 | RMSE t+5 |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU (ours) | 13.19 | 15.54 | 18.16 | 509.1 | 558.3 | 614.7 | 2062.5 | 2218.1 | 2391.6 |
| FedAvg-LSTM (ours) | 15.03 | 16.39 | 15.78 | 522.2 | 571.1 | 615.6 | 2094.1 | 2237.7 | 2392.3 |
| CentralBiGRU (ours) | 11.99 | 12.72 | 15.08 | 503.8 | 553.0 | 582.8 | 2027.2 | 2175.1 | 2324.5 |
| CentralLSTM (ours) | 15.88 | 12.35 | 13.06 | 515.4 | 550.7 | 592.0 | 2054.1 | 2190.4 | 2353.2 |
| FedAvg-BiGRU (Dogani) | 9.04 | 10.2 | 11.2 | 166.8 | 241.3 | 221.9 | 316.9 | 389.2 | 437.7 |
| FedAvg-LSTM (Dogani) | 11.2 | 12.4 | 14.1 | 204.3 | 221.4 | 279.7 | 385.5 | 414.7 | 495.8 |
| CentralBiGRU (Dogani) | 8.49 | 9.66 | 10.45 | 156.5 | 213.0 | 224.8 | 296.7 | 351.8 | 406.3 |
| CentralLSTM (Dogani) | 10.4 | 11.3 | 13.1 | 192.7 | 208.8 | 263.9 | 364.5 | 392.1 | 449.1 |

MAPE skips minutes with 0 real requests: 51 per model and step (pooled over all nodes).

## Diebold-Mariano test (absolute errors)

| Pair | DM t+3 | p t+3 | DM t+4 | p t+4 | DM t+5 | p t+5 |
|---|---|---|---|---|---|---|
| FedAvg-BiGRU vs FedAvg-LSTM | -20.71 | 2.93e-95 | -17.85 | 2.83e-71 | -0.85 | 0.396 |
| FedAvg-BiGRU vs CentralBiGRU | 5.24 | 1.65e-07 | 5.01 | 5.46e-07 | 23.91 | 2.63e-126 |
| FedAvg-BiGRU vs CentralLSTM | -9.37 | 7.37e-21 | 7.92 | 2.31e-15 | 20.37 | 3.46e-92 |

DM > 0: FedAvg-BiGRU has the larger errors. p < 0.05: the accuracy differs.

## Size and communication

| Model | Parameters | Model bytes | Rounds or epochs (best) | Bytes per round | Bytes in total | Break-even rounds | Training time (s) |
|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 27,589 | 110,356 | 17 (7) | 3,531,392 | 60,033,664 | 9.1 | 387.2 |
| FedAvg-LSTM | 18,501 | 74,004 | 16 (6) | 2,368,128 | 37,890,048 | 13.5 | 306.5 |
| CentralBiGRU | 27,589 | 110,356 | 33 (23) | – | 32,071,680 | – | 727.8 |
| CentralLSTM | 18,501 | 74,004 | 14 (4) | – | 32,071,680 | – | 292.4 |

Federated: bytes = model weights down and up for every chosen client. Central: bytes = every node's training and validation minutes (5 float32 features) sent once. Break-even rounds: after this many rounds FedAvg has sent as many bytes as the raw data.

Validation loss per round or epoch: validation_loss.csv and validation_loss.png.
