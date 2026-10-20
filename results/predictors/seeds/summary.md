# Table 8 seed check

All 4 Table 8 models trained again with seed 1, with the data and settings of the Table 8 run (seed 0, W = 30, patience 10, 16 nodes), and scored on the same test part (last 20% of every node). Written by `scripts/predictor_seeds.py`; each seed's own `table8.md` is in `seed_<n>/`.

Training time of all 4 models: seed 0 34.1 min, seed 1 44.3 min.

**Seeds 2 and 3 were not run.** The budget was about 75 minutes for the extra seeds. The estimate before the runs was 34 min per seed (the Table 8 run, 2,044 s on the same RTX 4060), so 3 seeds (about 102 min) could not fit, and 2 could. Seed 1 then took 44.3 min, because early stopping ended later (FedAvg-BiGRU 35 rounds instead of 19, FedAvg-LSTM 49 instead of 39), so a second seed would have ended at about 89 min, past the budget. With one new seed, the standard deviation below comes from two runs (seed 0 and seed 1).

## Mean ± sd over seed 0, 1

Seed 0 is the Table 8 run, so it counts as one of the seeds. The values of each seed are in the next section.

**MAPE (%)**

| Model | t+3 | t+4 | t+5 |
|---|---|---|---|
| FedAvg-BiGRU | 13.66 ± 0.42 | 14.07 ± 0.48 | 13.11 ± 0.41 |
| FedAvg-LSTM | 14.56 ± 2.66 | 14.56 ± 2.36 | 14.41 ± 1.88 |
| CentralBiGRU | 13.89 ± 0.93 | 15.24 ± 2.89 | 17.65 ± 4.29 |
| CentralLSTM | 13.00 ± 1.48 | 14.03 ± 1.55 | 12.99 ± 0.35 |

**MAE**

| Model | t+3 | t+4 | t+5 |
|---|---|---|---|
| FedAvg-BiGRU | 502.8 ± 5.1 | 544.9 ± 6.3 | 587.1 ± 6.9 |
| FedAvg-LSTM | 507.7 ± 3.0 | 550.8 ± 0.7 | 594.1 ± 3.8 |
| CentralBiGRU | 512.8 ± 15.2 | 545.3 ± 10.3 | 592.3 ± 15.2 |
| CentralLSTM | 502.3 ± 2.5 | 547.6 ± 1.9 | 590.1 ± 3.9 |

**RMSE**

| Model | t+3 | t+4 | t+5 |
|---|---|---|---|
| FedAvg-BiGRU | 2054.4 ± 15.0 | 2196.3 ± 17.2 | 2332.5 ± 13.0 |
| FedAvg-LSTM | 2054.2 ± 10.9 | 2193.4 ± 11.1 | 2345.7 ± 8.9 |
| CentralBiGRU | 2065.8 ± 31.2 | 2174.3 ± 2.3 | 2333.0 ± 21.2 |
| CentralLSTM | 2040.3 ± 6.9 | 2182.7 ± 7.3 | 2333.3 ± 13.9 |

## MAPE (%) of every seed

| Model | Step | Seed 0 (Table 8) | Seed 1 | Dogani |
|---|---|---|---|---|
| FedAvg-BiGRU | t+3 | 13.96 | 13.36 | 9.04 |
| FedAvg-BiGRU | t+4 | 14.41 | 13.73 | 10.2 |
| FedAvg-BiGRU | t+5 | 12.82 | 13.40 | 11.2 |
| FedAvg-LSTM | t+3 | 12.68 | 16.44 | 11.2 |
| FedAvg-LSTM | t+4 | 12.89 | 16.23 | 12.4 |
| FedAvg-LSTM | t+5 | 13.08 | 15.74 | 14.1 |
| CentralBiGRU | t+3 | 13.23 | 14.55 | 8.49 |
| CentralBiGRU | t+4 | 17.28 | 13.19 | 9.66 |
| CentralBiGRU | t+5 | 14.62 | 20.68 | 10.45 |
| CentralLSTM | t+3 | 11.95 | 14.04 | 10.4 |
| CentralLSTM | t+4 | 15.13 | 12.94 | 11.3 |
| CentralLSTM | t+5 | 13.24 | 12.75 | 13.1 |

## BiGRU vs LSTM per seed

The model with the lower error in each cell: B = BiGRU, L = LSTM. Dogani's own winners are in the last two rows. "Same as seed 0" and "same as Dogani" count the cells, of 9, with the same winner.

| Seed | Pair | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 | MAE t+4 | MAE t+5 | RMSE t+3 | RMSE t+4 | RMSE t+5 | BiGRU lower | Same as seed 0 | Same as Dogani |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | FedAvg | L | L | B | L | B | B | L | L | B | 4 of 9 | 9 of 9 | 3 of 9 |
| 0 | Central | L | L | L | L | L | B | L | B | B | 3 of 9 | 9 of 9 | 4 of 9 |
| 1 | FedAvg | B | B | B | B | B | B | B | B | B | 9 of 9 | 4 of 9 | 8 of 9 |
| 1 | Central | L | L | L | L | B | L | B | B | L | 3 of 9 | 5 of 9 | 2 of 9 |
| Dogani | FedAvg | B | B | B | B | L | B | B | B | B | 8 of 9 | | |
| Dogani | Central | B | B | B | B | L | B | B | B | B | 8 of 9 | | |
