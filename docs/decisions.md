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
- Step 4B, live demo with real containers: `autoscaler/cluster.py`, `autoscaler/loadgen.py`, `autoscaler/live.py`, `scripts/live_*.py`, results in `results/autoscaler_live/`, guide in `docs/demo_live.md`
- Step 4B on three more windows: `scripts/live_windows.py`, `scripts/live_windows_report.py`, results in `results/autoscaler_live/calm/`, `rise/` and `spiky/`, summary in `results/autoscaler_live/windows_report.md`

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

### 3.11 Checks on the gap to Dogani's MAPE

- **Question:** our MAPE at t+3 is 13.96 for FedAvg-BiGRU and 13.23 for CentralBiGRU, against Dogani's 9.04 and 8.49. FedAvg-BiGRU was also better at t+5 (12.82) than at t+3. Is something wrong?
- **Horizon alignment:** correct. A test feeds a trace where minute i has i requests through `predict()` and the Table 8 evaluation. A model that predicts "last input + h" has an error of exactly 0 at t+3, t+4 and t+5. Shifted by one minute, it is off by exactly 1 request. The pooled windows of the central models carry the same targets (`tests/test_predictors.py`). The MAE of every model also grows steadily from t+1 to t+5.
- **MAPE:** Eq. 13, the mean of |predicted - real| / real, in %. We compute it on real requests: the predictions are unscaled, the real values are rounded to whole requests, and only minutes with exactly 0 requests are skipped (51 per model and step). Nothing else is filtered. Dogani gives the same formula but does not say in which units he applied it (finding 4.20).
- **Settings next to Dogani's:**

  | Setting | Dogani | Ours |
  |---|---|---|
  | Hidden units | 64 in Table 2, 32 in Section 7.1 | 64 (3.3) |
  | Recurrent layers | 1 | 1 |
  | BiGRU merge mode | not stated | sum |
  | Input window W | not stated | 30 minutes (3.2) |
  | Features, outputs | 5 features, next 5 minutes | the same |
  | Split | 60 / 20 / 20 | the same, in time order per node |
  | Normalization | [0, 1] in Eq. 8, [-1, 1] in Section 6.2 | [0, 1] per node, fitted on the training part (3.4) |
  | Loss | MAE | MAE |
  | Optimizer | Adam | Adam |
  | Learning rate | not stated | 0.001 |
  | Batch size | 60 | 60 |
  | Dropout | 0.3 | 0.3 |
  | Epochs | 64 | at most 64 central epochs or 100 FedAvg rounds |
  | Early stopping, patience | not stated | patience 10 on the validation MAE (3.8) |
  | FedAvg rounds | not stated | 19 (best round 9) |
  | Local epochs per round | not stated | 1 |
  | Clients per round | a random subset, size not stated | all 16 |
  | Seeds, repeats | not stated | one seed per model |

- **Experiments:** `scripts/predictor_experiments.py` trains one model with one changed setting and keeps the step 3 results. We ran FedAvg-BiGRU with seeds 1 and 2 and with 32 units: 33 minutes on the RTX 4060. The results are in finding 4.22.
- **Results:** `scripts/predictor_gap.py` writes `results/predictor_gap/report.md`. The experiments are in `results/predictor_gap/experiments.csv`.

### 3.12 Which MAPE did Dogani compute?

- **Question:** finding 4.20 showed that the same forecasts score from 4 to 14 depending on what MAPE is computed on. Dogani gives Eq. 13 but not the values he applied it to. Which reading makes his own numbers fit together?
- **Readings:** `predictors/mape.py` computes MAPE in ten ways on the same saved forecasts:
  1. on real requests, skipping only zeros (ours);
  2. the same, skipping minutes below 1%, 5% or 10% of the node's mean;
  3. per node first, then the mean over nodes;
  4. on one total trace of all 16 nodes;
  5. on values scaled to [0, 1] or [-1, 1], with each node's own scaling or one scaling for all nodes.

  `tests/test_mape.py` checks every reading on hand-made minutes with a known answer.
- **Consistency check:** if Dogani's errors have the same shape as ours, MAE divided by the mean traffic is the same multiple of MAPE for him and for us. Each reading then gives the mean traffic that makes his MAE of 166.8 and MAPE of 9.04 fit together. We compare it with four candidates: the FIFA trace given to every node in full or split over 16 nodes, each over all 88 days or only over its test part, the last 20%. MAE is measured on the test part, so the test-part means matter most.
- **[-1, 1] training:** `--scale=-1,1` in `scripts/train_predictors.py` and `scripts/predictor_experiments.py` scales inputs and targets to [-1, 1], as in Section 6.2. The default stays [0, 1], so step 3 is unchanged. We retrained FedAvg-BiGRU and CentralBiGRU with it, seed 0: 24 minutes on the RTX 4060.
- **Results:** `scripts/mape_readings.py` writes `results/predictor_gap/mape_readings.md`. It uses the saved weights of step 3 and of the experiments and keeps their forecasts in `data/predictor_gap/forecasts/`. Findings 4.23 to 4.26.

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

## Step 4B: live demo with real containers

### 4B.1 Docker on one laptop, not Kubernetes

- **Dogani:** runs the scalers on a real container cluster with HAProxy in front (Section 7.5).
- **We:** run real worker containers with Docker on one laptop. HAProxy sits in front. Our own Python loop plays Kubernetes: it starts and stops containers. We compare 3 scalers: no autoscaling, KHPA and the planner with FedAvg-BiGRU. Each one replays the same 3-hour window, one after another.
- **Why:** this tests the step 4A logic against real CPU, real start-up times and real response times. A Kubernetes cluster would add a lot of setup and no new question.

