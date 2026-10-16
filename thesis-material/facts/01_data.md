# Chapter 1: Data

Source tags: `D x.y` = docs/decisions.md entry x.y (all paths relative to repo root). Page numbers (p.) are Dogani & Khunjush (2024), JPDC 187, 104837, as cited in decisions.md.

## 1.1 Real workload (FIFA World Cup 98)
- Unit: requests per minute, built from the binary logs of the Internet Traffic Archive. [D 1.1; scripts/fifa_workload.py]
- Total 1,352,804,107 requests = number on the archive page and in Dogani (p. 9). A match means no file is missing. [D 1.1]
- Dogani merges all requests of one minute into one record (Sec. 6.1, p. 9). [D 1.1]
- Time zone: both UTC and Paris time (UTC+2, summer time) kept; features use Paris time. Dogani does not say. [D 1.2]
- Reason: log files start/end at Paris midnight; day of week, hour, holidays need local time. [D 1.2]
- Dogani uses 88 days, 30 April to 26 July 1998 (p. 9). Ours: days 6 to 92 = 1 May 00:00 to 26 July 23:59 Paris = 87 days = 125,280 minutes. [D 1.3]
- Day 5 dropped: only the last 30 min of 30 April (logging started 23:30), 325 requests. [D 1.3]
- 10 minutes with 0 requests kept as 0 (8, 17, 18 May); neighbours have 1 to 79 requests; likely short outages or missing logs. [D 1.4]
- Busiest minute of the real trace 229,426 requests; our synthetic traces average ~10,800 requests per minute (real mean 10,798). [D 4.5]
- Real trace maximum: 229,426 requests per minute, 7 July 1998 23:41 Paris time; mean 10,798 req/min; variance/mean C = 34,342 (recomputed from data/fifa_requests_per_minute_days5-92.csv, matches data/synthetic/full_run.log and report.json). [D 4.5, D 2.2]
- Maximum of the one-week test window used for the distribution experiments (15 to 21 June 1998, 10,080 min) is 153,878 (mean 23,896); the old "154 thousand" in D 2.2 was this value, not the full-trace maximum. Lognorm draws reached 624,733 there (4.06x). [data/synthetic/test_week_fit/report.json; D 2.2]
- Fisk draws of 7.8 million per minute in that week test: figure from decisions.md, not found in the saved report (Fisk C = null, infinite variance). [D 2.2]
- Weekly mean: 882 req/min (first week of May), 28,842 (week from 26 June), 982 (last days of July); factor 33. No formal stationarity test. [D 4.1]
- Dogani claims the FIFA data is stationary (Sec. 6.1, p. 10). [D 4.1]
- Figure: FIFA requests per minute plot (scripts/plot_fifa_workload.py) is NOT in this folder; it exists only in the git-ignored data/ of the other worktree. See README.md.

## 1.2 Synthetic traces for 16 edge nodes
- Dogani: one synthetic trace per edge node, method of Koltuk & Schmidt (2020) [71]; keeps CDF and ACF of the real trace (Sec. 6.1, p. 10); no settings given. [D 2.1]
- Ours: Koltuk's two steps. Step 1 draws independent values with the right distribution. Step 2 shuffles values and keeps a shuffle only if the ACF gets closer. Seeds 0 to 15 (one per node). [D 2.1; scripts/synthetic_traces.py]
- Distribution fits tried: genextreme, burr12, lognorm, gamma, weibull_min, fisk. None passed Anderson-Darling; best A^2 = 1045 (lognorm), critical value 2.49. [D 2.2]
- Reason: 125,280 points make AD reject everything (Koltuk used hourly data, a few hundred points). [D 2.2]
- Fisk has infinite variance: draws reached 7.8 million req/min against a real max of 154 thousand; ACF matching stuck (error 0.089 fisk, 0.076 burr12). Lognorm converged slowly, max 4x the real one. [D 2.2]
- Decision: draw values from the real trace itself, with replacement (`--cdf empirical`). Distribution exact. [D 2.2]
- ACF error: lags 1 to 1440 (one day), weight 1/lag. Lag 1 counts 10x lag 10; lags 1 to 10 carry 37% of weight. [D 2.3]
- Why: predictor looks 3 to 5 min ahead. Test week: lag-1 ACF 0.963 with equal weights, 0.994 with 1/lag weights, real 0.998. [D 2.3]
- Stop rule, all three: (1) weighted ACF error <= 0.00001; (2) ACF at lags 1 to 10 within 0.01 of real; (3) ACF at lag 1440 within 0.02. [D 2.4]
- A shuffle is kept if it lowers weighted error plus the amount targets 2 and 3 are outside their limits. Each shuffle swaps values at S = 2 random positions (S = 2 beat S = 5, 10). [D 2.4]
- First run stopped every node at the cap of 200 million iterations after 6.2 h; no node met all targets. [D 2.5]
- `--resume` continued each node; all 16 met all targets after 205 to 271 million iterations in total. Resume redraws the starting values from the seed and checks the saved trace holds exactly those. [D 2.5]
- Limitation: synthetic traces lose the tournament trend (quiet May, busy from mid-June); busy days can appear anywhere. ACF is matched only to lag 1440. [D 2.6, D 4.1]
- Dogani assumes stationarity for the method (Sec. 6.1, p. 10). [D 2.6]
- Figure not in this folder: data/synthetic/node_00.png (CDF, ACF, time series of real vs synthetic). See README.md.

## 1.3 Features, split, windows (data side of prediction)
- 5 features per minute: requests, day of week, hour, minute, holiday. Output: next 5 minutes. [D 3.1; Dogani Sec. 6.1, p. 9]
- Split 60/20/20 in time order: train minutes 0 to 75,168; val 75,168 to 100,224; test 100,224 to 125,280. [results/predictors/report.json; D 3.1]
- Windows per node: train 75,134; val 25,022; test 25,022 (window W = 30). [results/predictors/report.json]
- Holidays (France, `holidays` package): 1 May, 8 May, 21 May, 1 June, 14 July 1998. Dogani does not say which. [D 3.1; report.json]
- No window crosses a split border. [D 3.1]
- Scaling: per node and per feature, min-max to [0, 1]; scaler fitted on the node's training part only. [D 3.4]
- Test period per node: 9 July 1998 14:54 to 26 July 23:55, 25,022 minutes. [D 4A.1]
- Test windows pooled over 16 nodes: ~400,000. [D 4.3]
