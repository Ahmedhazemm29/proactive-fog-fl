# Chapter 2: Prediction

Tags: `D x.y` = docs/decisions.md entry; `T8` = results/predictors/table8.md (patience 10, final); `T8p5` = results/predictors_patience5/table8.md.

## 2.1 Models and settings
- Models: FedAvg-BiGRU, FedAvg-LSTM, CentralBiGRU, CentralLSTM. [T8]
- Plain BiGRU: one layer, merge mode sum; plain LSTM; each followed by dropout 0.3 and a linear layer to 5 outputs. [D 3.5]
- Hidden units 64 for both. Parameters: BiGRU 27,589 (110,356 bytes); LSTM 18,501 (74,004 bytes). [D 3.3; T8]
- Adam, loss MAE, batch size 60, dropout 0.3, up to 64 epochs; learning rate 0.001 (Adam default, Dogani gives none). Seed 0. [D 3.6; results/predictors/report.json]
- Window length W = 30: validation MAE 0.00321 vs 0.00326 for W = 60 (FedAvg-BiGRU). [D 3.2; report.json window_selection]
- Device used for training: cuda. [results/predictors/report.json]

## 2.2 Federated training
- FedAvg per Dogani Algorithm 2 (Sec. 5.2, p. 8): local epochs per client, weights averaged by number of samples. [D 3.7]
- Ours: all 16 clients every round (fraction 1.0), E = 1 local epoch, average by number of training windows, fresh Adam each round, up to 100 rounds. [D 3.7; report.json]
- Everything in one process, client/server structure matching Flower. [D 3.7]
- Early stopping: patience 10 on validation loss, caps 100 rounds / 64 epochs, best weights kept. [D 3.8]
- Patience 5 stopped every model after 14 to 16 rounds/epochs; only FedAvg-LSTM improved with patience 10 (best round 29 instead of 9). Other three identical. Both kept: results/predictors_patience5/ and results/predictors/. [D 3.8]
- Rounds or epochs run (best): FedAvg-BiGRU 19 (9); FedAvg-LSTM 39 (29); CentralBiGRU 19 (9); CentralLSTM 21 (11). [T8; results/predictors/cost.csv]
- Training time (s): FedAvg-BiGRU 432.5; FedAvg-LSTM 758.8; CentralBiGRU 442.6; CentralLSTM 404.6. [cost.csv]
- Patience 5 run: 14/14/14/16 rounds-epochs; times 359.8, 282.1, 319.7, 312.1 s. [T8p5]
- Validation loss per round: results/predictors/validation_loss.csv, figure `figures/prediction/validation_loss_patience10.png`.

## 2.3 Metrics
- MAPE (Dogani Eq. 13, p. 10) divides by the real value; zero minutes skipped, 51 per model and step (pooled over 16 nodes). MAE and RMSE use all minutes. [D 3.9]
- Early bug: real values came back from scaling slightly above 0, MAPE reached millions of percent; real values now rounded to whole requests. [D 3.9]
- Errors pooled over all nodes' test windows, in requests per minute. [T8]
- Diebold-Mariano: absolute errors, overlap of multi-step forecasts accounted for, Harvey-Leybourne-Newbold correction; FedAvg-BiGRU vs each other model at t+3, t+4, t+5. [D 3.10]