### 4B.2 Worker and tasks

- **Dogani:** each request runs one of three tasks: sorting an array, the eigenvalues of a matrix, or compressing a file (Section 7.5).
- **We:** each request picks one of three tasks with equal chance:
  - sort 3000 random numbers;
  - find the eigenvalues of a 100 x 100 random matrix;
  - compress a 64 KB text file with zlib.

  The worker is a small Python HTTP server with numpy, limited to 0.5 CPU and 256 MB. It uses one BLAS thread. Nagle's algorithm is off.
- **Why:** with Nagle on, the server sends the headers and the body separately, and most requests waited about 40 ms for nothing. With it off, p95 dropped from 45 ms to about 5 ms.

### 4B.3 Calibration: workload_pod

- **Dogani:** uses 500 requests per minute per pod (Table 3, p. 10) and a 70% CPU threshold (p. 17).
- **We:** measure how many requests one worker handles at 70% CPU. That number is 1,650 per step (165 per second, 9,902 per real minute) in `results/autoscaler_live/calibration.json`. We use it in place of 500 x 0.7. Requested workers from the traffic are ceil(requests / 1,650), and the planner uses the same number.
- **How:** 18 workers get the same rate each. We read their CPU from the cgroup files. The 70% rate is read off the measured curve, between the two rates around it.
- **Why 18 workers:** a request costs more CPU when the laptop is busier. This i7-13620H has 6 fast cores with 2 threads each and 4 slow cores. At 1,650 requests per step, one worker alone used 55% of its limit, 8 workers used 59% each and 18 workers used 72% each. We calibrated at 18 because the busiest minute is scaled to need 18 workers. Calibrated with 8 workers, the busiest minute would need about 22 workers by CPU, over the cap of 20.
- **Pinning:** we also tried pinning the workers to the fast cores. The cost per request then grew 30% from 1 to 18 workers, against 12% without pinning. So we let Linux place them.

### 4B.4 Window and scale

- **Dogani:** Fig. 9 shows parts of the test period (p. 18).
- **We:** use node 0's test traffic from 23 July 1998, 07:30 to 10:29, which is 180 minutes. It is centred on the busiest half hour of node 0's test period. The demand rises from about 4 workers to 18 and falls back to about 5. The traffic and the forecasts are multiplied by 0.1554, so that the busiest minute needs 18 workers. The mean demand is 8.11 workers. 3 warm-up minutes before the window are replayed but not measured.
- **Why:** the task asks for a busy window with rises and drops, and at most about 18 workers at the peak.

### 4B.5 Time compression

- **Dogani:** one step is 1 minute. The cooldowns are 3 minutes up and 5 minutes down (Table 3, p. 10).
- **We:** one step (one trace minute) takes 10 s of real time. The cooldowns stay 3 and 5 steps, which is 30 s and 50 s.
- **Run time:** 180 steps x 10 s is 30 minutes. With warm-up and setup, each run takes about 31 minutes, not the 18 minutes the task estimated. We kept 10 s per minute, because the task states it twice.

### 4B.6 Load generator

- **Dogani:** does not describe the load generator.
- **We:** use an open loop, so each request has a planned send time and goes out then, however slow the earlier ones are.
  - Step k sends its requests evenly spread over its 10 s. Every scaler sees the same requests.
  - A request fails when it gets no 200 answer within 2 s of its planned time.
  - The response time is measured from the planned time. Waiting for a free connection counts.
  - p95 is taken over the requests that succeeded. Failures are counted separately.
  - The generator is plain asyncio with 6,000 keep-alive connections.
- **Why so many connections:** an overloaded request holds its connection for up to about 1 s, and the peak is about 3,000 requests per second. Our first full run used 256 connections. Under overload the generator then became the bottleneck. It sent only a few hundred requests per second, the rest expired in its own queue, and the workers sat at 0.13 CPU while every request failed. That turned the test into a closed loop, so we threw the run away. With 6,000 connections, 8 workers at 2,700 requests per second run at 0.49 CPU and serve about 1,930 per second. The rest fail with a 503.
- **Check:** the run JSON gives how late the generator queued requests. In every full run 99% were queued within 1.1 ms of their planned time (finding 4.13).

### 4B.7 Load balancer and starting workers

- **Dogani:** uses HAProxy.
- **We:** use HAProxy 2.8 with round-robin. It lists all 20 possible workers from the start, in maintenance mode.
  - **Scale-up:** the runner starts a pre-created container, waits for /health, then enables the worker through HAProxy's runtime API. Starting takes about 0.4 s.
  - **Scale-down:** the runner first puts the worker in maintenance, waits 0.2 s and then stops the container.
  - **Limits:** each worker takes at most 16 requests at once. The rest wait in HAProxy's queue for up to 1 s, then get a 503. HAProxy drops a queued request when its client gives up (`option abortonclose`).
  - **Safety:** at most 20 workers. Every container has the label thesis.live=1. The runner removes them at the end, also after an error or Ctrl+C.
- **Why:** pre-created containers make a scale-up as fast as a Kubernetes pod with a cached image. The runtime API changes the workers without restarting HAProxy.
- **Why the 1 s queue and abortonclose:** with a 2 s queue and no abortonclose, an overload went bad. HAProxy kept the requests whose clients had given up and still sent them to the workers. The workers then spent their CPU on answers nobody waited for, and no request succeeded at all. With both settings, an overloaded worker serves its full capacity and the excess is rejected quickly. The calibration was done before this change. A check afterwards gave the same CPU use: 70.1% with 18 workers and 61.1% with 8 at 1,650 requests per step.

### 4B.8 The three scalers

