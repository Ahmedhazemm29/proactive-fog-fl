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
