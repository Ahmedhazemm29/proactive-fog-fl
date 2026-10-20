# pi

The fog node: a Raspberry Pi 5 (arm64, 4 GB, `pi5@fognode1.local`) that runs the MQTT broker and the workers fed by the ESP32 clients in `esp32/`.

- `docker-compose.yml`: worker 1 (`fl-worker-1`, `workload/mqtt_worker.py`, 1.0 CPU) and cAdvisor (port 8080). The broker is the separate container `mqtt` on port 1883.
- `deploy.sh`: run from the repo root. Copies only the worker files to `~/fog` on the Pi with rsync, then builds the image there and starts it.

Change the ESP32's publish rate (1 to 50 msg/s); the worker's CPU follows it:

```
ssh pi5@fognode1.local "docker exec mqtt mosquitto_pub -t fog/client1/control -m 30"
ssh pi5@fognode1.local "docker stats --no-stream fl-worker-1"
```

Measured on 2026-10-20 with 10 steps per message: 1.5% CPU at 1 msg/s, 26-34% at 30 msg/s (about 0.9 ms per training step).

The Pi's kernel has memory cgroups turned off, so Docker ignores `mem_limit` there; the CPU limit works.
