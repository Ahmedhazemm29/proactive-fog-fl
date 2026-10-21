# pi

The fog node: a Raspberry Pi 5 (arm64, 4 GB, `pi5@fognode1.local`) that runs the MQTT broker, the FL aggregator for the ESP32 FL clients and the worker fed by the ESP32 sensor firmware (`esp32/`).

- `docker-compose.yml`: the FL aggregator (`fl-aggregator`, 1.0 CPU), worker 1 (`fl-worker-1`, `workload/mqtt_worker.py`, 1.0 CPU) and cAdvisor (port 8080). The broker is the separate container `mqtt` on port 1883.
- `aggregator/aggregator.py` and its `Dockerfile`: FedAvg over the ESP32 FL clients, first version without secure aggregation.
- `deploy.sh`: run from the repo root. Copies only the files the containers need to `~/fog` on the Pi with rsync, builds the images there and starts them. The aggregator always starts a fresh run.

## FL aggregator

It tracks the online clients from their `fog/<id>/status` messages. Each round it publishes the global model (`fog/global/model`, retained), waits for an update from every online client (at most `ROUND_TIMEOUT_S`, 10 s), and averages the weights, weighted by each client's `num_samples` (FedAvg). Round 1 starts from zeros. Settings come from the laptop when deploying:

```
FL_ROUNDS=5 FL_MIN_CLIENTS=6 pi/deploy.sh      # 5 rounds, start once 6 clients are online
pi/deploy.sh                                   # no round limit, start with 1 client
ssh pi5@fognode1.local "docker logs -f fl-aggregator"
```

Per round it logs the number of clients, the round time, the global loss (the global model on the clients' data, before local training) and the average loss after local training. `~/fog/pi/fl-data/` on the Pi gets `rounds.csv` (one row per round) and `updates.csv` (one row per client update). After its rounds it clears the retained model and stops.

## MQTT worker

Change the ESP32 sensor firmware's publish rate (1 to 50 msg/s); the worker's CPU follows it:

```
ssh pi5@fognode1.local "docker exec mqtt mosquitto_pub -t fog/client1/control -m 30"
ssh pi5@fognode1.local "docker stats --no-stream fl-worker-1"
```

Measured on 2026-10-20 with 10 steps per message: 1.5% CPU at 1 msg/s, 26-34% at 30 msg/s (about 0.9 ms per training step).

The Pi's kernel has memory cgroups turned off, so Docker ignores `mem_limit` there; the CPU limit works.
