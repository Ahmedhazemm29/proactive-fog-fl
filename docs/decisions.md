# Decisions log: reproducing Dogani & Khunjush (2024)

This log lists every choice we made while reproducing the prediction and autoscaling parts of
Dogani & Khunjush (2024), "Proactive auto-scaling technique for web
applications in container-based edge computing using federated learning
model", Journal of Parallel and Distributed Computing 187, 104837.
Page numbers refer to that article.

Each entry says what the paper says (or does not say), what we did, and why.
The code and results are in this repository:

- Step 1, real workload: `scripts/fifa_workload.py`
- Step 2, synthetic node traces: `scripts/synthetic_traces.py`
- Step 3, predictors: `predictors/`, `scripts/train_predictors.py`, results in `results/predictors/`
- Step 4A, autoscaler simulation: `autoscaler/`, `scripts/simulate_autoscaler.py`, results in `results/autoscaler/`
- Step 4A sensitivity: `scripts/autoscaler_sensitivity.py`, results in `results/autoscaler_sensitivity/`
- Step 4A fair runs (same Pods_min for KHPA and the planner): results in `results/autoscaler_fair/`

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

## Step 4A: autoscaler simulation

### 4A.1 A simulation, not Kubernetes

- **Dogani:** runs the autoscalers on a Kubernetes cluster with CPU-heavy test tasks (Section 7.5, p. 17).
- **We:** simulate the scalers in Python, one step per minute, on each node's test period. That is 25,022 minutes per node, from 9 July 1998 14:54 to 26 July 23:55. At the start of minute t a scaler may change the pod count. It knows the real traffic up to minute t-1. The planner also gets the forecast for minutes t to t+4. New pods are ready at once and serve minute t. Every scaler starts with 15 pods.
- **Why:** this isolates the planner and the predictors from cluster effects. A Kubernetes run is a later step.

### 4A.2 Traffic scale

- **Dogani:** uses 15 pods without autoscaling, "equal to the number of pods required to process the typical payload" (p. 17). The paper does not say how large its synthetic traffic is (finding 4.5).
- **We:** multiply each node's real traffic and its predictions by one factor. The factor makes the node's mean demand over the test period 15 pods (`--mean-pods`). The factors range from 0.42 to 2.44.
- **Why:** our traffic is much larger than Dogani's. Without scaling, a node would need 6 to 36 pods on average over its test period. Scaling per node gives every node the same mean demand as Dogani's setting.

### 4A.3 Requested pods and Δt

- **Dogani:** requested pods are the CPU usage divided by a threshold of 70% (p. 17). Eqs. 14 to 17 weight each step by Δt, the time between changes (p. 10).
- **We:** requested pods at minute t = ceil(traffic / 500), at least 1. One step is Δt = 1 minute.
- **Why:** we have traffic, not CPU usage. 500 requests per pod is workload_pod from Table 3. Summing every minute with Δt = 1 gives the same result as weighting each interval between changes by its length.
- **Later:** we added Dogani's 70% threshold as an option. See entry 4A.9.

### 4A.4 Line 6 of Algorithm 3

- **Dogani:** line 5 computes W_max_ScaleUp, the maximum of the next 3 predictions. Line 6 then divides W_max_ScaleDown by workload_pod (Algorithm 3, p. 9).
- **We:** use W_max_ScaleUp in line 6.
- **Why:** W_max_ScaleDown is only computed later, in the scale-down branch (line 10). Line 5 would be useless otherwise. The text says the scale-up uses three steps of prediction (p. 17). So line 6 is a typo.

### 4A.5 Planner details

- **Dogani:** line 3 picks the direction from the next prediction. A scale-down removes only part of the extra pods: Pods_next = Pods_current - floor((Pods_current - Pods_estimate) * (1 - SDR)), at least Pods_min (lines 11 to 13). Every branch sends a command and then waits for the cooldown (Algorithm 3, p. 9).
- **We:** follow these lines with the Table 3 values: workload_pod 500, Pods_min 5, cooldowns 3 and 5 minutes, SDR 0.3. Two cases are not covered by the pseudocode:
  1. If the maximum of the next 5 predictions needs more pods than now, the scale-down formula would add pods. We keep the current pods instead.
  2. A decision that leaves the pod count unchanged is not a scaling action. It starts no cooldown and is not counted.