- **No autoscaling:** 8 workers, the rounded mean demand of the window (8.11).
- **KHPA:**
  - Every step it asks Prometheus for the CPU of all workers: `sum(rate(container_cpu_usage_seconds_total[15s]))` from cAdvisor.
  - It wants ceil(CPU / 0.35) workers, at least 1. That is Kubernetes' rule with CPU request = limit = 0.5 and a 70% target.
  - Cooldowns are 3 and 5 steps, as in 4A.6. There is no 10% tolerance band.
  - The 15 s window is used because Prometheus scrapes every 5 s, and rate() needs 2 samples. If Prometheus does not answer, KHPA uses the cgroup CPU. No full run needed that fallback.
- **Planner:** Algorithm 3 exactly as in step 4A (`planner_step`), with line 6 read as in 4A.4. It runs on the scaled FedAvg-BiGRU forecasts with 1,650 requests per worker, at least 5.
- **All three** start at 8 workers.
- **Why:** these are the step 4A rules, with real CPU in place of traffic for KHPA, as the task asks.

### 4B.9 Requested workers: from CPU and from traffic

- **Dogani:** gets the optimal pods from the CPU usage and the 70% threshold (p. 17).
- **We:** report Table 11 twice.
  - **From real CPU:** requested = ceil(CPU of all workers in the step / 0.35), at least 1. This is what the task asks for.
  - **From the traffic:** requested = ceil(requests / 1,650). It is the same in every run, as in step 4A.
- **Why both:** the CPU measure has two weak spots.
  - A saturated worker cannot use more than 0.5 CPU, so the CPU hides the demand that did not fit. This is the "hidden demand" finding of the first part of this thesis.
  - A request costs less CPU when fewer workers run (entry 4B.3). So the CPU measure asks for fewer workers at low load.

  The traffic measure has neither problem. It matches the step 4A simulation, which we also run on the same window.

### 4B.10 Measuring CPU

- **We:** the runner reads each worker's cgroup file (cpu.stat) at every step boundary. That gives the exact CPU time of each step. Prometheus is only used for KHPA's decision and for Grafana.
- **Why:** Prometheus' rate() window and its 5 s scrapes make its value trail the real CPU by about half a step. The step CSVs keep both values: `cpu_total` from the cgroup and `prom_cpu` from Prometheus.

### 4B.11 The cap of 20 workers

- **Dogani:** the planner has a minimum, Pods_min = 5 (Table 3, p. 10). Step 4A used no maximum.
- **We:** run at most 20 workers. The limit was set in the step 4B task, as a safety limit for the laptop. The code keeps it in one constant, `MAX_WORKERS = 20` in `autoscaler/cluster.py`. Everything uses that constant:
  - the scalers can never ask for more than 20 (`pods_max` in `scripts/live_run.py`);
  - `scale_to()` never starts more than 20;
  - exactly 20 containers are created, at the fixed addresses 172.30.0.11 to 172.30.0.30;
  - HAProxy lists exactly these 20 workers.
- **Why 20:**
  - 20 workers x 0.5 CPU is at most 10 of the laptop's 16 threads. That leaves room for HAProxy, the load generator, Prometheus and cAdvisor.
  - The busiest minute is scaled to need 18 workers (entry 4B.4), so 2 workers are spare.
- **Effect:** the cap never mattered in the full runs. KHPA and the planner peaked at 17 workers. The workers requested from CPU reached 19 in one step, still below 20.

### 4B.12 Three more windows, chosen by a rule

- **Dogani:** reports Table 11 over 16 nodes and 17 days (p. 17), not over one window.
- **We:** repeat the live runs on three more windows, so the result does not rest on one window. A fixed rule picks them from all 16 nodes (`scripts/live_windows.py`):
  - **Candidates:** every 180-minute window that lies, with its 3 warm-up minutes, in the test minutes with forecasts. These are the minutes step 4A simulates.
  - **Guard:** the window mean is at least the median of the node's test minutes.
  - **Calm:** the lowest peak/mean.
  - **Rise:** the biggest rise from one minute to the next, divided by the window mean. The window is centred on it, so the rise goes from window minute 89 to 90.
  - **Spiky:** the same with the biggest jump up or down.

  | Window | Node | Time (1998) | Trace rows | Mean (requests/min) | Peak/mean | Biggest 1-minute jump |
  |---|---|---|---|---|---|---|
  | Calm | 1 | 20 July, 08:38 to 11:37 | 115,718 to 115,897 | 16,460 | 1.04 | +869 (5% of the mean) |
  | Rise | 7 | 12 July, 00:01 to 03:00 | 103,681 to 103,860 | 64,959 | 3.15 | +71,627 (110%) |
  | Spiky | 2 | 20 July 22:45 to 21 July 01:44 | 116,565 to 116,744 | 56,369 | 4.01 | -64,410 (114%) |

- **Why the guard:** without it, the spiky rule picks node 4 at night, from 17 July 03:45. That window has a mean of 169 requests per minute, against a node median of 1,734. A jump of 259% of such a mean is noise, not an event. Node 7's median is 2,092, so the rise window passes the guard easily.
- **Why centred:** the first window is centred on its busiest half hour. Without centring, the best jump of the guarded windows falls into the last minute of its window (node 7, from 11 July 22:32), where no scaler can react to it.
- **Rise and spiky differ:** the biggest jump overall is a drop, so a separate rule picks the biggest rise. In both windows the centred jump is also the biggest jump of the window.
- **Scale:** as in 4B.4, the busiest minute of each window needs 18 workers.

  | Window | Factor | Mean demand (workers) | No autoscaling |
  |---|---|---|---|
  | Calm | 1.7301 | 17.26 | 17 workers |
  | Rise | 0.1452 | 5.72 | 6 workers |
  | Spiky | 0.1315 | 4.49 | 4 workers |

