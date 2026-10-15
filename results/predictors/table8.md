# Workload prediction, 16 synthetic FIFA nodes (like Dogani's Table 8)

W = 30 minutes, test part = last 20% of every node, errors pooled over all nodes' test windows, in requests per minute. MAPE in %.

| Model | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 | MAE t+4 | MAE t+5 | RMSE t+3 | RMSE t+4 | RMSE t+5 |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU (ours) | 13.96 | 14.41 | 12.82 | 506.4 | 549.4 | 592.0 | 2064.9 | 2208.4 | 2341.7 |
| FedAvg-LSTM (ours) | 12.68 | 12.89 | 13.08 | 505.6 | 550.3 | 596.8 | 2061.9 | 2201.3 | 2351.9 |
| CentralBiGRU (ours) | 13.23 | 17.28 | 14.62 | 523.6 | 552.6 | 581.6 | 2087.8 | 2175.9 | 2318.0 |
| CentralLSTM (ours) | 11.95 | 15.13 | 13.24 | 504.1 | 546.3 | 592.9 | 2035.4 | 2187.8 | 2343.2 |
| FedAvg-BiGRU (Dogani) | 9.04 | 10.2 | 11.2 | 166.8 | 241.3 | 221.9 | 316.9 | 389.2 | 437.7 |
| FedAvg-LSTM (Dogani) | 11.2 | 12.4 | 14.1 | 204.3 | 221.4 | 279.7 | 385.5 | 414.7 | 495.8 |
| CentralBiGRU (Dogani) | 8.49 | 9.66 | 10.45 | 156.5 | 213.0 | 224.8 | 296.7 | 351.8 | 406.3 |
| CentralLSTM (Dogani) | 10.4 | 11.3 | 13.1 | 192.7 | 208.8 | 263.9 | 364.5 | 392.1 | 449.1 |

MAPE skips minutes with 0 real requests: 51 per model and step (pooled over all nodes).

## Diebold-Mariano test (absolute errors)

| Pair | DM t+3 | p t+3 | DM t+4 | p t+4 | DM t+5 | p t+5 |
|---|---|---|---|---|---|---|
| FedAvg-BiGRU vs FedAvg-LSTM | 1.41 | 0.158 | -1.49 | 0.137 | -6.43 | 1.27e-10 |
| FedAvg-BiGRU vs CentralBiGRU | -9.55 | 1.36e-21 | -2.22 | 0.0265 | 9.64 | 5.52e-22 |
| FedAvg-BiGRU vs CentralLSTM | 2.98 | 0.00289 | 4.40 | 1.06e-05 | -1.16 | 0.245 |

DM > 0: FedAvg-BiGRU has the larger errors. p < 0.05: the accuracy differs.

## Size and communication

| Model | Parameters | Model bytes | Rounds or epochs (best) | Bytes per round | Bytes in total | Break-even rounds | Training time (s) |
|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 27,589 | 110,356 | 19 (9) | 3,531,392 | 67,096,448 | 9.1 | 432.5 |
| FedAvg-LSTM | 18,501 | 74,004 | 39 (29) | 2,368,128 | 92,356,992 | 13.5 | 758.8 |
| CentralBiGRU | 27,589 | 110,356 | 19 (9) | – | 32,071,680 | – | 442.6 |
| CentralLSTM | 18,501 | 74,004 | 21 (11) | – | 32,071,680 | – | 404.6 |

Federated: bytes = model weights down and up for every chosen client. Central: bytes = every node's training and validation minutes (5 float32 features) sent once. Break-even rounds: after this many rounds FedAvg has sent as many bytes as the raw data.

Validation loss per round or epoch: validation_loss.csv and validation_loss.png.
