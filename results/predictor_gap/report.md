# Predictor gap to Dogani: checks without new training

Step 3 models (W = 30), test part of all 16 nodes pooled. Persistence repeats the last input minute. MAPE skips minutes with 0 real requests.

## MAPE (%) at every step

| Model | t+1 | t+2 | t+3 | t+4 | t+5 | Dogani t+3 / t+4 / t+5 |
|---|---|---|---|---|---|---|
| FedAvg-BiGRU | 11.95 | 11.82 | 13.96 | 14.41 | 12.82 | 9.04 / 10.2 / 11.2 |
| FedAvg-LSTM | 12.84 | 12.51 | 12.68 | 12.89 | 13.08 | 11.2 / 12.4 / 14.1 |
| CentralBiGRU | 11.04 | 11.60 | 13.23 | 17.28 | 14.62 | 8.49 / 9.66 / 10.45 |
| CentralLSTM | 12.14 | 16.24 | 11.95 | 15.13 | 13.24 | 10.4 / 11.3 / 13.1 |
| Persistence | 11.68 | 12.40 | 13.13 | 13.58 | 14.02 | – |

## MAE (requests per minute) at every step

| Model | t+1 | t+2 | t+3 | t+4 | t+5 |
|---|---|---|---|---|---|
| FedAvg-BiGRU | 417.4 | 460.9 | 506.4 | 549.4 | 592.0 |
| FedAvg-LSTM | 418.6 | 461.6 | 505.6 | 550.3 | 596.8 |
| CentralBiGRU | 424.7 | 468.8 | 523.6 | 552.6 | 581.6 |
| CentralLSTM | 426.0 | 470.7 | 504.1 | 546.3 | 592.9 |
| Persistence | 470.8 | 519.1 | 561.8 | 609.2 | 657.6 |

## MAPE at t+3, computed different ways

| Model | Real requests (ours) | Min-max [0, 1] | Min-max [-1, 1] |
|---|---|---|---|
| FedAvg-BiGRU | 13.96 | 14.40 | 4.13 |
| CentralBiGRU | 13.23 | 13.56 | 4.61 |

## MAPE at t+3 by traffic level

Level = the real requests of the minute divided by the node's test mean.

| Level | Share of minutes | FedAvg-BiGRU | CentralBiGRU |
|---|---|---|---|
| 0 to 0.25 x mean | 31.1% | 36.18 | 33.50 |
| 0.25 to 0.5 x mean | 22.4% | 3.99 | 4.09 |
| 0.5 to 1 x mean | 18.1% | 3.66 | 3.78 |
| 1 to 2 x mean | 16.9% | 3.20 | 3.40 |
| 2 to inf x mean | 11.5% | 5.28 | 5.50 |

## How bursty is each test part

CV = std / mean. 1-minute change = mean absolute change from one minute to the next, divided by the mean. The real trace is the FIFA trace over the same minutes (the last 20% of days 6 to 92).

| Series | Mean | CV | Peak/mean | 1-minute change | Lag-1 ACF | Persistence MAPE t+3 |
|---|---|---|---|---|---|---|
| node_00 | 7,737 | 1.71 | 24.7 | 4.4% | 0.9953 | 16.51 |
| node_01 | 13,121 | 1.46 | 17.2 | 4.6% | 0.9925 | 5.50 |
| node_02 | 7,700 | 1.41 | 29.3 | 3.9% | 0.9945 | 8.39 |
| node_03 | 12,980 | 1.82 | 17.4 | 5.5% | 0.9918 | 3.59 |
| node_04 | 4,587 | 1.60 | 21.9 | 3.7% | 0.9965 | 20.78 |
| node_05 | 3,790 | 1.60 | 30.2 | 2.9% | 0.9974 | 4.68 |
| node_06 | 18,037 | 1.53 | 12.5 | 6.0% | 0.9921 | 26.52 |
| node_07 | 4,435 | 1.93 | 46.1 | 4.0% | 0.9944 | 13.96 |
| node_08 | 16,816 | 1.51 | 13.6 | 5.7% | 0.9919 | 13.29 |
| node_09 | 10,486 | 1.18 | 17.5 | 3.9% | 0.9945 | 20.12 |
| node_10 | 3,942 | 2.71 | 58.2 | 5.1% | 0.9920 | 15.44 |
| node_11 | 12,280 | 1.37 | 18.2 | 4.8% | 0.9931 | 6.00 |
| node_12 | 16,201 | 1.50 | 13.9 | 5.4% | 0.9921 | 13.07 |
| node_13 | 3,072 | 2.31 | 42.7 | 4.0% | 0.9959 | 11.21 |
| node_14 | 4,379 | 2.43 | 45.6 | 4.4% | 0.9954 | 20.93 |
| node_15 | 13,604 | 1.54 | 16.4 | 5.2% | 0.9932 | 10.11 |
| real FIFA trace | 4,214 | 1.05 | 10.0 | 5.7% | 0.9956 | 11.31 |

Whole series (all 87 days): real trace CV 1.78, lag-1 ACF 0.9990, 1-minute change 3.8%; synthetic node_00 CV 1.78, lag-1 ACF 0.9935, 1-minute change 5.0%.