- **Same setup:** everything else is as in 4B.1 to 4B.11: 1,650 requests per worker and step, 10 s per step, the cooldowns, the cap of 20 and the run order no autoscaling, KHPA, planner. All three scalers start at the window's fixed count.
- **Planner below its minimum:** in the spiky window the start is 4 workers, one below the planner's minimum of 5. The planner keeps these 4 workers for the first 62 steps, until its forecasts ask for more. Algorithm 3 applies Pods_min only when it scales down (`planner_step` in `autoscaler/scalers.py`), and the step 4A simulation does the same. A start at 5 would give the planner θO 60.82 instead of 48.28 and εn 4.23 instead of 4.53, estimated with the CPU measured in its run. No answer in `windows_report.md` changes.
- **Limits of these windows:** calm keeps about 17 of the 20 workers busy for the whole run, so the scalers have little room. Spiky needs 18 workers for a single minute only.

### 4B.13 Options and folders for other windows

- **We added:**
  - `live_prepare.py --node N --start "YYYY-MM-DD HH:MM" --out-dir DIR`: the window of node N that starts at that minute. Without `--start`, the window is still centred on node 0's busiest half hour. The default run gives byte-identical `window.csv` and `window.json`. Another window needs `--out-dir`, so it can never overwrite the files of the first window.
  - `live_report.py --dir DIR`: the report of a window folder. It reads the shared `calibration.json`, and its header names the window's node. On the first window it gives a byte-identical `report.md` and `report.json`.
  - `live_windows.py`: the rule of 4B.12. It writes `results/autoscaler_live/windows.json` with the best window of every node and rule.
  - `live_windows_report.py`: the tables over all four windows, the answers and `windows_workers.png`.
- **Folders:** each new window has its own folder, `results/autoscaler_live/calm/`, `rise/` and `spiky/`, with the window, the step CSVs, the run JSONs, `report.md` and the plots. The response times of all requests go to `data/autoscaler_live/<window>/`, not to git. The files of the first window stay where they were.
- **Runs:** `live_run.py` already had `--window-dir`, `--out-dir` and `--data-dir`. One batch ran the 9 runs one after another, with 30 s between runs, on 16 October 2026 from 08:24 to 13:05. Each run rebuilds the cluster from scratch. A failed run would be retried once and then skipped. All 9 runs worked on the first try and left no container behind.
- **Check first:** a 1-minute KHPA run on the rise window, steps 88 to 90, tested the new folders, the Prometheus query and the cleanup before the long runs.

### 4B.14 KHPA's CPU read: wait for a fresh scrape

- **Bug:** KHPA asked Prometheus for `sum(rate(...[15s]))` right at each step start. Prometheus scrapes cAdvisor every 5 s, and the newest scrape was often not stored yet. The 15 s window then held 2 samples instead of 3, and rate() read too low. How often that happened depended on the offset between the 10 s step clock and the 5 s scrape clock, which stays the same for a whole run. On the rise window KHPA saw only 82% of the real CPU (finding 4.17). Its other runs saw 98% to 100%.
- **Fix:** `fresh_cpu()` in `autoscaler/live.py`.
  1. After the step start, KHPA waits until Prometheus has stored a cAdvisor scrape that is newer than the step start. It asks for the time of the newest scrape with `timestamp(up{job="cadvisor"})`.
  2. KHPA evaluates its query at that scrape's own time. The window then always holds that scrape and the two before it. cAdvisor stamps its samples 0.15 to 1.9 s before the scrape, so no fourth sample slips in.
  3. Step 0 starts 0.5 s before a scrape. A step is 10 s and the scrape interval 5 s, so every step start is followed by a scrape 0.5 s later. The wait is then about 0.6 s in every run, and not anywhere from 0 to 5 s depending on chance.
- **Unchanged:** the KHPA rule. It still wants ceil(CPU / 0.35) workers, at least 1, with the same cooldowns. The query and its 15 s window are also the same. Only when the query is evaluated changed. KHPA now acts about 0.6 s after the step start instead of right at it.
- **Other scalers:** no autoscaling and the planner do not use this value. The runner now reads it after their decision, only for the log. Their runs were not repeated.
- **Check in every report:** `report.md` now gives the share of the real CPU that KHPA saw, against the target of 98% to 100%. The run JSON has it as `prom_share_of_real_cpu`, together with the wait per step and the number of stale reads. The step CSVs have two new columns, `prom_wait_s` and `prom_fresh`.
- **Rerun:** KHPA ran again on all four windows on 17 October 2026, from 08:19 to 10:24. All 4 runs worked on the first try. KHPA saw 98.6% to 99.1% of the real CPU. Every read was fresh, and the longest wait was 0.74 s. The old KHPA files are kept in a `khpa_old_cpu_read` folder in each window folder, with the old `report.md` and `report.json`.

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

### 4.10 Live, KHPA lands close to Dogani's KHPA

- **Setup:** step 4B, 3 live runs of 30 minutes on node 0's busiest 3 hours (entries 4B.1 to 4B.10). Requested workers come from the real CPU.
- **We found:**

  | Scaler | θU | θO | TU | TO | εn |
  |---|---|---|---|---|---|
  | No autoscaling, 8 workers | 7.63 | 28.80 | 26.67 | 66.11 | 1.00 |
  | KHPA | 4.79 / 6.23 | 3.26 / 3.05 | 31.11 / 32.05 | 17.78 / 18.23 | 2.59 / 1.30 |
  | Planner, FedAvg-BiGRU | 0.27 / 0.26 | 24.62 / 13.04 | 2.78 / 1.65 | 87.78 / 75.12 | 3.93 / 1.59 |

  Each cell is ours / Dogani. Live KHPA is within 1.5 points of Dogani's KHPA on all four metrics. The planner's θU of 0.27 matches his 0.26. Its over-provisioning is about twice his. The εn order matches Dogani: the planner beats KHPA. No autoscaling cannot be compared, because Dogani's fixed pods sit far above the mean demand (θO 152.07), and ours sit at it.
