# Proactive fog autoscaling with federated learning

Bachelor thesis by Ahmed Hazem, German International University (GIU), Cairo.

Supervisors: Dr. Yasmine Zaghloul (first), Prof. Dr.-Ing. Ansgar Meroth (second).

This repository reproduces Dogani & Khunjush (2024), "Proactive auto-scaling technique for web applications in container-based edge computing using federated learning model" (JPDC 187, 104837).
A FedAvg-BiGRU model forecasts each edge node's traffic, and a planner adds or removes containers before the load arrives.
We test it in a simulation of 16 edge nodes and live, with real Docker containers on one laptop.

## Status

| Step | What it does | Report |
|---|---|---|
| 1. FIFA workload | Counts the requests per minute of the FIFA World Cup 98 logs: 1,352,804,107 requests over 87 days. | [decisions, step 1](docs/decisions.md#step-1-the-real-fifa-workload) |
| 2. Synthetic traces | Makes 16 edge-node traces with the same distribution and autocorrelation as the real trace. | [decisions, step 2](docs/decisions.md#step-2-synthetic-traces-for-16-edge-nodes) |
| 3. Predictors | Trains FedAvg-BiGRU, FedAvg-LSTM and their central versions, and compares them like Dogani's Table 8. | [table8.md](results/predictors/table8.md) |
| 4A. Simulation | Simulates no autoscaling, KHPA and the planner on all 16 nodes, like Dogani's Table 11. | [table11.md](results/autoscaler/table11.md) |
| 4B. Live demo | Replays real traffic against real Docker containers behind HAProxy, on four 3-hour windows. | [windows_report.md](results/autoscaler_live/windows_report.md) |

All five steps are done. Before the reproduction, the thesis built a testbed for vertical CPU scaling of two containers. Its code and results are in this repo too, see [the earlier part](#earlier-part-vertical-cpu-scaling).

## Key results

| Result | Dogani | Ours | Full report |
|---|---|---|---|
| FedAvg-BiGRU MAPE at t+3 / t+5 | 9.04% / 11.2% | 13.96% / 12.82% | [table8.md](results/predictors/table8.md) |
| Central BiGRU MAPE at t+3 / t+5 | 8.49% / 10.45% | 13.23% / 14.62% | [table8.md](results/predictors/table8.md) |
| Planner θU with FedAvg-BiGRU, simulated | 0.26 | 0.51 | [table11.md](results/autoscaler/table11.md) |
| εn planner / KHPA, simulated | 1.59 / 1.30 | 5.48 / 6.84 | [table11.md](results/autoscaler/table11.md) |
| Planner has fewer shortages than KHPA, live | yes | yes, in 4 of 4 windows | [windows_report.md](results/autoscaler_live/windows_report.md) |
| εn planner / KHPA, live, mean of 4 windows | 1.59 / 1.30 | 3.39 / 2.59 | [windows_report.md](results/autoscaler_live/windows_report.md) |
| Failed requests planner / KHPA, live, 4 windows | not reported | 2 / 6,534 | [windows_report.md](results/autoscaler_live/windows_report.md) |

- **Simulated εn:** KHPA wins in the main run, because it may drop to 1 pod while the planner keeps 5. With a minimum of 5 for both, the planner wins. With 1 for both, it is almost a tie. See findings 4.7 to 4.9 in the [decisions log](docs/decisions.md#findings-that-differ-from-dogani).
- **Why our numbers differ:** our traffic is much burstier, and the paper leaves several settings open. The decisions log explains every difference.

## Repo map

| Path | What it holds |
|---|---|
| [README.md](README.md) | This overview. |
| [.gitignore](.gitignore) | Keeps `data/`, `.venv/`, Python caches and the live load files of the earlier part out of git. |
| [docker-compose.yml](docker-compose.yml) | cAdvisor, Prometheus and Grafana, plus the two workers of the earlier part. |
| [docs/](docs/) | The decisions log, the live demo guide and the guides of the earlier part. |
| [scripts/](scripts/) | One command-line script per step: build the data, train, simulate, run live and report. |
| [predictors/](predictors/) | Step 3 code: features, models, FedAvg and evaluation. |
| [autoscaler/](autoscaler/) | Steps 4A and 4B code: KHPA, the planner, the metrics, the live cluster and the load generator. |
| [live/](live/) | The worker container of the live demo. |
| [monitoring/](monitoring/) | The Prometheus config and the Grafana dashboards. |
| [results/](results/) | All reports, tables, plots and CSVs of every step. |
| [tests/](tests/) | Unit tests for every step. |
| [controller/](controller/) | Earlier part: the reactive and proactive CPU controllers. |
| [workload/](workload/) | Earlier part: the training workload of the two worker containers. |
| [load/](load/) | Earlier part: named load profiles for those workers. |
| [analysis/](analysis/) | Earlier part: scripts that compare the controller runs. |
| [figures/](figures/) | Earlier part: PDF figures of the first controller runs. |
| `data/` | Git-ignored, about 9 GB: the raw FIFA logs, the per-minute trace, the 16 node traces, the model weights and the raw data of every run. The commands below rebuild it, step by step. |

## How to reproduce

Run everything from the repo root, on Linux with Docker and Python 3.10. One-time setup:

```bash
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
```

| Step | Commands | Run time |
|---|---|---|
| 1. FIFA workload | `.venv/bin/python scripts/fifa_workload.py` | about 45 min, mostly downloading 8.2 GB |
| 2. Synthetic traces | `.venv/bin/python scripts/synthetic_traces.py --cdf empirical`, then `.venv/bin/python scripts/synthetic_traces.py --cdf empirical --resume data/synthetic` | 6.2 h, then 1.2 h |
| 3. Predictors | `.venv/bin/python scripts/train_predictors.py` | 34 min on an RTX 4060 laptop GPU |
| 4A. Simulation | `.venv/bin/python scripts/simulate_autoscaler.py` | 15 s |
| 4A. Fair runs | `.venv/bin/python scripts/simulate_autoscaler.py --pods-min 1 --khpa-pods-min 1 --out-dir results/autoscaler_fair/pods_min_1 --pods-dir data/autoscaler_fair/pods_min_1`, and the same with 5 in place of 1 | 15 s each |
| 4A. Sensitivity | `.venv/bin/python scripts/autoscaler_sensitivity.py` | 20 s |
| 4B. Live demo | see below and [docs/demo_live.md](docs/demo_live.md) | about 31 min per run, 6.2 h for all 12 runs |
| Tests | `.venv/bin/python -m unittest discover -s tests` | about 10 s |

Step 4B needs the monitoring stack and the worker image. Then the first window:

```bash
docker compose up -d cadvisor prometheus grafana
docker build -t thesis/live-worker:latest live/worker
docker pull haproxy:2.8.10-alpine
.venv/bin/python scripts/live_calibrate.py                  # about 5 min
.venv/bin/python scripts/live_prepare.py                    # the first window, node 0
.venv/bin/python scripts/live_run.py --scaler none          # then --scaler khpa and --scaler planner
.venv/bin/python scripts/live_report.py
```

The other three windows, here the calm one:

```bash
.venv/bin/python scripts/live_windows.py                    # picks the windows by the rule of decision 4B.12
.venv/bin/python scripts/live_prepare.py --node 1 --start "1998-07-20 08:38" --out-dir results/autoscaler_live/calm
.venv/bin/python scripts/live_run.py --scaler none --window-dir results/autoscaler_live/calm --out-dir results/autoscaler_live/calm --data-dir data/autoscaler_live/calm
.venv/bin/python scripts/live_report.py --dir results/autoscaler_live/calm
```

| Window | Node | First minute |
|---|---|---|
| calm | 1 | 1998-07-20 08:38 |
| rise | 7 | 1998-07-12 00:01 |
| spiky | 2 | 1998-07-20 22:45 |

Rise and spiky use the same commands with their own node, first minute and folder. After the reports of all four windows, `.venv/bin/python scripts/live_windows_report.py` writes [windows_report.md](results/autoscaler_live/windows_report.md).

Each window needs 3 runs of about 31 minutes. The live runs start and remove their own containers, labelled `thesis.live=1`, and use at most 20 of them.

## Where decisions live

Every choice we made, and every place where our results differ from the paper, is in [docs/decisions.md](docs/decisions.md). Each entry says what Dogani says, what we did and why. The entries are numbered by step. The part before the dot names the step, and the part after it counts that step's entries. Reports and commits cite these numbers, for example "decision 4B.14".

- **1.1 to 1.4:** the FIFA trace.
- **2.1 to 2.6:** the synthetic node traces.
- **3.1 to 3.10:** the predictors.
- **4A.1 to 4A.10:** the simulation, the settings of Table 3 and how we read Algorithm 3.
- **4B.1 to 4B.14:** the live demo: the worker, the calibration, the windows and the fixed KHPA CPU read.
- **Findings 4.1 to 4.18:** a section of their own at the end. These are results that differ from Dogani, or that the paper does not report.

## Earlier part: vertical CPU scaling

Two containers share one CPU while they train a small model. A reactive and a proactive controller change their CPU limits every 5 s. The proactive controller beat the reactive one under every load profile.

- **Results:** [results/profiles_summary.md](results/profiles_summary.md).
- **Demo guide:** [docs/demo.md](docs/demo.md).
- **Concepts:** [docs/concepts.md](docs/concepts.md).
