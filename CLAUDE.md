# Proactive fog CPU allocation for federated learning

Bachelor thesis: proactive CPU allocation for containers in a fog setup for
federated learning.

- Local folder: `~/Desktop/Bachelor/Autoscaling`
- GitHub: private repo `Ahmedhazemm29/proactive-fog-fl` (branch `master`)
- Python venv: `.venv` in the project root

## Files

- `docker-compose.yml`: 2 workers (`fl-worker-1`, `fl-worker-2`) + cadvisor,
  prometheus (localhost:9090), grafana (localhost:3000)
- `workload/workload.py`: placeholder load. Trains SGDClassifier on sklearn
  digits. Bursty: each second it runs flat out for "intensity" seconds, then
  sleeps. Intensity comes from a load profile, `load/<worker>.json` (mounted
  read-only at /load, re-read every second): sine (default: 120 s,
  0.1 to 1.0), noisy_sine, bursts (seeded), steps, constant. Logs the
  intended intensity every second ("load t=... intensity=...", ground truth).
  Timed with time.monotonic(), so wall-clock jumps don't freeze it.
- `scripts/set_load.py`: change a worker's load live, e.g.
  `set_load.py fl-worker-2 bursts --gap 60` or `set_load.py all profile steps`.
  Named profiles (both workers) are in `load/profiles/`.
- `scripts/run_experiments.py --profile <name>`: alternating reactive/proactive
  runs; restarts the profile before every run so all runs see the same load;
  saves CSVs, runs.csv and the workers' log lines to `data/runs/<profile>/`.
- The controllers never read `load/`: they only see Prometheus and the CPU limits.
- `controller/set_cpu.py`: sets a container's CPU limit (cpu_period=100000,
  cpu_quota)
- `controller/reactive.py`: reactive baseline controller (done, committed).
  Every 5 s: >80% of limit -> +0.1, <20% -> -0.1, min 0.1, total budget 1.0.
  Logs to `data/reactive_log.csv`
- `controller/proactive.py`: proactive controller (in progress). Keeps last 6
  readings, fits a straight line, predicts 10 s ahead, splits the full 1.0
  budget proportionally to predicted demand, min 0.1, rounded to 0.05.
  Logs to `data/proactive_log.csv`. Estimated demand per worker =
  usage rate + throttled seconds rate:
  ```
  sum by (name) (rate(container_cpu_usage_seconds_total{name=~"fl-worker.*"}[30s]))
  + sum by (name) (rate(container_cpu_cfs_throttled_seconds_total{name=~"fl-worker.*"}[30s]))
  ```
  The usage half is `QUERY` in reactive.py, which proactive.py imports.
- `monitoring/grafana/dashboards/proactive-autoscaling.json`: exported dashboard
- `data/` is git-ignored (CSV logs).

## Findings so far

- Reactive run: the busy-first worker holds CPU it no longer needs while the
  other worker is throttled; help arrives about 30 s late.
- Hidden demand: a capped container's usage never exceeds its limit, so
  usage alone hides real demand.
- The throttle-ratio rule (throttled_periods / periods > 0.1) fails for our
  bursty workers: both always look throttled, so limits stay at 0.5/0.5.
- Verified in Grafana: usage + throttled seconds rate shows true demand,
  peaking near 1.0 even when a worker is capped at 0.2.
- For these bursty workers usage is about intensity x limit, not
  min(intensity, limit): the limit applies inside every 100 ms period of a
  burst. So usage hides demand even when average demand is below the limit
  (reactive_log.csv: worker-2 used 0.05 at limit 0.2-0.3, though its demand
  never drops below 0.1).
- Offline simulation (2026-10-02, not yet confirmed on Docker): with usage +
  throttled seconds, the limits follow demand over 0.10-0.90, about 14 s
  behind an ideal split; the throttle-ratio version stays at 0.5/0.5.
  Weak spots: the 30 s rate window causes most of the delay, and at a demand
  trough both predictions can clip to 0, giving one-cycle 0.9/0.1 splits.

- After a boot the system clock can start about 3 h ahead and be corrected by
  NTP later (2026-10-02, 2026-10-04). Containers started in that window log
  future timestamps, and Prometheus then rejects all new samples ("out of
  bounds") for up to an hour, so Grafana and the controllers see no data.

## Conventions

- Keep code simple and beginner-readable, with comments explaining each
  part. Explain changes section by section.
- Never add Claude/AI attribution (Co-Authored-By trailers, "Generated with
  Claude Code") to commits or PR descriptions.