- **Caution:** this is one 3-hour window on one node, not 16 nodes over 17 days.

### 4.11 Which "requested workers" to use changes the winner

- **We found:** with requested workers from the traffic, KHPA looks under-provisioned in 76% of the steps (TU 76.11). Its εn of 3.19 then beats the planner's 2.34. Yet KHPA lost no request, and its p95 stayed at 4.6 ms.
- **Why:** the traffic measure uses the calibration at 18 busy workers. With fewer workers a request costs less CPU (entry 4B.3), so fewer workers are enough. KHPA follows the CPU and uses this. The CPU measure has the opposite weak spot. When no autoscaling saturated its 8 workers at the peak, the CPU asked for at most 12 workers, while the traffic needed up to 18.
- **Consequence:** without saturation the CPU measure is the honest one, and with saturation the traffic measure is. Table 11 depends on that choice. Dogani derives the optimal pods from CPU (p. 17), so our main live table uses CPU.

### 4.12 Users see no difference between KHPA and the planner here

- **We found:** without autoscaling, 124,471 requests failed (5.17%), all of them HAProxy 503s during the peak, and p95 was 1,093 ms. With KHPA and with the planner, no request failed and p95 was 4.6 ms. KHPA had one step with a p95 of 20 ms, at a fast rise.
- **Consequence:** on this window the planner's lower θU shows in the metrics, but not in the response times. A scale-up takes about 0.4 s, and a 30% CPU margin absorbs the one-minute lag of KHPA. The planner pays with 22% more workers on average: 9.25 against 7.56.

### 4.13 Live against simulated

- **We found:** the live planner chose the same worker count as the step 4A simulation in all 180 steps. That is expected, because it only reads the forecasts. KHPA differed in 142 of 180 steps, because live KHPA reads CPU and the simulated one reads traffic. Its metrics are still close: simulated θU 4.65 and θO 3.51 (traffic measure), live 4.79 and 3.26 (CPU measure).
- **Load generator:** in every full run 99% of the requests were queued within 1.1 ms of their planned time. There were no client timeouts and no broken connections. The highest load average was 8.8 on 16 threads.
- **Results:** `results/autoscaler_live/report.md`, plots `plot_none.png`, `plot_khpa.png`, `plot_planner.png`.

### 4.14 Over four windows, the planner always has fewer shortages

- **Note:** the KHPA numbers here come from the runs with the old CPU read. Finding 4.18 gives them after the fix of 4B.14. The planner still has fewer shortages in every window.
- **Setup:** the live runs of step 4B on four windows: the first one and the calm, rise and spiky windows of entry 4B.12. Requested workers come from the real CPU.
- **Dogani:** the planner has the lowest θU and TU (Table 11, p. 17).
- **We found:** this holds in all four windows.

  | Window | θU planner / KHPA | TU planner / KHPA | Failed requests planner / KHPA |
  |---|---|---|---|
  | Original | 0.27 / 4.79 | 2.78 / 31.11 | 0 / 0 |
  | Calm | 0.62 / 1.38 | 11.67 / 23.89 | 0 / 0 |
  | Rise | 0.38 / 14.78 | 1.67 / 59.44 | 0 / 13,755 |
  | Spiky | 0.21 / 2.77 | 1.11 / 13.33 | 2 / 1,336 |

  Two more of Dogani's claims also hold in every window. The planner scales less often, with 14 actions against KHPA's 30 on average. KHPA over-provisions less, with θO 2.48 against 29.09 on average.
- **Users:** unlike on the first window (finding 4.12), users now see a difference. Over all four windows the planner lost 2 requests and KHPA 15,091. KHPA's losses came at the rise and at the spike, as 503s from HAProxy and a few timeouts. The planner pays with 18% more workers on average: 10.08 against 8.58.
- **The forecasts did not see the jumps:** for the jump minute, FedAvg-BiGRU forecast 11.5 workers in the rise window and 12.7 in the spiky window, while 18 were needed. The planner got through because it already ran more workers: 12 against KHPA's 8 at the rise, and 12 against 11 at the spike. That headroom comes from Algorithm 3 itself. It takes the maximum of the next forecasts and removes only 70% of the extra workers.
- **Results:** `results/autoscaler_live/windows_report.md` and `windows_workers.png`.

### 4.15 εn can rank first the scaler that loses requests

- **Note:** this used KHPA's run with the old CPU read on the rise window. After the fix of 4B.14, the planner has the higher εn there too (finding 4.18). The mechanism below still holds for any scaler that runs too few workers.
- **Dogani:** the planner has a higher εn than KHPA (Table 11, p. 17).
- **We found:** with requested workers from CPU, the planner has the higher εn in the original, calm and spiky windows. KHPA has it in the rise window, 6.91 against 4.10. Yet in that window KHPA lost 13,755 requests (0.81%) with a p95 of 494 ms, and the planner lost none.
- **Why:** Eq. 18 multiplies four ratios against no autoscaling. In the rise window KHPA almost never over-provisioned: θO 0.21 and TO 1.67, against 49.50 and 68.89 without autoscaling. These two ratios, 238 and 41, outweigh KHPA's shortages, which are about twice those of no autoscaling. A scaler that runs too few workers most of the time can win εn this way.
- **With requested workers from the traffic:** KHPA has the higher εn in the original, rise and spiky windows. In the calm window εn is not defined, because no autoscaling is never over-provisioned there: its θO and TO are 0.
- **Consequence:** εn alone does not tell which scaler serves users better. Its mean over the four windows is a tie: 3.41 for KHPA and 3.39 for the planner.

