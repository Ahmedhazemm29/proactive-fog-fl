#!/bin/sh
# Copy the MQTT worker to the Raspberry Pi and (re)start it there.
# Run from the repository root: pi/deploy.sh
# Only these files go to the Pi (no esp32/ folder, so no secrets.h or .pio).
set -e
PI=pi5@fognode1.local

# --relative keeps the folder names, so the Pi gets ~/fog/workload/... and ~/fog/pi/...
rsync -av --relative \
    workload/Dockerfile.mqtt workload/mqtt_worker.py pi/docker-compose.yml \
    "$PI:fog/"

# Build the image on the Pi (arm64) and start worker 1 and cAdvisor
ssh "$PI" "cd fog/pi && docker compose up -d --build"