## 2.4 Accuracy (Table 8 replica; `tables/table8_accuracy.tex`)
- FedAvg-BiGRU (ours): MAPE 13.96 / 14.41 / 12.82; MAE 506.4 / 549.4 / 592.0; RMSE 2064.9 / 2208.4 / 2341.7 (t+3 / t+4 / t+5). [T8]
- FedAvg-LSTM (ours): MAPE 12.68 / 12.89 / 13.08; MAE 505.6 / 550.3 / 596.8; RMSE 2061.9 / 2201.3 / 2351.9. [T8]
- CentralBiGRU (ours): MAPE 13.23 / 17.28 / 14.62; MAE 523.6 / 552.6 / 581.6; RMSE 2087.8 / 2175.9 / 2318.0. [T8]
- CentralLSTM (ours): MAPE 11.95 / 15.13 / 13.24; MAE 504.1 / 546.3 / 592.9; RMSE 2035.4 / 2187.8 / 2343.2. [T8]
- Dogani Table 8 (p. 13) FedAvg-BiGRU: MAPE 9.04 / 10.2 / 11.2; MAE 166.8 / 241.3 / 221.9; RMSE 316.9 / 389.2 / 437.7. [T8]
- Dogani FedAvg-LSTM: MAPE 11.2 / 12.4 / 14.1; MAE 204.3 / 221.4 / 279.7; RMSE 385.5 / 414.7 / 495.8. [T8]
- Dogani CentralBiGRU: MAPE 8.49 / 9.66 / 10.45; MAE 156.5 / 213.0 / 224.8; RMSE 296.7 / 351.8 / 406.3. [T8]
- Dogani CentralLSTM: MAPE 10.4 / 11.3 / 13.1; MAE 192.7 / 208.8 / 263.9; RMSE 364.5 / 392.1 / 449.1. [T8]
- MAE of federated and central BiGRU within 3.5% at every step. [D 4.3]
- Our MAPE for FedAvg-BiGRU 12.8 to 14.4% vs Dogani 9.0 to 11.2%. [D 4.5]
- MAE/RMSE not comparable: our traces average ~10,800 req/min, busiest minute ~229,000; Dogani's scaling is unknown. Only MAPE comparable. [D 4.5]
- Patience 5, FedAvg-LSTM (ours): MAPE 16.47 / 14.24 / 15.46; MAE 525.4 / 564.2 / 614.8; RMSE 2091.8 / 2233.0 / 2394.7. Other rows identical to patience 10. [T8p5]

## 2.5 Significance (`tables/table9_dm_test.tex`)
- BiGRU vs LSTM (federated), patience 10: DM 1.41 (p 0.158), -1.49 (p 0.137), -6.43 (p 1.27e-10) at t+3/t+4/t+5. [T8]
- Federated BiGRU vs CentralBiGRU: DM -9.55 (p 1.36e-21), -2.22 (p 0.0265), 9.64 (p 5.52e-22). [T8]
- FedAvg-BiGRU vs CentralLSTM: DM 2.98 (p 0.00289), 4.40 (p 1.06e-05), -1.16 (p 0.245). [T8]
- DM > 0 means FedAvg-BiGRU has the larger errors; p < 0.05 means accuracy differs. [T8]
- Patience 5, BiGRU vs LSTM: p 8.81e-213, 2.41e-89, 1.47e-108 (BiGRU better at all steps because FedAvg-LSTM stopped early). [T8p5; D 4.2]
- Dogani Table 9 (p. 15): BiGRU vs LSTM p 2.85e-12, 2.43e-07, 4.45e-06; federated vs central BiGRU p 0.062, 0.195, 0.185 (not significant). [D 4.2, D 4.3]
- Our federated-vs-central: significant at every step (about 400,000 test windows make small differences significant). BiGRU federated better at t+3, t+4, worse at t+5. [D 4.3]

## 2.6 Communication (`tables/fl_bytes_breakeven.tex`)
- Federated bytes per round = model weights down and up for all 16 clients: BiGRU 3,531,392; LSTM 2,368,128. [T8; D 4.4]
- Central bytes = all nodes' training and validation minutes, 5 float32 features, sent once: 32,071,680. [T8; D 4.4]
- Break-even rounds: BiGRU 9.1, LSTM 13.5. [cost.csv]
- Total bytes our runs: BiGRU 67,096,448 (19 rounds); LSTM 92,356,992 (39 rounds). [T8]
- Patience 5 totals: BiGRU 49,439,488; LSTM 33,153,792 (14 rounds each). [T8p5]
- Dogani claims a remarkable data-transmission reduction (p. 14) without measuring it. [D 4.4]
- FL saves bytes only if training stops within about 9 to 13 rounds; the clear advantage is privacy. [D 4.4]

## 2.7 Figures
- `figures/prediction/prediction_node00_patience10.png`: forecast vs real, node 0, 6 h plot (settings: plot_hours 6, plot_node 0). [report.json]
- `figures/prediction/prediction_node00_patience5.png`: same, patience 5.
- `figures/prediction/validation_loss_patience10.png`: validation loss per round/epoch.
