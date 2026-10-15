# Live autoscaler demo (step 4B)

This guide reruns one scaler live in about 5 minutes. Real FIFA traffic goes to real worker containers. You watch them scale in Grafana.

## What the demo shows

- **Workers:** each worker is one container with 0.5 CPU. Every request runs one of Dogani's three tasks: sorting, eigenvalues or compression.
- **Load balancer:** HAProxy spreads the requests round-robin over the running workers.
- **Load generator:** it replays node 0's traffic of 23 July 1998. One trace minute takes 10 seconds.
- **Scaler:** one of three.
  - none: 8 fixed workers.
  - khpa: reacts to the CPU it saw in the last step.
  - planner: Dogani's Algorithm 3. It uses FedAvg-BiGRU's forecasts.

The short demo covers steps 60 to 86. That is 08:30 to 08:56 in the trace, when the demand rises from 8 to 16 workers.

## Before the meeting (once)

1. Start the monitoring stack from the repository folder. This starts only these three services, not the FL workers:

   ```bash
   docker compose up -d cadvisor prometheus grafana
   ```

2. If Prometheus and Grafana were already running from an older version of this repository, restart them once. Prometheus then loads the HAProxy scrape job, and Grafana mounts the new dashboard:

   ```bash
   docker compose up -d --force-recreate prometheus grafana
   ```

3. Build the worker image and pull HAProxy:

   ```bash
   docker build -t thesis/live-worker:latest live/worker
   docker pull haproxy:2.8.10-alpine
   ```

4. Check that ports 8090, 8091 and 8404 are free. HAProxy uses them.

## The demo (about 5 minutes)

1. Open Grafana at http://localhost:3000/d/autoscaler-live (login admin / admin). Set the time range to "Last 10 minutes".

2. Start one scaler. The planner is the most interesting:

   ```bash
   .venv/bin/python scripts/live_run.py --scaler planner --first-step 60 --steps 27 --tag demo
   ```

   The run has 3 warm-up steps and 27 measured steps. That is 30 steps of 10 seconds, so 5 minutes. For the reactive scaler, use `--scaler khpa`. For fixed workers, use `--scaler none`.

3. While it runs, point at the dashboard:
   - **Workers:** the orange line is the running workers. The dashed line is the workers the CPU asks for at 70% use.
     - The planner scales up before the demand arrives, because it reads the forecasts.
     - KHPA only follows once the CPU has risen.
   - **CPU per worker:** most workers should stay near the 0.35 line, which is 70% of 0.5. Above 0.5 they are throttled.
   - **Requests waiting in HAProxy:** above 0 means too few workers.

4. After the run, make the table and the plot:

   ```bash
   .venv/bin/python scripts/live_report.py --tag demo
   ```

   This writes `results/autoscaler_live/report_demo.md` and `plot_planner_demo.png`. The plot shows the requested and running workers per step, with the p95 response time below. The report also lists the step 4A simulation of the same steps. For the planner, the worker counts must be equal, because it only reads the forecasts.

   For a comparison table, run two or three scalers with the same `--first-step`, `--steps` and `--tag`. εn needs the `none` run.

## The full runs

The full window has 180 steps and takes about 31 minutes per scaler:

```bash
.venv/bin/python scripts/live_run.py --scaler none
.venv/bin/python scripts/live_run.py --scaler khpa
.venv/bin/python scripts/live_run.py --scaler planner
.venv/bin/python scripts/live_report.py
```

The results are in `results/autoscaler_live/report.md`. To redo the setup from scratch, run `scripts/live_calibrate.py` (about 5 minutes) and then `scripts/live_prepare.py`.

## If something goes wrong

- **Stopping and cleanup:** Ctrl+C stops a run and removes all its containers. The runner also cleans up after an error. To clean up by hand:

  ```bash
  docker rm -f $(docker ps -aq --filter label=thesis.live=1)
  docker network rm live-net
  ```

  This only touches containers with the label `thesis.live=1`.
- **Empty HAProxy panels:** Prometheus does not have the `live-haproxy` job yet. Redo step 2 of "Before the meeting". The worker and CPU panels only need cAdvisor.
- **Prometheus not reachable:** KHPA then uses the CPU from the cgroup files. The run JSON counts these steps as `prom_missing`.
- **Laptop load:** a full run peaks at 18 workers, about 6 to 8 CPU cores. The run CSV logs the load average of every step.
