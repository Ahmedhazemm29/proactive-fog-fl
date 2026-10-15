# Decisions log: reproducing Dogani & Khunjush (2024)

This log lists every choice we made while reproducing the prediction part of
Dogani & Khunjush (2024), "Proactive auto-scaling technique for web
applications in container-based edge computing using federated learning
model", Journal of Parallel and Distributed Computing 187, 104837.
Page numbers refer to that article.

Each entry says what the paper says (or does not say), what we did, and why.
The code and results are in this repository:

- Step 1, real workload: `scripts/fifa_workload.py`
- Step 2, synthetic node traces: `scripts/synthetic_traces.py`
- Step 3, predictors: `predictors/`, `scripts/train_predictors.py`, results in `results/predictors/`

## Step 1: the real FIFA workload

### 1.1 Requests per minute

- **Dogani:** merges all requests of one minute into one record (Section 6.1, p. 9).
- **We:** count the requests per minute from the binary logs of the Internet Traffic Archive. Our total is 1,352,804,107 requests. That is exactly the number on the archive page and in the paper (p. 9).
- **Why:** the paper's unit. The matching total shows that no file is missing.

### 1.2 Time zone

- **Dogani:** does not say which time zone the minutes and the time features use.
- **We:** keep both UTC and Paris time (UTC + 2 hours, summer time). The features use Paris time.
- **Why:** the log files start and end at Paris midnight, and day of week, hour and holidays only make sense in local time.

### 1.3 Dropped day 5

- **Dogani:** uses the whole 88-day period from 30 April to 26 July 1998 (Section 6.1, p. 9).
- **We:** drop day 5. Our traces cover days 6 to 92, which is 1 May 00:00 to 26 July 23:59 Paris time. That is 87 full days, or 125,280 minutes.
- **Why:** day 5 holds only the last 30 minutes of 30 April (logging started at 23:30) and 325 requests. A half-hour fragment would add a gap-like start to every node.

### 1.4 Kept the 10 zero minutes

- **Dogani:** does not mention minutes without requests.
- **We:** keep 10 minutes with 0 requests (on 8, 17 and 18 May) as 0.
- **Why:** each one sits inside a short drop to almost 0. The minutes around them have only 1 to 79 requests. They look like real short outages or missing logs, so we keep the data as it is.

## Step 2: synthetic traces for 16 edge nodes

### 2.1 Method

- **Dogani:** makes one synthetic trace per edge node with the method of Koltuk & Schmidt (2020), reference [71]. Each trace keeps the CDF and the ACF of the real trace (Section 6.1, p. 10). The paper gives no settings for that method.
- **We:** use Koltuk's two steps. Step 1 draws independent values with the right distribution. Step 2 shuffles values and keeps a shuffle only if the ACF gets closer to the real one. Each node gets its own seed, 0 to 15.
- **Why:** this is the method the paper names.

### 2.2 Empirical draw instead of a fitted distribution

- **Dogani:** does not say which distribution was fitted. Koltuk fits several and keeps one that passes the Anderson-Darling (AD) test and has a similar variance to mean ratio.
- **We:** fitted genextreme, burr12, lognorm, gamma, weibull_min and fisk. No fit passed the AD test. On the full trace the lowest A² was 1045 (lognorm), and the critical value is 2.49. We then draw values from the real trace itself, with replacement (`--cdf empirical`).
- **Why:** Koltuk used hourly data with a few hundred points. With 125,280 points the AD test rejects every distribution. The fits that came closest also broke step 2. Fisk has infinite variance, and its draws reached 7.8 million requests in one minute against a real maximum of 154 thousand. The ACF matching then got stuck (error 0.089 with fisk, 0.076 with burr12). Lognorm converged, but slowly, and its maximum was 4 times the real one. Drawing real values keeps the distribution exact. Because we draw with replacement, every node gets a different mix of values.

### 2.3 Weighted ACF error

- **Dogani:** gives no error measure for the ACF matching. Koltuk uses the mean squared error over all lags.
- **We:** compare the ACF over lags 1 to 1440 (one day) and weight each lag by 1/lag. Lag 1 counts 10 times more than lag 10. Lags 1 to 10 together carry 37% of the weight.
- **Why:** the predictor looks 3 to 5 minutes ahead, so the short lags matter most. With equal weights, a test week reached a lag-1 ACF of only 0.963 against the real 0.998. With 1/lag weights it reached 0.994.

### 2.4 Three stop targets

