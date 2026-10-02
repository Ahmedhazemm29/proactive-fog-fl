"""
Proactive CPU controller for the worker containers.

"Proactive" means it tries to act *before* a worker gets busy: it looks at
the last 30 seconds of each worker's CPU demand, draws a straight line
through it, and follows that line 10 seconds into the future. The CPU
budget is then split between the workers according to that prediction.
(reactive.py instead waits until a worker is already busy or idle.)

Every LOOP_SECONDS it runs one cycle of:
    1. OBSERVE  - CPU usage and throttled time from Prometheus, current
                  limits from Docker (usage and limits use reactive.py's
                  functions)
    2. PREDICT  - estimate each worker's demand (usage + throttled time),
                  fit a straight line through its recent demand and follow
                  it into the future
    3. DECIDE   - split the CPU budget in proportion to the predictions
    4. ACT      - apply the new limits (the same set_cpus as reactive.py)
    5. LOG      - print the decision and append it to a CSV file

Usage:  python controller/proactive.py      (stop with Ctrl+C)
"""
import csv
import os
import time
from collections import deque
from datetime import datetime

import docker
import requests

# 1. OBSERVE: reuse reactive.py's functions. WORKERS and PROMETHEUS_URL come
#    from there too, so both controllers always watch the same workers.
from reactive import PROMETHEUS_URL, WORKERS, get_cpu_usage, get_current_limit

# 4. ACT: reuse the same actuator reactive.py uses.
from set_cpu import set_cpus


# ----------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------
LOOP_SECONDS = 5            # how often we run one full cycle

HISTORY_SIZE = 6            # readings kept per worker (6 x 5 s = 30 s)
PREDICT_AHEAD_SECONDS = 10  # how far into the future we follow the line

MAX_TOTAL = 1.0             # CPUs shared by all workers together
MIN_LIMIT = 0.1             # a single worker never gets less than this
ROUND_TO = 0.05             # limits are multiples of this (0.35, 0.40, ...)
# MAX_TOTAL and MIN_LIMIT should be multiples of ROUND_TO.

# Seconds per second that each worker spent throttled, i.e. waiting because
# it had used up its CPU limit for the current 100 ms period. Added to the
# usage, this gives the worker's real demand (see estimate_demand below).
# sum by (name) gives exactly one number per worker.
THROTTLED_SECONDS_QUERY = (
    'sum by (name) (rate(container_cpu_cfs_throttled_seconds_total{name=~"fl-worker.*"}[30s]))'
)

# The CSV log lives in data/ (already ignored by git), next to reactive_log.csv.
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "proactive_log.csv")


# ----------------------------------------------------------------------
# 1. OBSERVE (the part reactive.py doesn't have)
# ----------------------------------------------------------------------
def get_throttled_seconds_rate():
    """
    Return how many seconds per second each worker spent throttled,
    e.g. {"fl-worker-1": 0.05, "fl-worker-2": 0.62}.
    Works like reactive.py's get_cpu_usage(), just with THROTTLED_SECONDS_QUERY.
    """
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": THROTTLED_SECONDS_QUERY},
        timeout=5,
    )
    response.raise_for_status()  # turn HTTP errors into Python exceptions

    throttled = {}
    for series in response.json()["data"]["result"]:
        name = series["metric"]["name"]
        throttled[name] = float(series["value"][1])  # the value comes as a string
    return throttled


# ----------------------------------------------------------------------
# 2. PREDICT
# ----------------------------------------------------------------------
def estimate_demand(usage, throttled_rate):
    """
    Estimate how much CPU a worker really wants, in CPUs.

    A worker can never use more CPU than its limit, so usage alone hides
    part of the demand. Our workers run flat out for part of every second.
    When the limit cuts in, the rest of that busy time is spent throttled,
    waiting for the next 100 ms period. So

        time it ran + time it was throttled = time it wanted to run

    which is the same sum as the Grafana query: usage + throttled seconds.
    """
    return usage + throttled_rate


