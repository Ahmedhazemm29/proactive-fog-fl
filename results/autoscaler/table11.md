# Autoscaler simulation (Dogani & Khunjush 2024, Table 11)

Mean over 16 nodes, 25,022 test minutes each (one step = 1 minute).
Traffic per node scaled so that the mean demand is 15 pods at 100% use (factors 0.4157 to 2.4404).
Settings (Table 3): workload_pod 500, threshold 0.7, Pods_min 5 (KHPA 1), CDT scale-up 3 min, scale-down 5 min, SDR 0.3. No autoscaling: 15 pods.

Each cell: ours / Dogani. Counts are per node and test period for us. Dogani does not say what his counts cover.

| Scaler | θU (%) | θO (%) | TU (%) | TO (%) | εn | #Scale_Up | #Scale_Down |
|---|---|---|---|---|---|---|---|
| No autoscaling | 19.05 / 2.01 | 149.34 / 152.07 | 37.98 / 10.76 | 60.29 / 235.34 | 1.00 / 1.00 | 0 / – | 0 / – |
| KHPA | 2.47 / 6.23 | 2.43 / 3.05 | 24.11 / 32.05 | 20.20 / 18.23 | 6.84 / 1.30 | 1,962.6 / 1,841 | 1,958.4 / 1,892 |
| FedAvg-BiGRU | 0.51 / 0.26 | 26.83 / 13.04 | 8.72 / 1.65 | 65.23 / 75.12 | 5.48 / 1.59 | 878.6 / 1,008 | 855.4 / 1,049 |
| FedAvg-LSTM | 0.54 / 0.61 | 26.75 / 16.46 | 9.34 / 3.81 | 64.17 / 94.53 | 5.34 / 1.39 | 887.1 / 1,156 | 861.2 / 1,194 |
| CentralBiGRU | 0.47 / 0.23 | 27.03 / 12.50 | 7.57 / 1.42 | 66.87 / 72.20 | 5.69 / 1.63 | 682.6 / 976 | 823.6 / 1,009 |
| CentralLSTM | 0.62 / 0.53 | 26.69 / 16.12 | 10.42 / 3.37 | 62.28 / 87.43 | 5.02 / 1.42 | 820.2 / 1,144 | 833.5 / 1,171 |
| Oracle | 0.00 / – | 28.31 / – | 0.00 / – | 79.89 / – | ∞ / – | 711.0 / – | 804.1 / – |

- **Oracle:** εn is infinite on 16 of 16 nodes, because its θU and TU are 0 there and Eq. 18 divides by them.

## Elastic speedup check

Eq. 18 applied to the mean rows above. Dogani's printed εn does not follow from his own rows.

| | KHPA | FedAvg-BiGRU | FedAvg-LSTM | CentralBiGRU | CentralLSTM | Oracle |
|---|---|---|---|---|---|---|
| Ours, mean of the node values | 6.84 | 5.48 | 5.34 | 5.69 | 5.02 | ∞ |
| Ours, Eq. 18 on the mean rows | 6.87 | 5.37 | 5.23 | 5.64 | 4.96 | ∞ |
| Dogani, as printed | 1.30 | 1.59 | 1.39 | 1.63 | 1.42 | – |
| Dogani, Eq. 18 on his rows | 2.89 | 6.55 | 3.82 | 7.16 | 4.19 | – |

## Mean pods

| Scaler | Mean pods |
|---|---|
| No autoscaling | 15.00 |
| KHPA | 21.85 |
| FedAvg-BiGRU | 22.99 |
| FedAvg-LSTM | 22.94 |
| CentralBiGRU | 23.27 |
| CentralLSTM | 22.94 |
| Oracle | 23.86 |
