#!/bin/sh
# Copy the fog node's containers to the Raspberry Pi and (re)start them there.
# Run from the repository root: pi/deploy.sh [--wait]
# The FL aggregator's settings can be given here, e.g.
#   FL_ROUNDS=5 FL_MIN_CLIENTS=4 pi/deploy.sh
# (defaults: no round limit, at least 1 active client; boards take part
# after hardware/tools/fl_control.py join ...).
#   --wait   wait until the aggregator has finished its FL_ROUNDS, then copy
#            the run's data to the laptop
# Before deploying, the data of the earlier runs is copied to data/fl-runs/
# (pi/pull_runs.py, read-only on the Pi), so no run is only on the Pi when a
# new one starts.
# Only these files go to the Pi (no esp32/ folder, so no secrets.h or .pio).
set -e
PI=pi5@fognode1.local

case "${1:-}" in
    "") WAIT=no ;;
    --wait) WAIT=yes ;;
    *) echo "usage: [FL_ROUNDS=N] [FL_MIN_CLIENTS=N] pi/deploy.sh [--wait]" >&2; exit 2 ;;
esac

# Save the earlier runs first; stops here if that fails
python3 pi/pull_runs.py

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

if [ "$WAIT" = yes ]; then
    if [ "${FL_ROUNDS:-0}" = 0 ]; then
        echo "--wait: FL_ROUNDS is 0 (no limit), so the run only ends when you stop fl-aggregator"
    fi
    echo "Waiting for the aggregator to finish (Ctrl+C stops the waiting, not the run) ..."
    ssh "$PI" "docker wait fl-aggregator" > /dev/null
    python3 pi/pull_runs.py
fi