### 4.16 On a flat window, no scaler beats fixed workers

- **Dogani:** both scalers beat no autoscaling, with εn above 1 (Table 11, p. 17).
- **We found:** in the calm window, with peak/mean 1.04, εn is 0.80 for KHPA and 0.998 for the planner. No run lost a request. The 17 fixed workers, the mean demand, already fit. KHPA's 30 scaling actions only trade shortages for surpluses. The planner added one worker at the start and kept 18.
- **Why it differs:** Dogani's no autoscaling keeps far more pods than needed (θO 152.07). Ours keeps the window's mean demand, and on flat traffic that is already close to right. In the three windows that move, both scalers beat no autoscaling clearly, with εn 2.59 to 6.91. After the KHPA fix of 4B.14 that range is 2.65 to 4.53, and KHPA's calm εn is 0.81 (finding 4.18).

### 4.17 KHPA's Prometheus input read low in one run

- **We found:** in the rise window, the CPU that KHPA read from Prometheus was 82% of the real CPU over the run. In the other three KHPA runs it was 98% to 100%.
- **No data was lost:** over 25 minutes of that run, Prometheus' CPU counters and the cgroup files agree within 0.1%.
- **Timing:** KHPA reads a 15 s rate at each step start, every 10 s, while Prometheus scrapes every 5 s. During the run KHPA got about 10% less than the same query gives when evaluated afterwards, so the newest scrape was often not stored yet. The rest of the gap comes from how rate() extrapolates in such a short window. The step clock and the scrape clock keep the same offset for a whole run, so one run can read low throughout while others do not. The planner run on the same window read 99.7%.
- **Effect:** in that run KHPA asked for about 18% fewer workers than its own rule would with the real CPU. At the rise it ran 8 workers. Part of its 13,755 lost requests therefore comes from the measurement, not from the KHPA rule.
- **Not changed:** the runs kept the step 4B setup. Reading KHPA's CPU from the cgroup files, or querying a longer window a moment after the step start, would remove this effect in later runs. `windows_report.md` lists this check for every window.
- **Update:** fixed in 4B.14. KHPA now waits for a fresh scrape, and the reruns saw 98.6% to 99.1% of the real CPU.

### 4.18 KHPA after the CPU read fix

- **Setup:** KHPA again on all four windows, with the fixed read of 4B.14. No autoscaling and the planner keep their runs. Requested workers come from the real CPU.
- **We found:**

  | Window | θU old / new | TU old / new | Failed requests old / new | εn old / new | CPU seen old / new |
  |---|---|---|---|---|---|
  | Original | 4.79 / 4.93 | 31.11 / 31.11 | 0 / 1 | 2.59 / 2.65 | 98.0% / 98.6% |
  | Calm | 1.38 / 2.58 | 23.89 / 42.22 | 0 / 0 | 0.80 / 0.81 | 99.8% / 99.1% |
  | Rise | 14.78 / 3.05 | 59.44 / 15.56 | 13,755 / 3,050 | 6.91 / 3.91 | 81.7% / 98.8% |
  | Spiky | 2.77 / 3.42 | 13.33 / 15.00 | 1,336 / 3,483 | 3.35 / 2.97 | 99.3% / 98.6% |

- **Rise:** this is where the fix matters. With the full CPU, KHPA ran 11 workers at the jump instead of 8. It lost 3,050 requests instead of 13,755, and its p95 fell from 494 ms to 5.0 ms. Its εn fell from 6.91 to 3.91, because it now over-provisions sometimes, like a working scaler does.
- **The other windows:** the old reads were already 98% to 100%, so the changes there are run-to-run noise. On the spiky window KHPA ran 10 workers at the one-minute spike instead of 11, and lost 3,483 requests instead of 1,336.
- **Dogani's claims, again:**
  - The planner now has the higher εn in all four windows: 3.93, 1.00, 4.10 and 4.53 against KHPA's 2.65, 0.81, 3.91 and 2.97.
  - The planner still has fewer shortages, scales less often and over-provisions more in every window.
  - Only "both scalers beat no autoscaling" still fails, on the calm window (finding 4.16).
  - The example of finding 4.15 is gone. Over the four windows, εn now ranks the scalers the same way users do.
- **Users:** over the four windows the planner lost 2 requests and KHPA 6,534, against 15,091 before. The planner runs 17% more workers on average: 10.08 against 8.65.
- **Results:** `results/autoscaler_live/windows_report.md`, section "KHPA before and after the CPU read fix".

### 4.19 MAPE comes from the quiet minutes

- **We found:** 31% of the test minutes have less than a quarter of their node's mean traffic. There FedAvg-BiGRU's MAPE at t+3 is 36.2%. In all busier minutes it is 3.2% to 5.3%. The quiet minutes make up about 11 of the 13.96 points.
- **Against a naive forecast:** repeating the last input minute gives a MAPE of 13.13 at t+3. That beats both BiGRUs (13.96 and 13.23). The LSTMs reach 12.68 and 11.95. On MAE the models are clearly better: 506 against 562 requests per minute at t+3.
- **Why:** the models learn with MAE on values scaled to [0, 1] by the node's training maximum, 189,000 to 229,000 requests. A quiet minute with 500 requests is then about 0.003. An error that is tiny in that loss is large relative to 500. The loss hardly sees these minutes, but MAPE weights them as much as any other.
- **Consequence:** our MAPE says more about the quiet minutes than about the busy ones that matter for scaling. The order of the models by MAPE also changes from step to step (finding 4.22).