- **Dogani:** gives no stop rule.
- **We:** a node is done when all three targets hold:
  1. the weighted ACF error is at most 0.00001;
  2. the ACF at every lag from 1 to 10 is within 0.01 of the real one;
  3. the ACF at lag 1440 is within 0.02 of the real one.

  A shuffle is kept if it lowers the weighted error plus how far targets 2 and 3 still are outside their limits. Each shuffle reorders the values at 2 random positions (S = 2).
- **Why:** target 2 protects the short lags. Target 3 protects the daily rhythm, which the 1/lag weights would otherwise ignore. Without the extra term, lag 1440 barely moved. S = 2 reached the lowest error in tests against S = 5 and S = 10.

### 2.5 Resume run

- **Dogani:** not applicable.
- **We:** the first run stopped every node at its cap of 200 million iterations, after 6.2 hours. No node had met all three targets. We added `--resume` and continued each node from its saved trace. All 16 nodes then met all three targets after 205 to 271 million iterations in total.
- **Why:** the error was still falling fast at the cap, so more iterations were enough. Before continuing, the resume step draws each node's starting values again from its seed. It checks that the saved trace holds exactly those values, so the distribution is unchanged.

### 2.6 The tournament trend is lost

- **Dogani:** says the method assumes a stationary trace and that the FIFA data is stationary (Section 6.1, p. 10).
- **We:** observe that the synthetic traces do not keep the trend of the tournament. The real trace is quiet in May and busy from mid-June. In a synthetic trace, busy days can appear anywhere in the 87 days.
- **Why:** the ACF is matched only up to lag 1440 (one day). Nothing ties a value to its position in the 87 days. This is a limit of the method, not a bug. See finding 4.1.

## Step 3: the predictors

### 3.1 Features and split

- **Dogani:** 5 features per minute: requests, day of week, hour, minute and holiday. Output: the next 5 minutes. Split 60% train, 20% validation, 20% test (Section 6.1, p. 9).
- **We:** the same. Holidays come from the `holidays` package for France: 1 May, 8 May, 21 May, 1 June and 14 July 1998. Each node is split in time order, and no window crosses a split border.
- **Why:** following the paper. The paper does not say which holidays it used or how windows meet the split borders. Keeping windows inside one part keeps test data out of training.

### 3.2 Window length W = 30

- **Dogani:** does not give the input window length.
- **We:** tried W = 30 and W = 60 with FedAvg-BiGRU on the validation set. W = 30 won (validation MAE 0.00321 against 0.00326) and is used for all models.
- **Why:** the paper leaves it open. The validation set is meant for such choices (p. 9).

### 3.3 64 units, not 32

- **Dogani:** Table 2 says 64 units in the hidden layers (p. 10). Section 7.1 says all models use one BiGRU layer with 32 hidden units (p. 11).
- **We:** use 64 units for both models.
- **Why:** Table 2 is the full parameter table for FedAvg-BiGRU. We note the conflict.

### 3.4 Min-max to [0, 1], not [-1, 1]

- **Dogani:** Eq. 8 scales each feature to the range 0 to 1 (Section 5.2, p. 8). Section 6.2 says the data was scaled to [-1, 1] (p. 10).
- **We:** scale to [0, 1], per node and per feature. The scaler is fitted on each node's training part only.
- **Why:** Eq. 8 is the formula the paper gives. Fitting on the training part only keeps the validation and test data unseen. The paper says each node is scaled on its own (p. 8) but not which part the scaler sees.

### 3.5 Ignored the encoder, decoder and attention rows

- **Dogani:** Table 2 lists hidden layers for an encoder and a decoder and an attention activation (p. 10). The model described in the text is a plain BiGRU with a linear output layer (Section 5.2, p. 7 to 8).
- **We:** build a plain BiGRU (one layer, merge mode sum) and a plain LSTM, each followed by dropout 0.3 and a linear layer to the 5 outputs.
- **Why:** a plain BiGRU has no encoder, decoder or attention. These rows seem to come from another model.

### 3.6 Training settings

- **Dogani:** Adam, loss MAE, batch size 60, dropout 0.3, 64 epochs (Table 2, p. 10). No learning rate.
- **We:** the same, with Adam's default learning rate of 0.001.
- **Why:** following Table 2. The default is the usual choice when none is given.

### 3.7 FedAvg settings

- **Dogani:** Algorithm 2 picks a random subset of edge nodes each round, trains E local epochs on each, and averages the weights by number of samples (Section 5.2, p. 8). The paper gives neither the subset size, nor E, nor the number of rounds.
- **We:** all 16 clients every round, E = 1, average by number of training windows. Each client starts a fresh Adam optimiser every round. Everything runs in one process, with a client and server structure that matches Flower.
- **Why:** these are the simplest settings that follow Algorithm 2. With all clients in every round, the result depends less on the random choice of clients.

### 3.8 Early stopping, patience 10

