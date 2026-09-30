"""
Reactive CPU controller for the worker containers.

"Reactive" means it only looks at what is happening *right now*:
if a worker is busy it gets more CPU, if it is idle it gives CPU back.
(A proactive controller would instead try to predict the future.)

Every LOOP_SECONDS it runs one cycle of:
    1. OBSERVE  - ask Prometheus how much CPU each worker is using
    2. DECIDE   - compare usage to the worker's current CPU limit
    3. ACT      - apply the new limit with `docker update` (via set_cpu.py)
    4. LOG      - print the decision and append it to a CSV file

Usage:  python controller/reactive.py      (stop with Ctrl+C)
"""
import csv
import os
import time
from datetime import datetime

import docker
import requests

# Reuse the actuator we already have, so limits are applied exactly the
# same way as `python set_cpu.py <name> <cpus>` (cpu_period + cpu_quota).
from set_cpu import PERIOD, set_cpus


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
PROMETHEUS_URL = "http://localhost:9090"
WORKERS = ["fl-worker-1", "fl-worker-2"]

LOOP_SECONDS = 5        # how often we run one observe/decide/act cycle

HIGH_THRESHOLD = 0.80   # usage above 80% of the limit  -> scale up
LOW_THRESHOLD = 0.20    # usage below 20% of the limit  -> scale down
STEP = 0.1              # how many CPUs to add/remove per decision

MIN_LIMIT = 0.1         # a single worker never gets less than this
MAX_TOTAL = 1.0         # all workers together never get more than this

# CPU usage per container, measured in "CPUs" (1.0 = one full core).
# sum by (name) merges any duplicate series cAdvisor reports for the
# same container, so we always get exactly one number per worker.
QUERY = 'sum by (name) (rate(container_cpu_usage_seconds_total{name=~"fl-worker.*"}[30s]))'

# The CSV log lives in data/ (already ignored by git).
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "reactive_log.csv")


# ----------------------------------------------------------------------
# 1. OBSERVE
# ----------------------------------------------------------------------
def get_cpu_usage():
    """Return a dict like {"fl-worker-1": 0.43, "fl-worker-2": 0.12}."""
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": QUERY},
        timeout=5,
    )
    response.raise_for_status()  # turn HTTP errors into Python exceptions

    # Prometheus answers with JSON shaped like:
    # {"data": {"result": [{"metric": {"name": "fl-worker-1"},
    #                       "value": [<timestamp>, "0.43"]}, ...]}}
    usage = {}
    for series in response.json()["data"]["result"]:
        name = series["metric"]["name"]
        value = float(series["value"][1])  # the value comes as a string
        usage[name] = value
    return usage


def get_current_limit(client, name):
    """Read a container's current CPU limit (in CPUs) straight from Docker."""
    container = client.containers.get(name)
    quota = container.attrs["HostConfig"]["CpuQuota"]
    return quota / PERIOD


# ----------------------------------------------------------------------
# 2. DECIDE
# ----------------------------------------------------------------------
def decide(usage, limits):
    """
    Work out the new limit for every worker.

    usage  = {"fl-worker-1": 0.43, ...}   CPUs actually being used
    limits = {"fl-worker-1": 0.50, ...}   CPUs currently allowed
    Returns (new_limits, reasons), both dicts keyed by worker name.
    """
    new_limits = dict(limits)  # start with "no change" for everyone
    reasons = {}
    wants_more = []            # workers that asked for more CPU

    # Pass 1: handle scale-downs first. Any CPU freed here can be handed
    # to a busy worker in pass 2 of the same cycle.
    for name in WORKERS:
        if name not in usage:
            reasons[name] = "no data from Prometheus, keeping limit"
            continue

        ratio = usage[name] / limits[name]  # e.g. 0.45 / 0.50 = 90%

        if ratio > HIGH_THRESHOLD:
            wants_more.append(name)  # decided in pass 2
        elif ratio < LOW_THRESHOLD:
            lowered = round(limits[name] - STEP, 2)
            if lowered >= MIN_LIMIT:
                new_limits[name] = lowered
                reasons[name] = f"usage {ratio:.0%} of limit < {LOW_THRESHOLD:.0%}, scale down"
            else:
                reasons[name] = f"usage {ratio:.0%} of limit is low, but already at minimum"
        else:
            reasons[name] = f"usage {ratio:.0%} of limit is in range, keep"

    # Pass 2: scale-ups, but only while the total budget allows it.
    for name in wants_more:
        ratio = usage[name] / limits[name]
        raised = round(new_limits[name] + STEP, 2)
        total_after = round(sum(new_limits.values()) - new_limits[name] + raised, 2)

        if total_after <= MAX_TOTAL:
            new_limits[name] = raised
            reasons[name] = f"usage {ratio:.0%} of limit > {HIGH_THRESHOLD:.0%}, scale up"
        else:
            reasons[name] = f"usage {ratio:.0%} of limit is high, but total budget {MAX_TOTAL} is used up"

    return new_limits, reasons


# ----------------------------------------------------------------------
# 4. LOG (the CSV part)
# ----------------------------------------------------------------------
def append_to_csv(timestamp, name, usage, old_limit, new_limit):
    """Add one row to the CSV log, writing the header if the file is new."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    is_new_file = not os.path.exists(LOG_FILE)

    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new_file:
            writer.writerow(["timestamp", "worker", "usage", "old_limit", "new_limit"])
        writer.writerow([timestamp, name, round(usage, 4), old_limit, new_limit])


# ----------------------------------------------------------------------
# Main loop: OBSERVE -> DECIDE -> ACT -> LOG, forever
# ----------------------------------------------------------------------
def main():
    client = docker.from_env()
    print(f"Reactive controller started. Logging to {os.path.abspath(LOG_FILE)}")
    print("Press Ctrl+C to stop.\n")

    while True:
        timestamp = datetime.now().isoformat(timespec="seconds")

        # 1. OBSERVE: CPU usage from Prometheus, current limits from Docker.
        try:
            usage = get_cpu_usage()
            limits = {name: get_current_limit(client, name) for name in WORKERS}
        except Exception as error:
            # Prometheus or Docker not reachable: skip this cycle, try again.
            print(f"[{timestamp}] could not observe: {error}")
            time.sleep(LOOP_SECONDS)
            continue

        # 2. DECIDE: compute the new limits.
        new_limits, reasons = decide(usage, limits)

        for name in WORKERS:
            old = limits[name]
            new = new_limits[name]
            used = usage.get(name, 0.0)

            # 3. ACT: only call Docker when the limit actually changes.
            if new != old:
                set_cpus(name, new)

            # 4. LOG: print the decision and save it to the CSV.
            print(f"[{timestamp}] {name}: used {used:.2f} / limit {old:.2f} "
                  f"-> {new:.2f}  ({reasons[name]})")
            append_to_csv(timestamp, name, used, old, new)

        print()  # blank line between cycles
        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nController stopped.")
