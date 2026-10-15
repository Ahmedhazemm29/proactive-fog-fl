# Autoscaler simulation (Dogani & Khunjush 2024, Table 11)

Mean over 16 nodes, 25,022 test minutes each (one step = 1 minute).
Traffic per node scaled so that the mean demand is 15 pods at 100% use (factors 0.4157 to 2.4404).
Settings (Table 3): workload_pod 500, threshold 0.7, Pods_min 1 (KHPA 1), CDT scale-up 3 min, scale-down 5 min, SDR 0.3. No autoscaling: 15 pods.

Each cell: ours / Dogani. Counts are per node and test period for us. Dogani does not say what his counts cover.

| Scaler | θU (%) | θO (%) | TU (%) | TO (%) | εn | #Scale_Up | #Scale_Down |
|---|---|---|---|---|---|---|---|
| No autoscaling | 19.05 / 2.01 | 149.34 / 152.07 | 37.98 / 10.76 | 60.29 / 235.34 | 1.00 / 1.00 | 0 / – | 0 / – |
| KHPA | 2.47 / 6.23 | 2.43 / 3.05 | 24.11 / 32.05 | 20.20 / 18.23 | 6.84 / 1.30 | 1,962.6 / 1,841 | 1,958.4 / 1,892 |
| FedAvg-BiGRU | 0.57 / 0.26 | 11.18 / 13.04 | 8.93 / 1.65 | 57.20 / 75.12 | 6.69 / 1.59 | 905.6 / 1,008 | 881.2 / 1,049 |
| FedAvg-LSTM | 0.59 / 0.61 | 11.26 / 16.46 | 9.52 / 3.81 | 56.47 / 94.53 | 6.54 / 1.39 | 914.5 / 1,156 | 887.5 / 1,194 |
| CentralBiGRU | 0.57 / 0.23 | 11.25 / 12.50 | 7.92 / 1.42 | 58.31 / 72.20 | 6.82 / 1.63 | 708.0 / 976 | 847.8 / 1,009 |
| CentralLSTM | 0.70 / 0.53 | 11.48 / 16.12 | 10.69 / 3.37 | 54.77 / 87.43 | 6.10 / 1.42 | 844.8 / 1,144 | 856.9 / 1,171 |
| Oracle | 0.00 / – | 13.68 / – | 0.00 / – | 74.17 / – | ∞ / – | 735.6 / – | 829.0 / – |

- **Oracle:** εn is infinite on 16 of 16 nodes, because its θU and TU are 0 there and Eq. 18 divides by them.

## Elastic speedup check

Eq. 18 applied to the mean rows above. Dogani's printed εn does not follow from his own rows.

| | KHPA | FedAvg-BiGRU | FedAvg-LSTM | CentralBiGRU | CentralLSTM | Oracle |
|---|---|---|---|---|---|---|
| Ours, mean of the node values | 6.84 | 6.69 | 6.54 | 6.82 | 6.10 | ∞ |
| Ours, Eq. 18 on the mean rows | 6.87 | 6.68 | 6.53 | 6.85 | 6.11 | ∞ |
| Dogani, as printed | 1.30 | 1.59 | 1.39 | 1.63 | 1.42 | – |
| Dogani, Eq. 18 on his rows | 2.89 | 6.55 | 3.82 | 7.16 | 4.19 | – |

## Mean pods

| Scaler | Mean pods |
|---|---|
| No autoscaling | 15.00 |
| KHPA | 21.85 |
| FedAvg-BiGRU | 22.67 |
| FedAvg-LSTM | 22.63 |
| CentralBiGRU | 22.95 |
| CentralLSTM | 22.64 |
| Oracle | 23.57 |