def predict(history):
    """
    Fit a straight line through a worker's recent demand and follow it
    PREDICT_AHEAD_SECONDS into the future.

    history = [(time_in_seconds, demand), ...], oldest first.
    Returns the predicted demand, or None while there are fewer than
    HISTORY_SIZE readings.
    """
    if len(history) < HISTORY_SIZE:
        return None

    # x = time in seconds, counted from the newest reading. The readings sit
    # at roughly -25, -20, ..., -5, 0, so the future point we want is simply
    # x = PREDICT_AHEAD_SECONDS.  y = estimated demand.
    newest_time = history[-1][0]
    xs = [t - newest_time for t, demand in history]
    ys = [demand for t, demand in history]

    # Least-squares line y = slope * x + intercept: the straight line that
    # stays as close as possible to all the points at once.
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    slope = (sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
             / sum((x - mean_x) ** 2 for x in xs))
    intercept = mean_y - slope * mean_x

    # Follow the line into the future, but never predict less than MIN_LIMIT.
    # At a demand trough the line can point below 0 for every worker. If we
    # clipped at 0, a tiny difference (0.07 vs 0.00) would decide the whole
    # split and swing it to 0.90/0.10 for one cycle. Clipping at MIN_LIMIT
    # makes near-idle workers count as equal, so they share the budget evenly.
    predicted = slope * PREDICT_AHEAD_SECONDS + intercept
    return max(predicted, MIN_LIMIT)


# ----------------------------------------------------------------------
# 3. DECIDE
# ----------------------------------------------------------------------
def split_budget(predictions):
    """
    Share MAX_TOTAL between the workers in proportion to their predicted
    demand, without giving anyone less than MIN_LIMIT.
    Returns exact (not yet rounded) limits that add up to MAX_TOTAL.
    """
    limits = {}
    sharing = dict(predictions)  # workers that still get a proportional share
    budget = MAX_TOTAL           # CPU not handed out yet

    while True:
        total = sum(sharing.values())
        if total > 0:
            # Multiply every prediction by the same factor so they fill the budget:
            #   factor < 1: predictions add up to more than the budget -> all shrink
            #   factor > 1: there is leftover -> all grow, in proportion
            factor = budget / total
            shares = {name: p * factor for name, p in sharing.items()}
        else:
            # Nobody is expected to use any CPU: split the budget equally.
            shares = {name: budget / len(sharing) for name in sharing}

        too_small = [name for name, share in shares.items() if share < MIN_LIMIT]
        if not too_small:
            limits.update(shares)
            return limits

        # Give those workers exactly the minimum, then repeat the split for
        # everybody else with what is left of the budget.
        for name in too_small:
            limits[name] = MIN_LIMIT
            budget -= MIN_LIMIT
            del sharing[name]


def round_limits(limits):
    """
    Round every limit to a multiple of ROUND_TO while keeping the total at
    exactly MAX_TOTAL. Rounding each worker on its own could break the
    budget (3 x 0.333 would round to 3 x 0.35 = 1.05), so instead we:
      a) count CPU in whole steps of ROUND_TO (1.0 CPU = 20 steps of 0.05)
      b) round every worker DOWN to whole steps
      c) hand out the steps that are left, one each, to the workers that
         lost the most by rounding down
    """
    exact_steps = {name: limit / ROUND_TO for name, limit in limits.items()}
    steps = {name: int(exact) for name, exact in exact_steps.items()}

    steps_left = round(MAX_TOTAL / ROUND_TO) - sum(steps.values())
    lost_most_first = sorted(steps, key=lambda name: exact_steps[name] - steps[name],
                             reverse=True)
    for name in lost_most_first[:steps_left]:
        steps[name] += 1

    # round(..., 4) only removes floating-point noise like 0.35000000000000003
    return {name: round(count * ROUND_TO, 4) for name, count in steps.items()}


def decide(predictions, limits):
    """
    Work out the new limit for every worker.

    predictions = {"fl-worker-1": 0.45, ...}  predicted demand
                  PREDICT_AHEAD_SECONDS from now (None for a worker
                  without enough history yet)
    limits      = {"fl-worker-1": 0.50, ...}  CPUs currently allowed
    Returns (new_limits, reason).
    """
    # Until every worker has a full history, keep the current limits.
    if any(p is None for p in predictions.values()):
        return dict(limits), "collecting history, keeping current limits"

    # Why there is no headroom: the whole budget is always handed out in
    # proportion to the predictions, so only each worker's *share* of the
    # total matters. Adding 20% headroom would multiply every prediction by
    # 1.2, and that leaves every share unchanged:
    #     1.2*a / (1.2*a + 1.2*b)  =  a / (a + b)
    # Headroom would only start to matter if the leftover were kept unused
    # or shared out some other way, for example equally.
    new_limits = round_limits(split_budget(predictions))
    return new_limits, f"splitting {MAX_TOTAL} CPU in proportion to predicted demand"


