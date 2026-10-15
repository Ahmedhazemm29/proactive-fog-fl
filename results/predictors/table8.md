# Workload prediction, 16 synthetic FIFA nodes (like Dogani's Table 8)

W = 30 minutes, test part = last 20% of every node, errors pooled over all nodes' test windows, in requests per minute. MAPE in %.

| Model | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 | MAE t+4 | MAE t+5 | RMSE t+3 | RMSE t+4 | RMSE t+5 |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU (ours) | 13.96 | 14.41 | 12.82 | 506.4 | 549.4 | 592.0 | 2064.9 | 2208.4 | 2341.7 |
| FedAvg-LSTM (ours) | 16.47 | 14.24 | 15.46 | 525.4 | 564.2 | 614.8 | 2091.8 | 2233.0 | 2394.7 |
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
| FedAvg-BiGRU vs FedAvg-LSTM | -31.15 | 8.81e-213 | -20.05 | 2.41e-89 | -22.14 | 1.47e-108 |
| FedAvg-BiGRU vs CentralBiGRU | -9.55 | 1.36e-21 | -2.22 | 0.0265 | 9.64 | 5.52e-22 |
| FedAvg-BiGRU vs CentralLSTM | 2.98 | 0.00289 | 4.40 | 1.06e-05 | -1.16 | 0.245 |

DM > 0: FedAvg-BiGRU has the larger errors. p < 0.05: the accuracy differs.

## Size and communication

| Model | Parameters | Model bytes | Rounds or epochs | Bytes per round | Bytes in total | Training time (s) |
|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 27,589 | 110,356 | 14 | 3,531,392 | 49,439,488 | 359.8 |
| FedAvg-LSTM | 18,501 | 74,004 | 14 | 2,368,128 | 33,153,792 | 282.1 |
| CentralBiGRU | 27,589 | 110,356 | 14 | – | 32,071,680 | 319.7 |
| CentralLSTM | 18,501 | 74,004 | 16 | – | 32,071,680 | 312.1 |

Federated: bytes = model weights down and up for every chosen client. Central: bytes = every node's training and validation minutes (5 float32 features) sent once.
