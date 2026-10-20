# Table 8 seed check

All 4 Table 8 models trained again with seed 1, 2, 3, with the data and settings of the Table 8 run (seed 0, W = 30, patience 10, 16 nodes), and scored on the same test part (last 20% of every node). Written by `scripts/predictor_seeds.py`; each seed's own `table8.md` is in `seed_<n>/`.

Training time of all 4 models: seed 0 34.1 min, seed 1 44.3 min, seed 2 40.7 min, seed 3 28.7 min.

## Mean ± sd over seed 0, 1, 2, 3

Seed 0 is the Table 8 run, so it counts as one of the seeds. The values of each seed are in the next section.

**MAPE (%)**

| Model | t+3 | t+4 | t+5 |
|---|---|---|---|
| FedAvg-BiGRU | 13.31 ± 0.51 | 14.14 ± 1.13 | 14.75 ± 2.39 |
| FedAvg-LSTM | 14.24 ± 1.82 | 14.86 ± 1.73 | 14.68 ± 1.32 |
| CentralBiGRU | 13.04 ± 1.13 | 14.15 ± 2.11 | 16.08 ± 3.11 |
| CentralLSTM | 13.73 ± 1.67 | 13.95 ± 1.53 | 12.93 ± 0.26 |

**MAE**

| Model | t+3 | t+4 | t+5 |
|---|---|---|---|
| FedAvg-BiGRU | 504.5 ± 4.3 | 548.9 ± 7.3 | 595.5 ± 13.7 |
| FedAvg-LSTM | 511.0 ± 7.7 | 555.8 ± 10.2 | 599.1 ± 11.2 |
| CentralBiGRU | 510.1 ± 9.8 | 546.9 ± 7.2 | 589.4 ± 9.9 |
| CentralLSTM | 504.2 ± 8.1 | 548.0 ± 2.3 | 588.8 ± 4.5 |

**RMSE**

| Model | t+3 | t+4 | t+5 |
|---|---|---|---|
| FedAvg-BiGRU | 2056.8 ± 9.5 | 2202.4 ± 14.5 | 2354.7 ± 29.3 |
| FedAvg-LSTM | 2068.1 ± 19.9 | 2208.8 ± 21.9 | 2358.2 ± 23.4 |
| CentralBiGRU | 2047.9 ± 27.5 | 2176.1 ± 3.4 | 2332.9 ± 14.0 |
| CentralLSTM | 2042.5 ± 9.0 | 2181.5 ± 9.3 | 2335.4 ± 15.4 |

## MAPE (%) of every seed

| Model | Step | Seed 0 (Table 8) | Seed 1 | Seed 2 | Seed 3 | Dogani |
|---|---|---|---|---|---|---|
| FedAvg-BiGRU | t+3 | 13.96 | 13.36 | 12.73 | 13.19 | 9.04 |
| FedAvg-BiGRU | t+4 | 14.41 | 13.73 | 12.87 | 15.54 | 10.2 |
| FedAvg-BiGRU | t+5 | 12.82 | 13.40 | 14.61 | 18.16 | 11.2 |
| FedAvg-LSTM | t+3 | 12.68 | 16.44 | 12.82 | 15.03 | 11.2 |
| FedAvg-LSTM | t+4 | 12.89 | 16.23 | 13.92 | 16.39 | 12.4 |
| FedAvg-LSTM | t+5 | 13.08 | 15.74 | 14.09 | 15.78 | 14.1 |
| CentralBiGRU | t+3 | 13.23 | 14.55 | 12.39 | 11.99 | 8.49 |
| CentralBiGRU | t+4 | 17.28 | 13.19 | 13.40 | 12.72 | 9.66 |
| CentralBiGRU | t+5 | 14.62 | 20.68 | 13.92 | 15.08 | 10.45 |
| CentralLSTM | t+3 | 11.95 | 14.04 | 13.04 | 15.88 | 10.4 |
| CentralLSTM | t+4 | 15.13 | 12.94 | 15.39 | 12.35 | 11.3 |
| CentralLSTM | t+5 | 13.24 | 12.75 | 12.69 | 13.06 | 13.1 |

## BiGRU vs LSTM per seed

The model with the lower error in each cell: B = BiGRU, L = LSTM. Dogani's own winners are in the last two rows. "Same as seed 0" and "same as Dogani" count the cells, of 9, with the same winner.

| Seed | Pair | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 | MAE t+4 | MAE t+5 | RMSE t+3 | RMSE t+4 | RMSE t+5 | BiGRU lower | Same as seed 0 | Same as Dogani |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | FedAvg | L | L | B | L | B | B | L | L | B | 4 of 9 | 9 of 9 | 3 of 9 |
| 0 | Central | L | L | L | L | L | B | L | B | B | 3 of 9 | 9 of 9 | 4 of 9 |
| 1 | FedAvg | B | B | B | B | B | B | B | B | B | 9 of 9 | 4 of 9 | 8 of 9 |
| 1 | Central | L | L | L | L | B | L | B | B | L | 3 of 9 | 5 of 9 | 2 of 9 |
| 2 | FedAvg | B | B | L | B | B | L | B | B | L | 6 of 9 | 1 of 9 | 5 of 9 |
| 2 | Central | B | B | L | L | B | L | B | L | L | 4 of 9 | 2 of 9 | 3 of 9 |
| 3 | FedAvg | B | B | L | B | B | B | B | B | B | 8 of 9 | 3 of 9 | 7 of 9 |
| 3 | Central | B | L | L | B | L | B | B | B | B | 6 of 9 | 6 of 9 | 7 of 9 |
| Dogani | FedAvg | B | B | B | B | L | B | B | B | B | 8 of 9 | | |
| Dogani | Central | B | B | B | B | L | B | B | B | B | 8 of 9 | | |