### 4.20 Dogani's MAPE may not be in real requests

- **Dogani:** gives MAPE as Eq. 13 but does not say whether it is computed on real requests or on the scaled values.
- **We found:** the same FedAvg-BiGRU forecasts give a MAPE at t+3 of 13.96 on real requests, 14.40 on values scaled to [0, 1] and 4.13 on values scaled to [-1, 1]. With [-1, 1], quiet minutes sit near -1, far from 0, so their relative errors shrink. Section 6.2 says the data was scaled to [-1, 1] (entry 3.4).
- **Consequence:** depending on the units, the same forecasts score from 4 to 14. Dogani's 9.04 lies in between, so his MAPE cannot be compared with ours one to one. His MAE of 166.8 also points to traffic far smaller than ours (finding 4.5).
- **Update:** decision 3.12 tests every reading against Dogani's own MAE. Real requests, our reading, fits best, and [-1, 1] fits poorly (finding 4.24).

### 4.21 Our test data is burstier than the real trace

- **We found:** the synthetic traces keep the real distribution over all 87 days: the CV is 1.78 for both. But the test parts differ, because the tournament trend is lost (entry 2.6). Over the same minutes, the real trace has a CV of 1.05 and a peak/mean of 10.0. The 16 test parts have a CV of 1.18 to 2.71 and a peak/mean of 12.5 to 58.2. Over all 87 days the synthetic traces also change more from one minute to the next: lag-1 ACF 0.9935 against 0.9990.
- **Effect:** the naive forecast has a MAPE at t+3 of 11.31 on the real trace's test minutes and 13.13 on our 16 test parts pooled. Per node it ranges from 3.6 to 26.5, and each node's model MAPE follows its naive MAPE.
- **Consequence:** the data explains about 2 of the 4.9 points between our 13.96 and Dogani's 9.04. Even on the real trace, the naive forecast reaches only 11.31. Dogani's traces are other synthetic traces whose test parts we do not have, so the rest cannot be pinned down.
- **Also:** `results/autoscaler/pods_node_00.png` shows up to about 500 pods. It is correct and current, from the same run as `table11.md`. A mean demand of 15 pods at 100% use is 21.9 pods at 70%, and node 0's busiest test minute needs 529 pods, 24 times its mean.

### 4.22 Seed noise is as large as the step pattern

- **We ran:** FedAvg-BiGRU again with seeds 1 and 2, and with 32 units (seed 0), all other settings as in step 3.

  | Run | MAPE t+3 | MAPE t+4 | MAPE t+5 | MAE t+3 |
  |---|---|---|---|---|
  | Seed 0 (step 3) | 13.96 | 14.41 | 12.82 | 506.4 |
  | Seed 1 | 13.37 | 13.73 | 13.40 | 499.1 |
  | Seed 2 | 12.73 | 12.87 | 14.61 | 503.2 |
  | 32 units, seed 0 | 12.52 | 12.36 | 12.91 | 507.8 |

- **Seeds:** at t+3 the three seeds range from 12.73 to 13.96, mean 13.35. At t+5 they range from 12.82 to 14.61. MAE changes by at most 1.5%. Seeds 1 and 2 have no better t+5 than t+3, so that pattern of seed 0 is noise in the quiet minutes (finding 4.19), not an error.
- **32 units:** 12.52 at t+3 is 0.2 points below the lowest seed, with a slightly higher MAE. With one run, this is no clear effect. Section 7.1's 32 units would not close the gap.
- **Consequence:** a single MAPE value of ours is uncertain by about ±1 point. Our gap to Dogani at t+3 is still about 4 points (13.35 against 9.04 for the seed mean).

### 4.23 On [-1, 1], MAPE comes from a few busy minutes

- **We found:** with each node scaled to [-1, 1], where do the minutes land? FedAvg-BiGRU seed 0, t+3:

  | Band | Share of minutes | Position on [-1, 1] | MAPE, real requests | MAPE, [-1, 1] |
  |---|---|---|---|---|
  | Quiet, below 0.25 x node mean | 31.1% | -0.99 | 36.23 | 0.07 |
  | Normal, 0.25 to 2 x node mean | 57.5% | -0.93 | 3.65 | 0.28 |
  | Busy, above 2 x node mean | 11.5% | -0.64 | 5.27 | 34.40 |

- **Why:** the range is set by the training maximum, about 200,000 requests, while a node's mean is about 10,000. So almost every minute sits near -1, and its error is divided by about 1. A quiet minute that is 36% off in real requests counts as 0.07%. Only the busiest minutes cross the middle of the range, where the denominator is near 0. There are 910 of them within 0.05 of 0, 0.23% of all minutes. They are 1,292% off on average and give 2.94 of the 4.13 points.
- **Consequence:** a MAPE on [-1, 1] measures how a few minutes near half the training maximum happen to fall, not forecast quality. It would hide exactly the quiet minutes that drive our real-unit MAPE (finding 4.19).

### 4.24 Dogani's MAE and MAPE fit our reading best

