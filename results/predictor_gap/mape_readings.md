# Which MAPE did Dogani compute?

The same saved forecasts (W = 30, test part of all 16 nodes) under every reading of Eq. 13. "3 seeds" is the mean of the MAPEs of FedAvg-BiGRU seeds 0, 1 and 2. "Naive" repeats the last input minute.

## 1. Where the minutes land on [-1, 1] (FedAvg-BiGRU seed 0, t+3)

| Band | Share of minutes | Position on [-1, 1], mean (range) | MAPE, real requests | MAPE, [-1, 1] |
|---|---|---|---|---|
| quiet (0 to 0.25 x node mean) | 31.1% | -0.99 (-1.00 to -0.95) | 36.23 | 0.07 |
| normal (0.25 to 2 x node mean) | 57.5% | -0.93 (-0.99 to -0.62) | 3.65 | 0.28 |
| busy (2 to inf x node mean) | 11.5% | -0.64 (-0.95 to +1.39) | 5.27 | 34.40 |

Minutes within 0.05 of 0 on [-1, 1]: 910 (0.23%). Their MAPE is 1291.7%, the largest single error 76723%, and they add 2.94 points to the total. The closest real minute to 0 is at 0.0000.

## 2. MAPE (%) under every reading, t+3 / t+4 / t+5

| Reading | FedAvg-BiGRU seed 0 | 3 seeds | Naive | 3 seeds / naive at t+3 |
|---|---|---|---|---|
| a. Real requests, skip only zeros (ours) | 13.96 / 14.41 / 12.82 | 13.35 / 13.67 / 13.61 | 13.13 / 13.58 / 14.02 | 1.02 |
| b1. Real requests, skip below 1% of the node mean | 5.17 / 5.52 / 5.70 | 5.05 / 5.44 / 5.76 | 5.26 / 5.68 / 6.09 | 0.96 |
| b5. Real requests, skip below 5% of the node mean | 4.71 / 5.03 / 5.21 | 4.57 / 4.94 / 5.24 | 4.78 / 5.16 / 5.55 | 0.96 |
| b10. Real requests, skip below 10% of the node mean | 4.36 / 4.66 / 4.85 | 4.24 / 4.59 / 4.88 | 4.44 / 4.81 / 5.17 | 0.96 |
| c. Real requests, each node first, then the mean over nodes | 13.96 / 14.41 / 12.82 | 13.35 / 13.67 / 13.61 | 13.13 / 13.58 / 14.02 | 1.02 |
| d. Real requests, one total trace of all 16 nodes | 2.49 / 2.71 / 2.93 | 2.51 / 2.74 / 2.96 | 2.79 / 3.02 / 3.27 | 0.90 |
| e1. [0, 1], each node's own scaling | 14.40 / 14.96 / 13.31 | 13.73 / 14.15 / 14.13 | 13.43 / 14.00 / 14.49 | 1.02 |
| e2. [-1, 1], each node's own scaling | 4.13 / 4.52 / 4.80 | 4.11 / 4.52 / 4.71 | 4.89 / 5.11 / 5.84 | 0.84 |
| e3. [0, 1], one scaling for all nodes | 13.96 / 14.41 / 12.82 | 13.35 / 13.67 / 13.61 | 13.13 / 13.58 / 14.02 | 1.02 |
| e4. [-1, 1], one scaling for all nodes | 8.74 / 9.39 / 9.78 | 8.50 / 9.21 / 9.31 | 10.53 / 12.08 / 10.55 | 0.81 |

Dogani's FedAvg-BiGRU: 9.04 / 10.2 / 11.2.

## 3. What Dogani's MAE and MAPE imply, per reading

Dogani's FedAvg-BiGRU: MAE 166.8 / 241.3 / 221.9 and MAPE 9.04 / 10.2 / 11.2 at t+3 / t+4 / t+5. If his errors have the same shape as ours, MAE / mean traffic is the same multiple of MAPE for him and for us. That gives the mean traffic his numbers imply. The FIFA trace has 1,352,804,107 requests over 88 days: 10,676 per minute if every node gets the whole trace, 667 if it is split over 16 nodes. MAE is measured on the test part, so the candidates also include the real trace's test part, the last 20% of the days and the end of the tournament: 4,214 per minute, or 263 split over 16 nodes. Reading d is the total of all nodes, so its candidates are 16 times larger.

