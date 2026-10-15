# Autoscaler simulation (Dogani & Khunjush 2024, Table 11)

Mean over 16 nodes, 25,022 test minutes each (one step = 1 minute).
Traffic per node scaled so that the mean demand is 15 pods (factors 0.4157 to 2.4404).
Settings (Table 3): workload_pod 500, Pods_min 5, CDT scale-up 3 min, scale-down 5 min, SDR 0.3. No autoscaling: 15 pods.

Each cell: ours / Dogani. Counts are per node and test period for us. Dogani does not say what his counts cover.

| Scaler | θU (%) | θO (%) | TU (%) | TO (%) | εn | #Scale_Up | #Scale_Down |
|---|---|---|---|---|---|---|---|
| No autoscaling | 12.65 / 2.01 | 222.09 / 152.07 | 28.40 / 10.76 | 69.70 / 235.34 | 1.00 / 1.00 | 0 / – | 0 / – |
| KHPA | 1.38 / 6.23 | 40.58 / 3.05 | 16.85 / 32.05 | 47.18 / 18.23 | 3.39 / 1.30 | 1,378.4 / 1,841 | 1,382.7 / 1,892 |
| FedAvg-BiGRU | 0.42 / 0.26 | 43.41 / 13.04 | 6.51 / 1.65 | 68.70 / 75.12 | 5.21 / 1.59 | 674.0 / 1,008 | 659.3 / 1,049 |
| FedAvg-LSTM | 0.45 / 0.61 | 43.32 / 16.46 | 7.00 / 3.81 | 67.79 / 94.53 | 5.05 / 1.39 | 679.1 / 1,156 | 663.9 / 1,194 |
| CentralBiGRU | 0.39 / 0.23 | 43.52 / 12.50 | 5.76 / 1.42 | 69.72 / 72.20 | 5.38 / 1.63 | 556.7 / 976 | 640.8 / 1,009 |
| CentralLSTM | 0.50 / 0.53 | 43.26 / 16.12 | 7.66 / 3.37 | 66.29 / 87.43 | 4.78 / 1.42 | 643.5 / 1,144 | 650.8 / 1,171 |
| Oracle | 0.00 / – | 44.74 / – | 0.00 / – | 80.78 / – | ∞ / – | 558.6 / – | 626.7 / – |

- **Oracle:** εn is infinite on 16 of 16 nodes, because its θU and TU are 0 there and Eq. 18 divides by them.

## Elastic speedup check

Eq. 18 applied to the mean rows above. Dogani's printed εn does not follow from his own rows.

| | KHPA | FedAvg-BiGRU | FedAvg-LSTM | CentralBiGRU | CentralLSTM | Oracle |
|---|---|---|---|---|---|---|
| Ours, mean of the node values | 3.39 | 5.21 | 5.05 | 5.38 | 4.78 | ∞ |
| Ours, Eq. 18 on the mean rows | 3.35 | 5.11 | 4.95 | 5.34 | 4.74 | ∞ |
| Dogani, as printed | 1.30 | 1.59 | 1.39 | 1.63 | 1.42 | – |
| Dogani, Eq. 18 on his rows | 2.89 | 6.55 | 3.82 | 7.16 | 4.19 | – |

## Mean pods

| Scaler | Mean pods |
|---|---|
| No autoscaling | 15.00 |
| KHPA | 16.20 |
| FedAvg-BiGRU | 16.71 |
| FedAvg-LSTM | 16.68 |
| CentralBiGRU | 16.89 |
| CentralLSTM | 16.68 |
| Oracle | 17.31 |
