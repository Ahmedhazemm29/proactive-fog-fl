# Table 8 on random windows

The trained seed-0 models of `results/predictors/table8.md` (no retraining), scored on 30 random windows of the test part instead of the whole test part. A window is 1440 consecutive forecasts (1 day), the same minutes on all 16 nodes, starting at a random point (seed 1, `windows.csv`). In a window the errors are pooled over the 16 nodes with the rules of table8.md: real requests, MAPE skips minutes with 0 real requests. The test part has 25,022 forecasts per node (about 17.4 days), so the windows overlap. Written by `scripts/table8_random_windows.py`.

Check: scored on the whole test part, these weights give table8.md's numbers (largest relative difference 0.0e+00).

## Mean ± sd over the windows, and where Table 8 falls

"Table 8" is the value of table8.md (whole test part). "Below" is the share of windows with a lower value than Table 8.

**MAPE (%)**

| Model | t+3 mean ± sd | t+3 min to max | t+3 Table 8 (below) | t+4 mean ± sd | t+4 min to max | t+4 Table 8 (below) | t+5 mean ± sd | t+5 min to max | t+5 Table 8 (below) |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 14.40 ± 8.54 | 5.45 to 33.74 | 13.96 (60%) | 14.91 ± 8.72 | 6.17 to 34.66 | 14.41 (63%) | 13.33 ± 6.81 | 5.63 to 28.10 | 12.82 (53%) |
| FedAvg-LSTM | 12.98 ± 7.58 | 5.49 to 29.97 | 12.68 (70%) | 13.17 ± 7.45 | 5.68 to 29.47 | 12.89 (70%) | 13.41 ± 7.16 | 5.69 to 29.37 | 13.08 (63%) |
| CentralBiGRU | 14.21 ± 7.22 | 5.90 to 29.75 | 13.23 (50%) | 18.16 ± 10.11 | 7.29 to 42.54 | 17.28 (63%) | 15.79 ± 8.00 | 5.88 to 32.03 | 14.62 (50%) |
| CentralLSTM | 12.45 ± 6.22 | 5.65 to 25.20 | 11.95 (50%) | 15.65 ± 9.02 | 6.10 to 35.70 | 15.13 (60%) | 13.69 ± 6.98 | 5.75 to 29.37 | 13.24 (60%) |

**MAE (requests/min)**

| Model | t+3 mean ± sd | t+3 min to max | t+3 Table 8 (below) | t+4 mean ± sd | t+4 min to max | t+4 Table 8 (below) | t+5 mean ± sd | t+5 min to max | t+5 Table 8 (below) |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 534.9 ± 164.6 | 308.9 to 866.5 | 506.4 (57%) | 580.6 ± 179.3 | 332.1 to 953.5 | 549.4 (57%) | 627.9 ± 192.5 | 358.1 to 1033.7 | 592.0 (57%) |
| FedAvg-LSTM | 535.2 ± 165.9 | 312.1 to 868.6 | 505.6 (57%) | 582.9 ± 180.4 | 336.7 to 955.4 | 550.3 (57%) | 634.0 ± 194.9 | 363.0 to 1041.1 | 596.8 (57%) |
| CentralBiGRU | 554.7 ± 173.4 | 322.5 to 904.5 | 523.6 (53%) | 583.8 ± 177.1 | 342.6 to 961.3 | 552.6 (57%) | 618.2 ± 193.1 | 354.8 to 1014.4 | 581.6 (57%) |
| CentralLSTM | 532.6 ± 162.9 | 314.1 to 864.4 | 504.1 (57%) | 578.5 ± 178.9 | 336.7 to 949.6 | 546.3 (57%) | 628.5 ± 191.4 | 362.3 to 1035.5 | 592.9 (57%) |

**RMSE (requests/min)**

| Model | t+3 mean ± sd | t+3 min to max | t+3 Table 8 (below) | t+4 mean ± sd | t+4 min to max | t+4 Table 8 (below) | t+5 mean ± sd | t+5 min to max | t+5 Table 8 (below) |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 2036.5 ± 556.8 | 1102.7 to 3261.0 | 2064.9 (53%) | 2188.3 ± 586.7 | 1181.5 to 3398.1 | 2208.4 (57%) | 2337.9 ± 597.1 | 1293.8 to 3524.4 | 2341.7 (70%) |
| FedAvg-LSTM | 2039.6 ± 555.8 | 1104.5 to 3251.0 | 2061.9 (50%) | 2188.6 ± 579.3 | 1192.5 to 3378.2 | 2201.3 (63%) | 2352.0 ± 601.1 | 1311.3 to 3548.1 | 2351.9 (67%) |
| CentralBiGRU | 2072.9 ± 551.9 | 1140.5 to 3264.0 | 2087.8 (63%) | 2165.0 ± 572.6 | 1177.3 to 3328.5 | 2175.9 (63%) | 2316.1 ± 597.4 | 1288.0 to 3505.9 | 2318.0 (70%) |
| CentralLSTM | 2011.2 ± 543.6 | 1083.6 to 3193.5 | 2035.4 (50%) | 2171.9 ± 576.0 | 1173.0 to 3347.1 | 2187.8 (63%) | 2340.2 ± 594.8 | 1302.8 to 3530.7 | 2343.2 (70%) |

## How often each model ranks first

Windows (of 30) in which the model has the lowest error of the four.

| Model | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 | MAE t+4 | MAE t+5 | RMSE t+3 | RMSE t+4 | RMSE t+5 |
|---|---|---|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 2 | 0 | 16 | 7 | 4 | 4 | 5 | 7 | 8 |
| FedAvg-LSTM | 15 | 30 | 11 | 9 | 0 | 0 | 3 | 1 | 0 |
| CentralBiGRU | 0 | 0 | 0 | 0 | 5 | 25 | 2 | 10 | 22 |
| CentralLSTM | 13 | 0 | 3 | 14 | 21 | 1 | 20 | 12 | 0 |

## BiGRU vs LSTM per step

Windows (of 30) in which BiGRU has the lower error than LSTM. In brackets: the winner in table8.md (B = BiGRU, L = LSTM).

| Pair | Metric | t+3 | t+4 | t+5 |
|---|---|---|---|---|
| FedAvg | MAPE | 2 (L) | 0 (L) | 17 (B) |
| FedAvg | MAE | 17 (L) | 24 (B) | 29 (B) |
| FedAvg | RMSE | 18 (L) | 19 (L) | 24 (B) |
| Central | MAPE | 1 (L) | 2 (L) | 4 (L) |
| Central | MAE | 0 (L) | 8 (L) | 26 (B) |
| Central | RMSE | 2 (L) | 13 (B) | 28 (B) |

Box plots: `boxplot_mape.png`, `boxplot_mae.png`, `boxplot_rmse.png` (and .pdf).