| Reading | Implied mean per minute, t+3 / t+4 / t+5 | Nearest candidate | Off by | Dogani / our naive, t+3 |
|---|---|---|---|---|
| a. Real requests, skip only zeros (ours) | 4,685 / 5,667 / 4,377 | whole trace per node, its test part (4,214) | x1.11 | 0.69 |
| e3. [0, 1], one scaling for all nodes | 4,685 / 5,667 / 4,377 | whole trace per node, its test part (4,214) | x1.11 | 0.69 |
| c. Real requests, each node first, then the mean over nodes | 4,685 / 5,668 / 4,377 | whole trace per node, its test part (4,214) | x1.11 | 0.69 |
| e1. [0, 1], each node's own scaling | 4,818 / 5,864 / 4,544 | whole trace per node, its test part (4,214) | x1.14 | 0.67 |
| e4. [-1, 1], one scaling for all nodes | 2,983 / 3,819 / 2,993 | whole trace per node, its test part (4,214) | x1.41 | 0.86 |
| e2. [-1, 1], each node's own scaling | 1,441 / 1,874 / 1,515 | trace split over 16 nodes, all days (667) | x2.16 | 1.85 |
| b10. Real requests, skip below 10% of the node mean | 1,489 / 1,901 / 1,569 | trace split over 16 nodes, all days (667) | x2.23 | 2.03 |
| b1. Real requests, skip below 1% of the node mean | 1,771 / 2,254 / 1,853 | whole trace per node, its test part (4,214) | x2.38 | 1.72 |
| b5. Real requests, skip below 5% of the node mean | 1,605 / 2,046 / 1,687 | trace split over 16 nodes, all days (667) | x2.41 | 1.89 |
| d. Real requests, one total trace of all 16 nodes | 1,534 / 1,975 / 1,663 | trace split over 16 nodes, its test part (4,214) | x2.75 | 3.24 |

"Off by" compares the t+3 value with the nearest candidate. "Dogani / our naive" is his MAPE divided by the MAPE of repeating the last minute on our data under the same reading: below 1 means better than the naive forecast.

## 4. Model error / naive error (unit-free)

| Run | MAPE ratio t+3 / t+4 / t+5 | MAE ratio t+3 / t+4 / t+5 |
|---|---|---|
| FedAvg-BiGRU seed 0 | 1.06 / 1.06 / 0.91 | 0.90 / 0.90 / 0.90 |
| FedAvg-BiGRU seed 1 | 1.02 / 1.01 / 0.96 | 0.89 / 0.89 / 0.89 |
| FedAvg-BiGRU seed 2 | 0.97 / 0.95 / 1.04 | 0.90 / 0.90 / 0.90 |
| CentralBiGRU seed 0 | 1.01 / 1.27 / 1.04 | 0.93 / 0.91 / 0.88 |
| FedAvg-BiGRU [-1, 1] | 1.08 / 1.03 / 1.00 | 0.91 / 0.90 / 0.89 |
| CentralBiGRU [-1, 1] | 1.12 / 1.58 / 1.75 | 0.96 / 0.95 / 0.94 |
| 3 seeds | 1.02 / 1.01 / 0.97 | 0.90 / 0.90 / 0.90 |

## 5. Trained on [-1, 1] (seed 0)

| Run | MAPE real, t+3 / t+4 / t+5 | MAPE on [-1, 1], t+3 | MAE t+3 | Quiet minutes, MAPE t+3 |
|---|---|---|---|---|
| FedAvg-BiGRU seed 0 | 13.96 / 14.41 / 12.82 | 4.13 | 506.4 | 36.23 |
| FedAvg-BiGRU [-1, 1] | 14.22 / 14.04 / 14.07 | 4.05 | 510.0 | 37.05 |
| CentralBiGRU seed 0 | 13.23 / 17.28 / 14.62 | 4.61 | 523.6 | 33.55 |
| CentralBiGRU [-1, 1] | 14.72 / 21.50 / 24.51 | 4.58 | 538.7 | 36.96 |
