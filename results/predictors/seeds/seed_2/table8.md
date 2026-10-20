# Workload prediction, 16 synthetic FIFA nodes (like Dogani's Table 8)

W = 30 minutes, test part = last 20% of every node, errors pooled over all nodes' test windows, in requests per minute. MAPE in %.

| Model | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 | MAE t+4 | MAE t+5 | RMSE t+3 | RMSE t+4 | RMSE t+5 |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU (ours) | 12.73 | 12.87 | 14.61 | 503.2 | 547.5 | 593.3 | 2056.0 | 2199.1 | 2362.3 |
| FedAvg-LSTM (ours) | 12.82 | 13.92 | 14.09 | 506.4 | 550.4 | 592.6 | 2070.0 | 2210.5 | 2349.1 |
| CentralBiGRU (ours) | 12.39 | 13.40 | 13.92 | 510.9 | 544.2 | 590.4 | 2032.9 | 2180.8 | 2341.1 |
| CentralLSTM (ours) | 13.04 | 15.39 | 12.69 | 496.5 | 546.0 | 583.2 | 2035.2 | 2170.2 | 2321.5 |
| FedAvg-BiGRU (Dogani) | 9.04 | 10.2 | 11.2 | 166.8 | 241.3 | 221.9 | 316.9 | 389.2 | 437.7 |
| FedAvg-LSTM (Dogani) | 11.2 | 12.4 | 14.1 | 204.3 | 221.4 | 279.7 | 385.5 | 414.7 | 495.8 |
| CentralBiGRU (Dogani) | 8.49 | 9.66 | 10.45 | 156.5 | 213.0 | 224.8 | 296.7 | 351.8 | 406.3 |
| CentralLSTM (Dogani) | 10.4 | 11.3 | 13.1 | 192.7 | 208.8 | 263.9 | 364.5 | 392.1 | 449.1 |

MAPE skips minutes with 0 real requests: 51 per model and step (pooled over all nodes).

## Diebold-Mariano test (absolute errors)

| Pair | DM t+3 | p t+3 | DM t+4 | p t+4 | DM t+5 | p t+5 |
|---|---|---|---|---|---|---|
| FedAvg-BiGRU vs FedAvg-LSTM | -7.14 | 9.09e-13 | -5.66 | 1.49e-08 | 1.12 | 0.264 |
| FedAvg-BiGRU vs CentralBiGRU | -13.74 | 5.85e-43 | 5.90 | 3.74e-09 | 4.34 | 1.4e-05 |
| FedAvg-BiGRU vs CentralLSTM | 12.27 | 1.31e-34 | 1.86 | 0.0624 | 10.93 | 8.47e-28 |

DM > 0: FedAvg-BiGRU has the larger errors. p < 0.05: the accuracy differs.

## Size and communication

| Model | Parameters | Model bytes | Rounds or epochs (best) | Bytes per round | Bytes in total | Break-even rounds | Training time (s) |
|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 27,589 | 110,356 | 25 (15) | 3,531,392 | 88,284,800 | 9.1 | 566.6 |
| FedAvg-LSTM | 18,501 | 74,004 | 38 (28) | 2,368,128 | 89,988,864 | 13.5 | 722.0 |
| CentralBiGRU | 27,589 | 110,356 | 25 (15) | – | 32,071,680 | – | 564.6 |
| CentralLSTM | 18,501 | 74,004 | 31 (21) | – | 32,071,680 | – | 583.6 |

Federated: bytes = model weights down and up for every chosen client. Central: bytes = every node's training and validation minutes (5 float32 features) sent once. Break-even rounds: after this many rounds FedAvg has sent as many bytes as the raw data.

Validation loss per round or epoch: validation_loss.csv and validation_loss.png.