- **Why:** case 1 follows the text. Dogani says the planner did not scale down "since it predicted an increase in resource consumption over the next three steps" (p. 17). In case 2, nothing changed, so there is nothing to wait for. Because of the floor, a drop of 1 pod never leads to a scale-down.

### 4A.6 KHPA

- **Dogani:** KHPA computes the pods from the measured CPU usage and a target (Algorithm 1, Section 3.2, p. 5). It waits 3 minutes after a scale-up and 5 after a scale-down.
- **We:** at minute t, KHPA asks for ceil(traffic of minute t-1 / 350) pods, with the 70% threshold of entry 4A.9. Its own minimum is 1 pod in the main run and 1 or 5 in the fair runs (entry 4A.10). It has the same cooldowns. There is no tolerance band.
- **Why:** this is Algorithm 1 with traffic in place of CPU usage. Real Kubernetes ignores changes below 10%. Algorithm 1 has no such band, so we leave it out.

### 4A.7 Oracle predictor

- **Dogani:** compares against an "optimal mode" only in Fig. 9 (p. 17 and 18), not in Table 11.
- **We:** add a 5th predictor, Oracle, that gives the planner the real future traffic.
- **Why:** it shows what the planner does with perfect forecasts. Any gap between a model and the Oracle comes from forecast errors. Any gap between the Oracle and the requested pods comes from the planner itself.

### 4A.8 Averages and counts

- **Dogani:** does not say how the 16 nodes are combined in Table 11, or what the scaling counts cover.
- **We:** compute all metrics per node and report the mean over the 16 nodes. The counts are per node over its test period. εn is computed per node against that node's no-autoscaling run, then averaged. When εn divides by 0, we report it as infinite and name the metric that is 0.
- **Why:** each node runs its own autoscaler. The per-node values are in `results/autoscaler/metrics_per_node.csv`.

### 4A.9 The 70% threshold

- **Dogani:** gets the optimal pods by dividing the CPU usage by a threshold. The threshold is 70% (Section 7.5, p. 17).
- **We:** use threshold 0.7 by default (`--threshold`). Requested pods = ceil(traffic / (500 x 0.7)), so a pod gets 350 requests per minute. KHPA and the planner use the same 350. The traffic scale does not change with the threshold: mean pods 15 still means 15 x 500 requests per minute. So with 0.7 the same traffic needs about 1/0.7 times more pods. No autoscaling stays at 15 pods.
- **Why:** Dogani states it. Our first run used 1.0 and was far from Table 11 (finding 4.9). That first run can be reproduced exactly with `--threshold 1.0 --khpa-pods-min 5`.

### 4A.10 Main run and fair runs

- **Dogani:** Table 3 lists Pods_min = 5 as a planner parameter (p. 10). The paper does not say whether KHPA has a minimum.
- **We:** the main "Dogani-like" run in `results/autoscaler/` uses mean pods 15, threshold 0.7, KHPA Pods_min 1 and planner Pods_min 5. Two fair runs in `results/autoscaler_fair/` use the same settings, but give KHPA and the planner the same Pods_min: both 1 (`pods_min_1/`) and both 5 (`pods_min_5/`).
- **Why:** the main run is the combination closest to Dogani's Table 11 (finding 4.9). But it lets KHPA drop to 1 pod while the planner keeps 5, which favours KHPA at low load. The fair runs compare the two scalers under the same rule.

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

### 4.6 Table 11 does not follow its own formula

- **Dogani:** prints εn = 1.30 for KHPA and 1.59 for FedAvg-BiGRU (Table 11, p. 17). It also gives TO = 235.34 for no autoscaling.
- **We found:** Eq. 18 applied to Dogani's own Table 11 rows gives εn = 2.89 for KHPA and 6.55 for FedAvg-BiGRU. The order of the models stays the same, but every value is 2.2 to 4.4 times larger than printed. TO is a share of time, so it cannot be above 100 (Eq. 17, p. 11). We cannot tell how the printed εn values were computed.

### 4.7 Most over-provisioning comes from Pods_min

