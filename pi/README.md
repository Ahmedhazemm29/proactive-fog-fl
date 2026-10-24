# pi

The fog node: a Raspberry Pi 5 (arm64, 4 GB, `pi5@fognode1.local`) that runs the MQTT broker, the FL aggregator for the ESP32 FL clients and the worker fed by the ESP32 sensor firmware (`esp32/`).

- `docker-compose.yml`: the FL aggregator (`fl-aggregator`, 1.0 CPU), worker 1 (`fl-worker-1`, `workload/mqtt_worker.py`, 1.0 CPU) and cAdvisor (port 8080). The broker is the separate container `mqtt` on port 1883.
- `aggregator/aggregator.py` and its `Dockerfile`: FedAvg over the ESP32 FL clients, first version without secure aggregation.
- `deploy.sh`: run from the repo root. First copies the data of the earlier runs to the laptop (`pull_runs.py`), then copies only the files the containers need to `~/fog` on the Pi with rsync, builds the images there and starts them. The aggregator always starts a fresh run. `--wait` waits until the run has finished and copies its data too.
- `pull_runs.py`: copies the FL run data from the Pi to `data/fl-runs/` of the main checkout (git-ignored), one folder per run. Read-only on the Pi: rsync only reads there and never deletes anything.

## FL aggregator

It tracks the clients from their `fog/<id>/status` messages: `online-active` (and the older firmware's plain `online`) means active, `online-standby` or `offline` means not. Every board starts in standby; `hardware/tools/fl_control.py join ESP-1 ...` makes it active.

Each round:
1. It waits until at least `FL_MIN_CLIENTS` clients are **active**.
2. The clients active at that moment are the round's participants. A client that joins later waits for the next round.
3. It publishes the global model (`fog/global/model`, retained) and waits for an update from every participant, at most `ROUND_TIMEOUT_S` (10 s). A participant that leaves or goes offline during the round is dropped from it at once, without waiting for the timeout, and its update is dropped too if it had already arrived.
4. It averages the participants' weights, weighted by each client's `num_samples` (FedAvg). Round 1 starts from zeros.

Settings come from the laptop when deploying:

```
python3 hardware/tools/fl_control.py join ESP-1 ESP-2 ESP-3 ESP-4
FL_ROUNDS=5 FL_MIN_CLIENTS=4 pi/deploy.sh --wait   # 5 rounds once 4 clients are active, then copy the data
pi/deploy.sh                                       # no round limit, start with 1 active client
ssh pi5@fognode1.local "docker logs -f fl-aggregator"
```

Per round it logs how many of the active clients answered, the round time, the global loss (the global model on the clients' data, before local training), the average loss after local training, and who did not answer or left during the round. Every run gets its own folder on the Pi, `~/fog/pi/fl-data/<run>/`, with `rounds.csv` (one row per round; `active` is the number of participants when the round started, `dropped` those that left during it, `empty` is `True` when nobody answered: the losses are NaN, the model stays the same and the log line starts with `EMPTY`) and `updates.csv` (one row per client update). One folder per run, so a new column never ends up under an older file's header; the runs before join/leave are in `~/fog/pi/fl-data/rounds.csv` and `updates.csv`. After its rounds it clears the retained model and stops.

For the dashboard (`fl_dashboard/`) it also publishes `fog/global/round`, not retained: `{"phase": "start", "run", "round", "rounds", "participants"}` when a round starts and `{"phase": "end", ...}` with the round's results (the same numbers as in `rounds.csv`, including `"empty"`) when it ends. The model message carries the run's total too (`"rounds"`, 0 = no limit).

### The run data on the laptop

`pi/deploy.sh` runs `python3 pi/pull_runs.py` before every deploy, so no run is only on the Pi when a new one starts, and again after the run with `--wait`. It can also be run by hand at any time. The data goes to `data/fl-runs/` of the main checkout, also when a worktree runs it:

```
data/fl-runs/
├── .pi-mirror/                    # an exact copy of ~/fog/pi/fl-data/
├── control.csv                    # every join/leave/status command of fl_control.py
└── <date>_<run>/                  # e.g. 2026-10-23_1792772831
    ├── rounds.csv, updates.csv
    └── control.csv                # the run's commands, also those sent before it started
                                   # or while it waited for its first clients
```

A run's own folder on the Pi is copied again on every pull while it grows. Runs split out of the old shared files are written once and never overwritten.

## MQTT worker

Change the ESP32 sensor firmware's publish rate (1 to 50 msg/s); the worker's CPU follows it:

```
ssh pi5@fognode1.local "docker exec mqtt mosquitto_pub -t fog/client1/control -m 30"
ssh pi5@fognode1.local "docker stats --no-stream fl-worker-1"
```

Measured on 2026-10-20 with 10 steps per message: 1.5% CPU at 1 msg/s, 26-34% at 30 msg/s (about 0.9 ms per training step).

The Pi's kernel has memory cgroups turned off, so Docker ignores `mem_limit` there; the CPU limit works.