- **Dogani:** gives 64 epochs (Table 2, p. 10) and no stop rule.
- **We:** stop when the validation loss has not improved for 10 rounds or epochs. The caps are 100 FedAvg rounds and 64 central epochs. The best weights are kept.
- **Why:** with patience 5 every model stopped after 14 to 16 rounds or epochs, and the validation loss was noisy. With patience 10 only FedAvg-LSTM found a better point (round 29 instead of 9). The other three models gave identical results. Both runs are kept in `results/predictors_patience5/` and `results/predictors/`.

### 3.9 MAPE skips zero minutes

- **Dogani:** Eq. 13 divides by the real value (Section 6.3, p. 10). It does not say what happens when the real value is 0.
- **We:** skip minutes with 0 real requests in MAPE and report how many (51 per model and step, over all 16 nodes). MAE and RMSE use all minutes.
- **Why:** MAPE is undefined for 0. In our first run the real values came back from scaling slightly above 0, and MAPE reached millions of percent. We now round real values to whole requests, so zeros are skipped.

### 3.10 Diebold-Mariano test

- **Dogani:** uses the DM test with reference [72] (Section 6.3, p. 10). It does not say which loss or which correction.
- **We:** compare absolute errors, account for the overlap of multi-step forecasts, and use the Harvey, Leybourne and Newbold small-sample correction. We test FedAvg-BiGRU against each other model at t+3, t+4 and t+5, on all nodes' test windows together.
- **Why:** absolute errors match the MAE loss. The correction is the standard version of the test.

## Findings that differ from Dogani

### 4.1 The FIFA trace is not stationary

- **Dogani:** "the FIFA datasets being analyzed are stationary" (Section 6.1, p. 10).
- **We found:** the mean load changes strongly over the tournament. The weekly mean is 882 requests per minute in the first week of May, rises to 28,842 in the week from 26 June, and falls back to 982 in the last days of July. That is a factor of 33. We did not run a formal stationarity test.
- **Consequence:** the synthetic traces keep the daily ACF but lose this trend (entry 2.6).

### 4.2 BiGRU beats LSTM only at t+5

- **Dogani:** FedAvg-BiGRU is clearly better than FedAvg-LSTM at t+3, t+4 and t+5. The DM p-values are 2.85e-12, 2.43e-07 and 4.45e-06 (Table 9, p. 15).
- **We found:** with patience 10, FedAvg-BiGRU and FedAvg-LSTM do not differ significantly at t+3 (p 0.158) or t+4 (p 0.137). FedAvg-BiGRU is better only at t+5 (p 1.3e-10). With patience 5, BiGRU was better at all three steps, because FedAvg-LSTM had stopped too early.

### 4.3 Federated against central

- **Dogani:** FedAvg-BiGRU and CentralBiGRU do not differ significantly. The p-values are 0.062, 0.195 and 0.185 (Table 9, p. 15).
- **We found:** the MAE of the two is within 3.5% at every step. But the DM test finds a significant difference at every step. FedAvg-BiGRU is better at t+3 and t+4 and worse at t+5. With about 400,000 test windows, even small differences reach significance.

### 4.4 FL sends more bytes than the raw data

- **Dogani:** claims a remarkable reduction in data transmission (p. 14) but does not measure it.
- **We found:** one FedAvg round sends 3,531,392 bytes for the BiGRU and 2,368,128 bytes for the LSTM: the model down and up for all 16 clients. Sending all nodes' training and validation data to the cloud once costs 32,071,680 bytes. FedAvg passes that amount after 9.1 rounds for the BiGRU and 13.5 rounds for the LSTM. Our runs used 19 and 39 rounds (best rounds 9 and 29), which is 67.1 MB and 92.4 MB in total. FL saves bytes here only if training stops within about 9 to 13 rounds. Its clear advantage is privacy, not volume.

### 4.5 MAE and RMSE cannot be compared

- **Dogani:** reports an MAE of 166.8 and an RMSE of 316.9 for FedAvg-BiGRU at t+3 (Table 8, p. 13).
- **We found:** an MAE of 506.4 and an RMSE of 2064.9. Our traces average about 10,800 requests per minute, and the busiest minute has about 229,000. An MAE of 167 would be very small for traffic of this size. The paper does not say how its synthetic traces are scaled, so the traffic level behind its numbers is unknown. Only MAPE can be compared. Our MAPE is 12.8 to 14.4% for FedAvg-BiGRU, against Dogani's 9.0 to 11.2%.
- **Note:** Table 8 gives FedAvg-BiGRU's MAE at t+5 as 221.9, but Table 4 gives 261.9 for the same model and data (p. 11 and 13).
