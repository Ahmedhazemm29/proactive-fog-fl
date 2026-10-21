#!/bin/sh
# Copy the fog node's containers to the Raspberry Pi and (re)start them there.
# Run from the repository root: pi/deploy.sh
# The FL aggregator's settings can be given here, e.g.
#   FL_ROUNDS=5 FL_MIN_CLIENTS=6 pi/deploy.sh
# (defaults: no round limit, at least 1 client).
# Only these files go to the Pi (no esp32/ folder, so no secrets.h or .pio).
set -e
PI=pi5@fognode1.local

# --relative keeps the folder names, so the Pi gets ~/fog/workload/... and ~/fog/pi/...
rsync -av --relative \
    workload/Dockerfile.mqtt workload/mqtt_worker.py pi/docker-compose.yml \
    pi/aggregator/Dockerfile pi/aggregator/aggregator.py \
    "$PI:fog/"

# On the Pi: build the images (arm64), start the aggregator fresh (a new run
# with these settings), then start or update worker 1 and cAdvisor.
ssh "$PI" "cd fog/pi \
    && export FL_ROUNDS=${FL_ROUNDS:-0} FL_MIN_CLIENTS=${FL_MIN_CLIENTS:-1} \
    && docker compose build \
    && docker compose up -d --force-recreate fl-aggregator \
    && docker compose up -d"