- **Dogani:** KHPA over-provisions much less than the planner: θO 3.05 against 13.04 for FedAvg-BiGRU (Table 11, p. 17).
- **We found:** over-provisioning depends mostly on Pods_min.
  1. In our first run (threshold 1.0, Pods_min 5 for both), θO was about the same for all scalers: 40.6 for KHPA and 43.3 to 43.5 for the four predictors. A third of all minutes needed fewer than 5 pods, and Pods_min = 5 alone gave θO = 39.3.
  2. In the main run, KHPA may drop to 1 pod. Its θO falls to 2.43, close to Dogani's 3.05. The planner keeps 5 pods and has θO 26.83 with FedAvg-BiGRU.
  3. In the fair run with Pods_min 1 for both, the planner's θO falls to 11.18 to 11.48, close to Dogani's 12.50 to 16.46.
- **Also:** the Oracle over-provisions the most of all planners, even with perfect forecasts (θO 13.68 and TO 74.2 in the fair run with Pods_min 1). Taking the maximum of the next 3 or 5 minutes and removing only 70% of the extra pods keep more pods than needed. That is the planner's design, not a forecast error.

### 4.8 The planner beats KHPA on under-provisioning

- **Dogani:** the planner has the lowest θU and TU, needs fewer scaling actions than KHPA, and has a higher εn (Table 11, p. 17).
- **We found:** the planner has less under-provisioning and fewer scaling actions in every run. Whether it has a higher εn depends on Pods_min. With FedAvg-BiGRU:

  | Run | θU planner / KHPA | TU planner / KHPA | Scale-ups planner / KHPA | εn planner / KHPA |
  |---|---|---|---|---|
  | Main (KHPA 1, planner 5) | 0.51 / 2.47 | 8.72 / 24.11 | 879 / 1,963 | 5.48 / 6.84 |
  | Fair, both 1 | 0.57 / 2.47 | 8.93 / 24.11 | 906 / 1,963 | 6.69 / 6.84 |
  | Fair, both 5 | 0.51 / 1.60 | 8.72 / 21.26 | 879 / 1,710 | 5.48 / 3.83 |

  With both at 5 the planner wins clearly, as in Dogani. With both at 1, εn is almost a tie. The planner then trades fewer missing pods for more extra pods. KHPA has θO 2.43 against the planner's 11.18.
- **Order of the predictors:** CentralBiGRU is best, then FedAvg-BiGRU (εn 5.69 and 5.48 in the main run). This is the same order as Dogani's top two. With the Oracle, θU and TU are 0, so its εn is infinite.
- **No autoscaling:** 15 fixed pods are too few in 38% of the minutes (θU 19.05 against Dogani's 2.01), because our demand has high peaks.

### 4.9 Which assumptions explain the gap to Table 11

- **Question:** our Table 11 is far from Dogani's. Which of our assumptions causes it?
- **We tested:** 12 combinations of mean traffic (15, 25 and 40 pods at 100% use), threshold (1.0 and 0.7) and KHPA's Pods_min (5 and 1). The planner keeps Pods_min 5, and no autoscaling keeps 15 pods. We measured the distance to Dogani as the sum of absolute differences on θU, θO, TU and TO, for no autoscaling, KHPA and FedAvg-BiGRU. His TO of 235.34 for no autoscaling is left out.
- **We found:**
  1. The closest combination is mean 15, threshold 0.7 and KHPA Pods_min 1, with a distance of 92.3. Our first run (mean 15, threshold 1.0, Pods_min 5) had a distance of 226.6. The main run now uses the closest combination (entry 4A.10).
  2. KHPA's Pods_min matters most for KHPA. With Pods_min 1, KHPA's θO drops from 40.6 to 2.2, close to Dogani's 3.05. So Dogani's KHPA probably did not keep 5 pods at low load.
  3. With threshold 0.7 and mean 15, no autoscaling gets θO 149.3, close to Dogani's 152.07.
  4. No combination brings the under-provisioning of no autoscaling close to Dogani. Our θU stays at 12.65 or more against his 2.01, and our TU at 28.4 or more against his 10.76. Our traffic has higher peaks relative to its mean, so 15 fixed pods are too few more often.
  5. FedAvg-BiGRU stays at θO 9 to 44 and TU 6.5 to 16.4, against Dogani's 13.04 and 1.65. No setting matches both.
  6. In the closest combination KHPA has a higher εn than FedAvg-BiGRU (6.84 against 5.48), because KHPA may drop to 1 pod and the planner may not. The fair runs give both the same Pods_min (entry 4A.10, finding 4.8).
- **Results:** `results/autoscaler_sensitivity/sensitivity.md`.