- **We found:** the mean traffic per node that Dogani's MAE and MAPE imply at t+3 (decision 3.12), next to the nearest candidate:

  | Reading | Our 3 seeds, MAPE t+3 | Implied mean per minute | Nearest candidate | Off by | Dogani / our naive |
  |---|---|---|---|---|---|
  | Real requests, skip only zeros (ours) | 13.35 | 4,685 | whole trace per node, test part (4,214) | x1.11 | 0.69 |
  | [0, 1], each node's own scaling | 13.73 | 4,818 | whole trace per node, test part (4,214) | x1.14 | 0.67 |
  | [-1, 1], one scaling for all nodes | 8.50 | 2,983 | whole trace per node, test part (4,214) | x1.41 | 0.86 |
  | [-1, 1], each node's own scaling | 4.11 | 1,441 | trace split over 16 nodes (667) | x2.16 | 1.85 |
  | Real requests, skip below 10% of the node mean | 4.24 | 1,489 | trace split over 16 nodes (667) | x2.23 | 2.03 |
  | Real requests, one total trace of all 16 nodes | 2.51 | 1,534 x 16 | split, test part (4,214) | x2.75 | 3.24 |

  Per node first, and [0, 1] with one scaling for all nodes, give exactly our numbers. Every node has the same number of test minutes, and the global minimum is 0. Skipping below 1% or 5% of the mean behaves like 10%. All readings are in `results/predictor_gap/mape_readings.md`.
- **Reading the table:** real requests fit well. His MAE and MAPE then imply about 4,700 requests per minute per node. The real FIFA trace has 4,214 over its test part, the end of the tournament. The [-1, 1] reading fits poorly. It needs a traffic level 2.2 times away from every candidate. It would also make his model 1.85 times worse than repeating the last minute, while ours is 0.84 under that reading. The other readings fail the same way. A total trace or skipping quiet minutes makes MAPE so small that his 9.04 would be a poor model.
- **Limits:** the check assumes his errors have the same shape as ours, and with four candidates a close match can happen by chance. His MAE is not monotone over the steps either (166.8, 241.3, 221.9), so the implied traffic moves from 4,685 to 5,667 between t+3 and t+4 in every reading.
- **Consequence:** that Dogani computed MAPE on scaled values (suspect #2) is unlikely. His numbers fit together best if he computed it on real requests, as we do, on test traffic like the real trace's last weeks.

### 4.25 Model error against the naive error

- **We found:** dividing each error by the error of repeating the last minute gives a number without units:

  | Run | MAPE ratio t+3 / t+4 / t+5 | MAE ratio t+3 / t+4 / t+5 |
  |---|---|---|
  | FedAvg-BiGRU, 3 seeds | 1.02 / 1.01 / 0.97 | 0.90 / 0.90 / 0.90 |
  | CentralBiGRU, seed 0 | 1.01 / 1.27 / 1.04 | 0.93 / 0.91 / 0.88 |

  The MAE ratio is the same, 0.89 to 0.90, for every seed and step. The MAPE ratio moves from 0.91 to 1.06 with the seed, because the quiet minutes drive it (finding 4.19).
- **Against Dogani:** he reports no naive forecast, so his ratio cannot be computed. Our estimate assumes his naive MAPE behaves like the real trace's over its test part, 11.31 (finding 4.21). His ratio would then be 9.04 / 11.31 = 0.80, against our 1.02.
- **The 4.9 points at t+3:** the gap between our 13.96 and his 9.04 splits into four parts:

  | Part | Points | How |
  |---|---|---|
  | Seed noise | 0.61 | Seed 0's 13.96 against the 3-seed mean of 13.35 |
  | Burstier data | 1.85 | Our ratio 1.02 times the naive gap 13.13 - 11.31 |
  | Measurement | about 0 | The best-fitting reading is ours (finding 4.24) |
  | What remains | 2.46 | The rest of the gap after seed noise and data: ratio 1.02 against his estimated 0.80, times 11.31 |

- **Consequence:** the ratio is a fairer measure for our own claims, because it does not depend on the traffic level or the units. Against Dogani it needs an assumption about his naive score. The 2.46 points are what remains after seed noise and data, and most likely reflect model quality. By our estimate, which assumes his naive score behaves like the real trace's, his model beat the naive forecast by about 20% in MAPE, while ours only matches it. In MAE ours beats it by 10%.

### 4.26 Training on [-1, 1] changes how the score looks, not the forecasts

- **We ran:** FedAvg-BiGRU and CentralBiGRU with inputs and targets scaled to [-1, 1], seed 0, all else as in step 3 (decision 3.12).

  | Run | MAPE real, t+3 / t+4 / t+5 | MAPE on [-1, 1], t+3 | MAE t+3 | Quiet minutes, MAPE t+3 |
  |---|---|---|---|---|
  | FedAvg-BiGRU, [0, 1] | 13.96 / 14.41 / 12.82 | 4.13 | 506.4 | 36.23 |
  | FedAvg-BiGRU, [-1, 1] | 14.22 / 14.04 / 14.07 | 4.05 | 510.0 | 37.05 |
  | CentralBiGRU, [0, 1] | 13.23 / 17.28 / 14.62 | 4.61 | 523.6 | 33.55 |
  | CentralBiGRU, [-1, 1] | 14.72 / 21.50 / 24.51 | 4.58 | 538.7 | 36.96 |

- **FedAvg-BiGRU:** it ran 42 rounds, best round 32. Its real-unit MAPE at t+3, 14.22, is 0.26 points above the highest of the three seeds of finding 4.22, so it is no better. Its MAE is 0.7% higher.
- **CentralBiGRU:** it got worse, with MAPE 24.51 at t+5 and MAE 2.9% higher. With one seed, this may be partly noise.
- **Quiet minutes:** they do not improve, 37.05% and 36.96% against 36.23% and 33.55%. The scaling only moves the values linearly, so the MAE loss still sees a quiet minute's error as tiny.
- **Consequence:** training on [-1, 1] does not help the quiet minutes. Scoring on [-1, 1] makes every model look about 3 times better, whatever it was trained on. Section 6.2's range does not explain the gap.

