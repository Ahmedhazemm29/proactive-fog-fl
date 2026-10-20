# workload

This folder belongs to the earlier part of the thesis. It holds the program of the two worker containers `fl-worker-1` and `fl-worker-2` in `docker-compose.yml`. Each worker trains a small classifier on the sklearn digits data. In every second it works for "intensity" seconds and sleeps for the rest, following its profile in `load/`.

- `workload.py`: the training loop. It logs the intended intensity every second.
- `Dockerfile`: the worker image, python:3.11-slim with numpy and scikit-learn.
- `mqtt_worker.py`: the fog-node worker (on the Raspberry Pi). Instead of a profile, it trains on the sensor values an ESP32 publishes on `fog/client<ID>/data`, with `STEPS_PER_MSG` training steps per message, so its CPU demand follows the ESP32's publish rate. It logs `steps/s=` like `workload.py` and serves messages per second on `:8000/metrics`.
- `Dockerfile.mqtt`: its image, the same base and libraries plus paho-mqtt and prometheus-client. Built on the Pi by `pi/docker-compose.yml`.
