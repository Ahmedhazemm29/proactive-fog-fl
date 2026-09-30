# Thesis Autoscaler

Testbed for a bachelor thesis on **proactive vertical CPU autoscaling** of containers.

Two Docker containers run a lightweight ML training loop whose CPU demand follows a
predictable sine wave. cAdvisor, Prometheus and Grafana record how much CPU each worker
uses compared with its limit. A small Python actuator changes a running container's CPU
limit. A forecasting controller that calls this actuator is planned but not written yet.

```
 ┌──────────────┐   ┌──────────────┐
 │ fl-worker-1  │   │ fl-worker-2  │   ← workload (0.5 CPU each at start)
 └──────┬───────┘   └──────┬───────┘
        │ cgroup stats     │
        ▼                  ▼
   ┌─────────┐  scrape 5s ┌────────────┐      ┌─────────┐
   │cAdvisor │ ─────────▶ │ Prometheus │ ───▶ │ Grafana │
   └─────────┘            └────────────┘      └─────────┘

 controller/set_cpu.py ── docker update (cpu_quota) ──▶ fl-worker-N
```

## Repository layout

| Path | Purpose |
|------|---------|
| `docker-compose.yml` | The full stack: 2 workers + cAdvisor, Prometheus and Grafana |
| `workload/workload.py` | Training loop with a CPU demand that follows a sine wave |
| `workload/Dockerfile` | Worker image (`python:3.11-slim` + numpy + scikit-learn) |
| `controller/set_cpu.py` | Actuator: sets a container's CPU limit at runtime |
| `monitoring/prometheus.yml` | Prometheus scrape config (cAdvisor every 5 s) |
| `monitoring/grafana/provisioning/` | Sets up Prometheus as Grafana's default datasource |

## Prerequisites

- Linux host with Docker Engine and the Docker Compose v2 plugin
- Python 3.9+ for the controller
- Free ports: `3000` (Grafana), `8080` (cAdvisor), `9090` (Prometheus)

cAdvisor runs `privileged` and mounts `/`, `/sys` and `/var/lib/docker` read-only. It
needs these mounts to read per-container cgroup stats.

## Quick start

```bash
# 1. Build the worker image and start everything
docker compose up -d --build

# 2. Check that the workers are running
docker compose ps
docker logs -f fl-worker-1
```

Every 10 s, each worker logs a line like this:

```
t=    60s intensity=0.55 steps/s=  142.3 acc=0.912
```

| UI | URL | Login |
|----|-----|-------|
| Grafana | http://localhost:3000 | `admin` / `admin` |
| Prometheus | http://localhost:9090 | – |
| cAdvisor | http://localhost:8080 | – |

## The workload

`workload.py` divides time into 1-second slots. In each slot the worker trains an
`SGDClassifier` on the sklearn *digits* dataset for `intensity` seconds, then sleeps for
the rest of the slot. The intensity follows a sine wave between 0.1 and 1.0 CPU:

```
intensity(t) = 0.1 + 0.9 · (sin(2π·t / PERIOD_S) + 1) / 2
```

Because the demand is periodic, a forecaster can learn it. If the CPU limit is below
the current demand, `steps/s` drops. That drop is the measurable cost of giving a worker
too little CPU.

Environment variables:

| Variable | Default | Meaning |
|----------|---------|---------|
| `PERIOD_S` | `120` | Length of one load cycle, in seconds |
| `BATCH` | `256` | Mini-batch size per training step |
| `LOG_EVERY_S` | `10` | How often to print throughput and accuracy |

Each worker starts with `cpu_quota: 50000` / `cpu_period: 100000`, which is **0.5 CPU**,
and a 512 MB memory limit. That is below the peak demand of 1.0 CPU, so throttling is
visible from the start.

## Changing CPU limits (controller)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r controller/requirements.txt

python controller/set_cpu.py fl-worker-1 1.0    # give worker-1 a full CPU
python controller/set_cpu.py fl-worker-2 0.25   # squeeze worker-2
```

The script does the same as `docker update --cpu-quota`. It keeps `cpu_period` at
100 000 µs, which must match the value in `docker-compose.yml`, and sets
`cpu_quota = cpus × period`. You can also import `set_cpus(name, cpus)` from another
script.

Your user needs access to the Docker socket (member of the `docker` group, or use `sudo`).

## Useful PromQL queries

cAdvisor labels containers by `name`:

```promql
# CPU usage, in cores
rate(container_cpu_usage_seconds_total{name=~"fl-worker-.*"}[30s])

# CPU limit, in cores
container_spec_cpu_quota{name=~"fl-worker-.*"} / container_spec_cpu_period{name=~"fl-worker-.*"}

# Throttled time: shows when the limit is too low
rate(container_cpu_cfs_throttled_seconds_total{name=~"fl-worker-.*"}[30s])
```

> **Note:** Only the Grafana *datasource* is in the repo. The dashboard itself lives in
> the `grafana-data` Docker volume. To keep it in the repo, export it as JSON and add a
> dashboard provider under `monitoring/grafana/provisioning/dashboards/`.

## Stopping and cleaning up

```bash
docker compose down        # stop containers, keep Prometheus and Grafana data
docker compose down -v     # also delete the prometheus-data and grafana-data volumes
```

## Roadmap

- [x] Workload with a periodic CPU demand
- [x] Monitoring stack (cAdvisor → Prometheus → Grafana)
- [x] CPU actuator (`set_cpu.py`)
- [ ] Proactive controller: forecast demand from Prometheus and resize ahead of time
- [ ] Reactive baseline for comparison
- [ ] Experiments: throughput loss vs. CPU over-allocation
