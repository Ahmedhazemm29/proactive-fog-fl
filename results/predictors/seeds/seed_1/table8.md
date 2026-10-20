# Workload prediction, 16 synthetic FIFA nodes (like Dogani's Table 8)

W = 30 minutes, test part = last 20% of every node, errors pooled over all nodes' test windows, in requests per minute. MAPE in %.

| Model | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 | MAE t+4 | MAE t+5 | RMSE t+3 | RMSE t+4 | RMSE t+5 |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU (ours) | 13.36 | 13.73 | 13.40 | 499.1 | 540.4 | 582.1 | 2043.8 | 2184.1 | 2323.3 |
| FedAvg-LSTM (ours) | 16.44 | 16.23 | 15.74 | 509.8 | 551.3 | 591.5 | 2046.5 | 2185.6 | 2339.4 |
| CentralBiGRU (ours) | 14.55 | 13.19 | 20.68 | 502.0 | 538.0 | 603.1 | 2043.7 | 2172.6 | 2348.0 |
| CentralLSTM (ours) | 14.04 | 12.94 | 12.75 | 500.6 | 549.0 | 587.3 | 2045.2 | 2177.5 | 2323.5 |
| FedAvg-BiGRU (Dogani) | 9.04 | 10.2 | 11.2 | 166.8 | 241.3 | 221.9 | 316.9 | 389.2 | 437.7 |
| FedAvg-LSTM (Dogani) | 11.2 | 12.4 | 14.1 | 204.3 | 221.4 | 279.7 | 385.5 | 414.7 | 495.8 |
| CentralBiGRU (Dogani) | 8.49 | 9.66 | 10.45 | 156.5 | 213.0 | 224.8 | 296.7 | 351.8 | 406.3 |
| CentralLSTM (Dogani) | 10.4 | 11.3 | 13.1 | 192.7 | 208.8 | 263.9 | 364.5 | 392.1 | 449.1 |

MAPE skips minutes with 0 real requests: 51 per model and step (pooled over all nodes).

## Diebold-Mariano test (absolute errors)

| Pair | DM t+3 | p t+3 | DM t+4 | p t+4 | DM t+5 | p t+5 |
|---|---|---|---|---|---|---|
| FedAvg-BiGRU vs FedAvg-LSTM | -29.64 | 6.88e-193 | -20.51 | 2.06e-93 | -18.11 | 2.68e-73 |
| FedAvg-BiGRU vs CentralBiGRU | -8.29 | 1.13e-16 | 4.77 | 1.83e-06 | -24.00 | 3.32e-127 |
| FedAvg-BiGRU vs CentralLSTM | -3.42 | 0.000627 | -11.18 | 5.34e-29 | -8.41 | 4e-17 |

DM > 0: FedAvg-BiGRU has the larger errors. p < 0.05: the accuracy differs.

## Size and communication

| Model | Parameters | Model bytes | Rounds or epochs (best) | Bytes per round | Bytes in total | Break-even rounds | Training time (s) |
|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 27,589 | 110,356 | 35 (25) | 3,531,392 | 123,598,720 | 9.1 | 813.7 |
| FedAvg-LSTM | 18,501 | 74,004 | 49 (39) | 2,368,128 | 116,038,272 | 13.5 | 956.5 |
| CentralBiGRU | 27,589 | 110,356 | 21 (11) | – | 32,071,680 | – | 484.3 |
| CentralLSTM | 18,501 | 74,004 | 21 (11) | – | 32,071,680 | – | 397.8 |

Federated: bytes = model weights down and up for every chosen client. Central: bytes = every node's training and validation minutes (5 float32 features) sent once. Break-even rounds: after this many rounds FedAvg has sent as many bytes as the raw data.

Validation loss per round or epoch: validation_loss.csv and validation_loss.png.