# ----------------------------------------------------------------------
# 5. LOG (the CSV part)
# ----------------------------------------------------------------------
def append_to_csv(timestamp, name, usage, old_limit, new_limit, predicted,
                  throttled_rate, demand):
    """
    Add one row to the CSV log, writing the header if the file is new.
    Same columns as reactive_log.csv, plus:
      predicted_usage         the line's prediction of estimated demand
                              (empty while the history is still filling up)
      throttled_seconds_rate  seconds per second the worker spent throttled
      estimated_demand        usage + throttled_seconds_rate, the value fed
                              to the predictor this cycle

    (reactive.py's append_to_csv can't be reused here: its file name and
    its five columns are fixed inside that function.)
    """
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    is_new_file = not os.path.exists(LOG_FILE)
    predicted_text = "" if predicted is None else round(predicted, 4)

    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new_file:
            writer.writerow(["timestamp", "worker", "usage", "old_limit",
                             "new_limit", "predicted_usage",
                             "throttled_seconds_rate", "estimated_demand"])
        writer.writerow([timestamp, name, round(usage, 4), old_limit,
                         new_limit, predicted_text, round(throttled_rate, 4),
                         round(demand, 4)])


# ----------------------------------------------------------------------
# Main loop: OBSERVE -> PREDICT -> DECIDE -> ACT -> LOG, forever
# ----------------------------------------------------------------------
def main():
    client = docker.from_env()

    # The last HISTORY_SIZE demand estimates of each worker, as (time, demand)
    # pairs. A deque with maxlen forgets the oldest reading automatically.
    history = {name: deque(maxlen=HISTORY_SIZE) for name in WORKERS}

    print(f"Proactive controller started. Logging to {os.path.abspath(LOG_FILE)}")
    print("Press Ctrl+C to stop.\n")

    while True:
        now = time.time()
        timestamp = datetime.fromtimestamp(now).isoformat(timespec="seconds")

        # 1. OBSERVE: usage and throttled time from Prometheus, limits from Docker.
        try:
            usage = get_cpu_usage()
            throttled = get_throttled_seconds_rate()
            limits = {name: get_current_limit(client, name) for name in WORKERS}
            missing = [name for name in WORKERS
                       if name not in usage or name not in throttled]
            if missing:
                raise ValueError(f"no Prometheus data for {', '.join(missing)}")
        except Exception as error:
            # Skip this cycle. The line should only be fitted through
            # back-to-back readings, so the history starts again from scratch.
            print(f"[{timestamp}] could not observe: {error}. Restarting history.\n")
            for readings in history.values():
                readings.clear()
            time.sleep(LOOP_SECONDS)
            continue

        # 2. PREDICT: estimate each worker's demand, remember it, then follow
        #    each worker's line into the future.
        demand = {name: estimate_demand(usage[name], throttled[name]) for name in WORKERS}
        for name in WORKERS:
            history[name].append((now, demand[name]))
        predictions = {name: predict(history[name]) for name in WORKERS}

        # 3. DECIDE: split the budget.
        new_limits, reason = decide(predictions, limits)

        # 4. ACT: apply the changes. Shrinking limits go first, so the total
        #    never goes over MAX_TOTAL, not even for a moment.
        for name in sorted(WORKERS, key=lambda n: new_limits[n] - limits[n]):
            if new_limits[name] != limits[name]:
                set_cpus(name, new_limits[name])

        # 5. LOG: print the decision and save it to the CSV.
        print(f"[{timestamp}] {reason}")
        for name in WORKERS:
            p = predictions[name]
            predicted_text = "  -  " if p is None else f"{p:.2f}"
            print(f"  {name}: used {usage[name]:.2f} + throttled {throttled[name]:.2f} "
                  f"= demand {demand[name]:.2f}, predicted {predicted_text}, "
                  f"limit {limits[name]:.2f} -> {new_limits[name]:.2f}")
            append_to_csv(timestamp, name, usage=usage[name], old_limit=limits[name],
                          new_limit=new_limits[name], predicted=p,
                          throttled_rate=throttled[name], demand=demand[name])

        print()  # blank line between cycles
        time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nController stopped.")
